import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseBadRequest, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods, require_POST

from billing.limits import check_limit
from forms_app.models import Form, Submission
from spam.features import extract_text

PREVIEW_CHARS = 120
PAGE_SIZE = 25
_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_SHADOW_SIGNAL = "model_shadow"

STATUS_FILTERS = [
    ("all", "All"),
    ("ham", "Ham"),
    ("spam", "Spam"),
    ("possible_spam", "Possible spam"),
]
_STATUS_FILTER_VALUES = {value for value, _ in STATUS_FILTERS}


def _get_owned_form(request, pk):
    return get_object_or_404(Form, pk=pk, account=request.user.account)


def _get_owned_submission(request, form_obj, submission_pk, queryset=None):
    qs = queryset if queryset is not None else Submission.objects
    return get_object_or_404(qs, pk=submission_pk, form=form_obj)


def _status_filter(request):
    status = request.GET.get("status", "all")
    return status if status in _STATUS_FILTER_VALUES else "all"


def _is_possible_spam(submission) -> bool:
    return submission.status == Submission.Status.HAM and _SHADOW_SIGNAL in submission.spam_signals


def _filter_submissions(qs, status):
    if status == "possible_spam":
        return qs.filter(status=Submission.Status.HAM, spam_signals__contains=[_SHADOW_SIGNAL])
    if status != "all":
        return qs.filter(status=status)
    return qs


def _row_visible_under_filter(submission, status) -> bool:
    if status == "all":
        return True
    if status == "possible_spam":
        return _is_possible_spam(submission)
    return submission.status == status


def _submission_list_context(form_obj, status, page):
    qs = _filter_submissions(form_obj.submissions.all(), status).order_by("-created_at")
    paginator = Paginator(qs, PAGE_SIZE)
    page_obj = paginator.get_page(page)
    rows = [{"submission": s, "preview": extract_text(s.payload)[:PREVIEW_CHARS]} for s in page_obj]
    return {
        "form_obj": form_obj,
        "status": status,
        "page_obj": page_obj,
        "rows": rows,
        "filters": STATUS_FILTERS,
    }


@login_required
def home(request):
    account = request.user.account
    start_of_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    forms = account.forms.annotate(
        ham_count=Count("submissions", filter=Q(submissions__status=Submission.Status.HAM)),
        spam_count=Count("submissions", filter=Q(submissions__status=Submission.Status.SPAM)),
        ham_this_month=Count(
            "submissions",
            filter=Q(
                submissions__status=Submission.Status.HAM,
                submissions__created_at__gte=start_of_month,
            ),
        ),
    )
    forms_limit = check_limit(account, "forms")
    submissions_limit = check_limit(account, "submissions")
    return render(
        request,
        "dashboard/home.html",
        {"forms": forms, "forms_limit": forms_limit, "submissions_limit": submissions_limit},
    )


@login_required
def submission_list(request, pk):
    form_obj = _get_owned_form(request, pk)
    status = _status_filter(request)
    context = _submission_list_context(form_obj, status, request.GET.get("page"))
    return render(request, "dashboard/submissions_list.html", context)


@login_required
def submission_detail(request, pk, submission_pk):
    form_obj = _get_owned_form(request, pk)
    detail_qs = Submission.objects.select_related("model_version")
    submission = _get_owned_submission(request, form_obj, submission_pk, queryset=detail_qs)
    context = {"form_obj": form_obj, "submission": submission}
    return render(request, "dashboard/submission_detail.html", context)


def _label_message(target_status) -> str:
    return "Marked as ham." if target_status == Submission.Status.HAM else "Marked as spam."


@login_required
@require_POST
def submission_label(request, pk, submission_pk):
    form_obj = _get_owned_form(request, pk)
    submission = _get_owned_submission(request, form_obj, submission_pk)

    target_status = request.POST.get("status")
    if target_status not in (Submission.Status.HAM, Submission.Status.SPAM):
        return HttpResponseBadRequest("status must be 'ham' or 'spam'")

    if target_status != submission.status:
        submission.status = target_status
        submission.corrected = target_status != submission.original_status
        submission.corrected_at = timezone.now() if submission.corrected else None
        submission.save(update_fields=["status", "corrected", "corrected_at"])

    message = _label_message(target_status)

    if request.headers.get("HX-Request") == "true":
        fragment = request.POST.get("fragment", "row")
        list_filter = request.POST.get("filter", "all")
        if list_filter not in _STATUS_FILTER_VALUES:
            list_filter = "all"
        undo_status = (
            Submission.Status.SPAM
            if target_status == Submission.Status.HAM
            else Submission.Status.HAM
        )
        toast_html = render_to_string(
            "dashboard/_toast_oob.html",
            {
                "form_obj": form_obj,
                "submission": submission,
                "message": message,
                "undo_status": undo_status,
                "undo_fragment": "panel" if fragment == "row" else "status",
                "list_filter": list_filter,
            },
            request=request,
        )

        if fragment == "status":
            body = render_to_string(
                "dashboard/_submission_status.html",
                {"form_obj": form_obj, "submission": submission},
                request=request,
            )
        elif fragment == "panel":
            # Reuses the whole-page render + client-side hx-select="#submissions-panel"
            # trick the filter tabs already use, rather than a dedicated panel-only
            # partial — Undo is rare enough that this is the pragmatic choice.
            context = _submission_list_context(form_obj, list_filter, request.POST.get("page"))
            body = render_to_string("dashboard/submissions_list.html", context, request=request)
        else:
            if _row_visible_under_filter(submission, list_filter):
                body = render_to_string(
                    "dashboard/_submission_row.html",
                    {
                        "form_obj": form_obj,
                        "status": list_filter,
                        "row": {
                            "submission": submission,
                            "preview": extract_text(submission.payload)[:PREVIEW_CHARS],
                        },
                    },
                    request=request,
                )
            else:
                body = ""

        return HttpResponse(body + toast_html)

    messages.success(request, message)
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect("dashboard:submission_list", pk=form_obj.pk)


@login_required
@require_http_methods(["GET", "POST"])
def submission_delete(request, pk, submission_pk):
    form_obj = _get_owned_form(request, pk)
    submission = _get_owned_submission(request, form_obj, submission_pk)

    if request.method == "POST":
        submission.delete()
        messages.success(request, "Submission deleted.")
        return redirect("dashboard:submission_list", pk=form_obj.pk)

    return render(
        request,
        "dashboard/submission_delete_confirm.html",
        {"form_obj": form_obj, "submission": submission},
    )


def _csv_safe(value) -> str:
    text = "" if value is None else str(value)
    if text and text[0] in _INJECTION_PREFIXES:
        return "'" + text
    return text


def _csv_flatten(value):
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return value


def _payload_key_union(form_obj, status):
    sql = "SELECT DISTINCT jsonb_object_keys(payload) FROM forms_app_submission WHERE form_id = %s"
    params = [str(form_obj.id)]
    if status == "possible_spam":
        sql += " AND status = %s AND spam_signals @> %s::jsonb"
        params.append(Submission.Status.HAM)
        params.append(f'["{_SHADOW_SIGNAL}"]')
    elif status != "all":
        sql += " AND status = %s"
        params.append(status)
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return sorted(row[0] for row in cursor.fetchall())


class _Echo:
    """File-like object whose write() returns the value, so csv.writer's
    output can be yielded directly from a generator (Django's documented
    pattern for streaming CSV)."""

    def write(self, value):
        return value


@login_required
def submissions_csv(request, pk):
    form_obj = _get_owned_form(request, pk)
    status = _status_filter(request)

    qs = _filter_submissions(form_obj.submissions.all(), status).order_by("-created_at")

    payload_keys = _payload_key_union(form_obj, status)
    header = ["id", "created_at", "status", "spam_score", *payload_keys]

    writer = csv.writer(_Echo())

    def rows():
        yield "﻿"
        yield writer.writerow(_csv_safe(cell) for cell in header)
        for submission in qs.iterator():
            row = [
                submission.id,
                submission.created_at.isoformat(),
                submission.status,
                submission.spam_score,
            ]
            for key in payload_keys:
                row.append(_csv_flatten(submission.payload.get(key, "")))
            yield writer.writerow(_csv_safe(cell) for cell in row)

    response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
    date_str = timezone.now().date().isoformat()
    slug = slugify(form_obj.name) or str(form_obj.id)
    response["Content-Disposition"] = f'attachment; filename="{slug}-submissions-{date_str}.csv"'
    return response

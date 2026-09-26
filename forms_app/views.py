from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from forms_app.forms import FormCreateForm, FormEditForm
from forms_app.models import Form


def _get_owned_form(request, pk):
    return get_object_or_404(Form, pk=pk, account=request.user.account)


def _html_snippet(form_obj):
    return f"""<form action="{form_obj.endpoint_url}" method="POST">
  <input type="text" name="name" placeholder="Your name" required>
  <input type="email" name="email" placeholder="Your email" required>
  <textarea name="message" placeholder="Message" required></textarea>
  <input type="text" name="_honeypot" tabindex="-1" autocomplete="off"
         aria-hidden="true" style="position:absolute;left:-9999px;">
  <input type="hidden" name="_ts" id="easyforms-ts">
  <script>document.getElementById('easyforms-ts').value = Date.now();</script>
  <button type="submit">Send</button>
</form>"""


def _fetch_snippet(form_obj):
    return f"""fetch("{form_obj.endpoint_url}", {{
  method: "POST",
  headers: {{ "Content-Type": "application/json" }},
  body: JSON.stringify({{
    name: "Jane Doe",
    email: "jane@example.com",
    message: "Hello!",
    _honeypot: "",
    _ts: Date.now()
  }})
}})
  .then(res => res.json())
  .then(data => console.log(data));"""


@login_required
def form_create(request):
    if request.method == "POST":
        create_form = FormCreateForm(request.POST)
        if create_form.is_valid():
            new_form = create_form.save(commit=False)
            new_form.account = request.user.account
            # TODO(Day 7): check_limit(request.user.account, "forms")
            new_form.save()
            return redirect("forms_app:detail", pk=new_form.pk)
    else:
        create_form = FormCreateForm()

    return render(request, "forms_app/form_new.html", {"form": create_form})


@login_required
def form_detail(request, pk):
    form_obj = _get_owned_form(request, pk)

    if request.method == "POST":
        edit_form = FormEditForm(request.POST, instance=form_obj)
        if edit_form.is_valid():
            edit_form.save()
            messages.success(request, "Form updated.")
            return redirect("forms_app:detail", pk=form_obj.pk)
    else:
        edit_form = FormEditForm(instance=form_obj)

    return render(
        request,
        "forms_app/form_detail.html",
        {
            "form_obj": form_obj,
            "edit_form": edit_form,
            "html_snippet": _html_snippet(form_obj),
            "fetch_snippet": _fetch_snippet(form_obj),
        },
    )


@login_required
@require_POST
def form_deactivate(request, pk):
    form_obj = _get_owned_form(request, pk)
    form_obj.is_active = False
    form_obj.save(update_fields=["is_active", "updated_at"])
    messages.success(request, "Form deactivated.")
    return redirect("forms_app:detail", pk=form_obj.pk)


@login_required
@require_POST
def form_activate(request, pk):
    form_obj = _get_owned_form(request, pk)
    form_obj.is_active = True
    form_obj.save(update_fields=["is_active", "updated_at"])
    messages.success(request, "Form activated.")
    return redirect("forms_app:detail", pk=form_obj.pk)

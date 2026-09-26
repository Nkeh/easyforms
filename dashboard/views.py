from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from billing.limits import check_limit


@login_required
def home(request):
    account = request.user.account
    forms = account.forms.all()
    forms_limit = check_limit(account, "forms")
    return render(request, "dashboard/home.html", {"forms": forms, "forms_limit": forms_limit})

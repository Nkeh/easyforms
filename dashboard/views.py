from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    forms = request.user.account.forms.all()
    return render(request, "dashboard/home.html", {"forms": forms})

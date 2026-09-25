import pytest

from accounts.models import Account, User

pytestmark = pytest.mark.django_db


def test_create_user_sets_expected_fields_and_hashes_password():
    user = User.objects.create_user(email="Owner@Example.com", password="s3cret-pass")

    assert user.email == "Owner@example.com"  # Django's normalize_email lowercases the domain only
    assert user.check_password("s3cret-pass")
    assert user.password != "s3cret-pass"
    assert user.is_active is True
    assert user.is_staff is False
    assert user.is_superuser is False
    assert user.is_verified is False


def test_create_user_without_account_auto_creates_one():
    user = User.objects.create_user(email="solo@example.com", password="s3cret-pass")

    assert user.account is not None
    assert user.account.plan == "free"
    assert Account.objects.filter(pk=user.account_id).exists()


def test_create_user_with_explicit_account_reuses_it():
    account = Account.objects.create(name="Acme Inc")

    user = User.objects.create_user(
        email="member@example.com", password="s3cret-pass", account=account
    )

    assert user.account_id == account.id
    assert Account.objects.count() == 1


def test_create_superuser_sets_staff_and_superuser_flags():
    admin_user = User.objects.create_superuser(email="admin@example.com", password="s3cret-pass")

    assert admin_user.is_staff is True
    assert admin_user.is_superuser is True
    assert admin_user.is_verified is True
    assert admin_user.account is not None


def test_create_superuser_rejects_is_staff_false():
    with pytest.raises(ValueError):
        User.objects.create_superuser(
            email="admin2@example.com", password="s3cret-pass", is_staff=False
        )

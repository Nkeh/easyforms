from django.http import HttpRequest
from django.test import override_settings
from django.views.defaults import server_error


@override_settings(DEBUG=False)
def test_404_page_renders_for_unknown_url(client):
    response = client.get("/no-such-path-xyz/")

    assert response.status_code == 404
    assert b"Page not found" in response.content


@override_settings(DEBUG=False)
def test_500_page_renders_with_no_db_access_and_no_request_context():
    # The bare HttpRequest has no session/user/middleware attached — this is
    # exactly Django's own contextless rendering of the default handler500
    # (Context(), not RequestContext, when DEBUG=False), so anything the
    # template touched that needed a real request or a DB-backed messages
    # store would raise here instead of just rendering.
    response = server_error(HttpRequest())

    assert response.status_code == 500
    assert b"Something went wrong" in response.content

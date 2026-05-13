import pytest

from services.auth_service import (
    build_line_authorize_url,
    fetch_line_profile,
    resolve_line_callback_url,
)
from utils.errors import ServiceUnavailableError, ValidationError


@pytest.mark.parametrize("line_channel_id", [None, ""])
def test_build_line_authorize_url_requires_line_channel_id(line_channel_id):
    with pytest.raises(ServiceUnavailableError) as exc_info:
        build_line_authorize_url(
            line_channel_id,
            "https://example.com/callback",
            "state-token",
        )

    assert "LINE_CHANNEL_ID" in exc_info.value.message


@pytest.mark.parametrize("line_callback_url", [None, ""])
def test_build_line_authorize_url_requires_line_callback_url(line_callback_url):
    with pytest.raises(ServiceUnavailableError) as exc_info:
        build_line_authorize_url("channel-id", line_callback_url, "state-token")

    assert "LINE_CALLBACK_URL" in exc_info.value.message


@pytest.mark.parametrize("state", [None, ""])
def test_build_line_authorize_url_requires_state(state):
    with pytest.raises(ValidationError) as exc_info:
        build_line_authorize_url("channel-id", "https://example.com/callback", state)

    assert "OAuth state" in exc_info.value.message


def test_build_line_authorize_url_includes_encoded_redirect_uri_and_state():
    url = build_line_authorize_url(
        "channel-id",
        "https://example.com/line/callback?next=/member center",
        "state-token",
    )

    assert "client_id=channel-id" in url
    assert (
        "redirect_uri=https%3A//example.com/line/callback%3Fnext%3D/member%20center"
        in url
    )
    assert "state=state-token" in url


def test_resolve_line_callback_url_uses_configured_external_url():
    callback_url = resolve_line_callback_url(
        "https://example.com/api/line/callback",
        "https://request.example.com/api/line/callback",
        "request.example.com",
    )

    assert callback_url == "https://example.com/api/line/callback"


def test_resolve_line_callback_url_keeps_localhost_for_local_requests():
    callback_url = resolve_line_callback_url(
        "http://localhost:5000/api/line/callback",
        "http://localhost:5000/api/line/callback",
        "localhost:5000",
    )

    assert callback_url == "http://localhost:5000/api/line/callback"


def test_resolve_line_callback_url_replaces_localhost_for_external_requests():
    callback_url = resolve_line_callback_url(
        "http://localhost:5000/api/line/callback",
        "http://140.119.143.95:5000/api/line/callback",
        "140.119.143.95:5000",
    )

    assert callback_url == "http://140.119.143.95:5000/api/line/callback"


def test_fetch_line_profile_requires_line_channel_secret():
    with pytest.raises(ServiceUnavailableError) as exc_info:
        fetch_line_profile(
            "code-token",
            "channel-id",
            "",
            "https://example.com/api/line/callback",
        )

    assert "LINE_CHANNEL_SECRET" in exc_info.value.message

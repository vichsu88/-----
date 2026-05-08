import pytest

from services.auth_service import build_line_authorize_url
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

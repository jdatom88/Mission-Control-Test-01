from datetime import UTC, datetime, timedelta

from mission_control.security.errors import AuthenticationRejectedError
from mission_control.security.http_adapter import SecurityHttpAdapter
from mission_control.security.models import (
    AuthorizationStart,
    CredentialVerification,
    GOOGLE_PROVIDER,
    OperatorSession,
    ProviderIdentity,
)


NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
REDIRECT_URI = "https://mission-control.example.test/auth/google/callback"
TOKEN = "synthetic-session-token"


class FakeProvider:
    name = GOOGLE_PROVIDER


class FakeBoundary:
    def __init__(self):
        self.callback = None
        self.authenticated = None
        self.verifications = 0

    def begin_authorization(self, provider):
        return AuthorizationStart(
            "https://accounts.example.test/oauth?state=one-time-state",
            NOW + timedelta(minutes=10),
        )

    def complete_authorization(self, provider, *, authorization_response, state):
        self.callback = (authorization_response, state)
        return OperatorSession(_identity(), TOKEN, NOW + timedelta(hours=12))

    def authenticate_session(self, token):
        self.authenticated = token
        if token != TOKEN:
            raise AuthenticationRejectedError("synthetic rejection with secret details")
        return _identity()

    def verify_persisted_authorization(self, provider):
        self.verifications += 1
        return CredentialVerification(
            provider=GOOGLE_PROVIDER,
            operator_subject=_identity().subject,
            operator_email=_identity().normalized_email,
            resource_context="google-calendar:primary:synthetic:timezone=UTC",
            scopes=frozenset({"openid", "email"}),
            verified_at=NOW,
        )


def _identity():
    return ProviderIdentity(
        GOOGLE_PROVIDER,
        "synthetic-google-subject",
        "operator@example.test",
        True,
    )


def _adapter(boundary=None):
    return SecurityHttpAdapter(boundary or FakeBoundary(), FakeProvider(), REDIRECT_URI)


def _headers(response):
    return dict(response.headers)


def test_start_redirects_to_provider_with_no_store_security_headers():
    response = _adapter()("GET", "/auth/google/start", {})

    assert response.status == 302
    assert _headers(response)["Location"].startswith("https://accounts.example.test/")
    assert _headers(response)["Cache-Control"] == "no-store"
    assert _headers(response)["Referrer-Policy"] == "no-referrer"
    assert response.body == b""


def test_callback_consumes_response_and_redirects_to_clean_result():
    boundary = FakeBoundary()
    adapter = _adapter(boundary)
    response = adapter(
        "GET",
        "/auth/google/callback?code=sensitive-code&state=one-time-state",
        {},
    )

    assert response.status == 303
    assert boundary.callback == (
        REDIRECT_URI + "?code=sensitive-code&state=one-time-state",
        "one-time-state",
    )
    assert _headers(response)["Location"] == "/auth/complete"
    cookie = _headers(response)["Set-Cookie"]
    assert TOKEN in cookie
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert b"sensitive-code" not in response.body
    assert "sensitive-code" not in repr(response.headers)


def test_callback_rejects_missing_or_duplicate_state_without_echoing_query():
    adapter = _adapter()
    for target in (
        "/auth/google/callback?code=sensitive-code",
        "/auth/google/callback?code=sensitive-code&state=one&state=two",
    ):
        response = adapter("GET", target, {})
        assert response.status == 400
        assert b"sensitive-code" not in response.body
        assert b"one" not in response.body


def test_verification_requires_session_and_returns_sanitized_receipt():
    boundary = FakeBoundary()
    adapter = _adapter(boundary)

    rejected = adapter("POST", "/auth/google/verify", {})
    assert rejected.status == 401
    assert boundary.verifications == 0

    verified = adapter(
        "POST",
        "/auth/google/verify",
        {"Cookie": f"other=value; mission_control_session={TOKEN}"},
    )
    assert verified.status == 200
    assert boundary.authenticated == TOKEN
    assert boundary.verifications == 1
    assert b'"status":"verified"' in verified.body
    assert b'"calendar_mutations":0' in verified.body
    assert b"synthetic-google-subject" not in verified.body
    assert TOKEN.encode() not in verified.body


def test_completion_page_has_no_third_party_resources_and_unknown_route_falls_through():
    adapter = _adapter()
    response = adapter("GET", "/auth/complete", {})
    assert response.status == 200
    assert b"<script" not in response.body
    assert b"<img" not in response.body
    assert b"http" not in response.body
    assert adapter("GET", "/unrelated", {}) is None

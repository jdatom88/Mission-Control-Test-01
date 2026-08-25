"""Minimal HTTP activation surface for the single-operator security boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Mapping
from urllib.parse import parse_qs, urlparse

from mission_control.core.http import HttpResponse
from mission_control.security.errors import (
    AuthenticationExpiredError,
    AuthenticationRejectedError,
    OAuthTransactionError,
    SecurityBoundaryError,
)
from mission_control.security.models import OAuthProvider
from mission_control.security.service import SingleOperatorSecurityBoundary


SESSION_COOKIE_NAME = "mission_control_session"
COMMON_HEADERS = (
    ("Cache-Control", "no-store"),
    (
        "Content-Security-Policy",
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    ),
    ("Referrer-Policy", "no-referrer"),
    ("X-Content-Type-Options", "nosniff"),
)


@dataclass(frozen=True)
class SecurityHttpAdapter:
    """Expose only OAuth start/callback and authenticated read-back."""

    boundary: SingleOperatorSecurityBoundary
    provider: OAuthProvider
    redirect_uri: str

    def __post_init__(self) -> None:
        parsed = urlparse(self.redirect_uri)
        if parsed.scheme != "https" or not parsed.netloc or not parsed.path:
            raise ValueError("Security callback requires an absolute HTTPS redirect URI.")

    @property
    def callback_path(self) -> str:
        return urlparse(self.redirect_uri).path

    def __call__(
        self,
        method: str,
        target: str,
        headers: Mapping[str, str],
    ) -> HttpResponse | None:
        parsed = urlparse(target)
        if method == "GET" and parsed.path == "/auth/google/start":
            return self._start()
        if method == "GET" and parsed.path == self.callback_path:
            return self._callback(parsed.query)
        if method == "GET" and parsed.path == "/auth/complete":
            return _html_response(
                200,
                "Authorization received. Run the authenticated verification step "
                "before treating the connection as usable.",
            )
        if method == "POST" and parsed.path == "/auth/google/verify":
            return self._verify(headers)
        return None

    def _start(self) -> HttpResponse:
        try:
            started = self.boundary.begin_authorization(self.provider)
        except SecurityBoundaryError:
            return _json_error(503, "authorization_start_unavailable")
        except Exception:
            return _json_error(500, "authorization_start_failed")
        return HttpResponse(
            302,
            headers=COMMON_HEADERS + (("Location", started.authorization_url),),
        )

    def _callback(self, query: str) -> HttpResponse:
        values = parse_qs(query, keep_blank_values=True)
        state_values = values.get("state", [])
        if len(state_values) != 1 or not state_values[0]:
            return _json_error(400, "authorization_callback_rejected")
        authorization_response = self.redirect_uri.split("?", 1)[0]
        if query:
            authorization_response += "?" + query
        try:
            session = self.boundary.complete_authorization(
                self.provider,
                authorization_response=authorization_response,
                state=state_values[0],
            )
        except (OAuthTransactionError, AuthenticationRejectedError):
            return _json_error(400, "authorization_callback_rejected")
        except SecurityBoundaryError:
            return _json_error(503, "authorization_callback_unavailable")
        except Exception:
            return _json_error(500, "authorization_callback_failed")
        return HttpResponse(
            303,
            headers=COMMON_HEADERS
            + (
                ("Location", "/auth/complete"),
                ("Set-Cookie", session.cookie_header(name=SESSION_COOKIE_NAME)),
            ),
        )

    def _verify(self, headers: Mapping[str, str]) -> HttpResponse:
        token = _session_token(headers.get("Cookie", ""))
        if token is None:
            return _json_error(401, "operator_authentication_required")
        try:
            operator = self.boundary.authenticate_session(token)
            verification = self.boundary.verify_persisted_authorization(self.provider)
        except (AuthenticationExpiredError, AuthenticationRejectedError):
            return _json_error(401, "operator_authentication_rejected")
        except SecurityBoundaryError:
            return _json_error(503, "provider_readback_failed")
        except Exception:
            return _json_error(500, "provider_readback_failed")
        subject_fingerprint = hashlib.sha256(operator.subject.encode("utf-8")).hexdigest()[:16]
        return _json_response(
            200,
            {
                "status": "verified",
                "provider": verification.provider,
                "operator_email": verification.operator_email,
                "operator_subject_fingerprint": subject_fingerprint,
                "resource_context": verification.resource_context,
                "scopes": sorted(verification.scopes),
                "verified_at": verification.verified_at.isoformat(),
                "calendar_mutations": 0,
            },
        )


def _session_token(cookie_header: str) -> str | None:
    try:
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        morsel = cookie.get(SESSION_COOKIE_NAME)
        return morsel.value if morsel and morsel.value else None
    except Exception:
        return None


def _json_error(status: int, code: str) -> HttpResponse:
    return _json_response(status, {"status": "error", "code": code})


def _json_response(status: int, payload: Mapping[str, object]) -> HttpResponse:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return HttpResponse(
        status,
        body,
        COMMON_HEADERS + (("Content-Type", "application/json"),),
    )


def _html_response(status: int, message: str) -> HttpResponse:
    body = (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Mission Control"
        "</title></head><body><main><h1>Mission Control</h1><p>"
        + message
        + "</p></main></body></html>"
    ).encode("utf-8")
    return HttpResponse(
        status,
        body,
        COMMON_HEADERS + (("Content-Type", "text/html; charset=utf-8"),),
    )

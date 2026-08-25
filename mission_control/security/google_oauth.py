"""Thin server-side Google OAuth and independent Calendar read-back adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from oauthlib.oauth2 import OAuth2Error

from mission_control.security.errors import (
    AuthenticationExpiredError,
    InsufficientScopeError,
    ProviderAuthorizationError,
    ProviderVerificationError,
)
from mission_control.security.models import (
    GOOGLE_PROVIDER,
    ProviderGrant,
    ProviderIdentity,
    ProviderReadback,
)


GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URI = "https://openidconnect.googleapis.com/v1/userinfo"


@dataclass(frozen=True)
class GoogleOAuthProvider:
    """Confidential web-server OAuth; no token is exposed to the browser."""

    client_id: str
    redirect_uri: str
    client_secret: str = field(repr=False)
    flow_factory: Callable[..., Flow] = field(
        default=Flow.from_client_config,
        repr=False,
        compare=False,
    )
    name: str = GOOGLE_PROVIDER

    def authorization_url(
        self,
        *,
        state: str,
        code_verifier: str,
        scopes: frozenset[str],
    ) -> str:
        try:
            flow = self._flow(scopes, state=state, code_verifier=code_verifier)
            url, returned_state = flow.authorization_url(
                access_type="offline",
                include_granted_scopes="true",
                prompt="consent",
            )
        except (OAuth2Error, ValueError) as exc:
            raise ProviderAuthorizationError(
                "Google authorization request could not be created."
            ) from exc
        if returned_state != state:
            raise ProviderAuthorizationError(
                "Google OAuth library returned unexpected authorization state."
            )
        return url

    def exchange_callback(
        self,
        *,
        authorization_response: str,
        state: str,
        code_verifier: str,
        scopes: frozenset[str],
    ) -> ProviderGrant:
        try:
            flow = self._flow(scopes, state=state, code_verifier=code_verifier)
            flow.fetch_token(authorization_response=authorization_response)
            credentials = flow.credentials
            if not credentials.refresh_token:
                raise ProviderAuthorizationError(
                    "Google did not return a refresh token; explicit re-consent is required."
                )
            readback = self._read_back_credentials(credentials, requested_scopes=scopes)
            return ProviderGrant(
                identity=readback.identity,
                scopes=readback.scopes,
                refresh_token=credentials.refresh_token,
            )
        except ProviderAuthorizationError:
            raise
        except (OAuth2Error, RefreshError, ValueError) as exc:
            raise ProviderAuthorizationError(
                "Google OAuth callback could not be exchanged safely."
            ) from exc

    def read_back(
        self,
        *,
        refresh_token: str,
        scopes: frozenset[str],
    ) -> ProviderReadback:
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=GOOGLE_TOKEN_URI,
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=sorted(scopes),
        )
        try:
            credentials.refresh(Request())
            return self._read_back_credentials(credentials, requested_scopes=scopes)
        except RefreshError as exc:
            raise AuthenticationExpiredError(
                "Google authorization is expired, revoked, or otherwise unusable."
            ) from exc

    def _flow(
        self,
        scopes: frozenset[str],
        *,
        state: str,
        code_verifier: str,
    ) -> Flow:
        return self.flow_factory(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": GOOGLE_AUTH_URI,
                    "token_uri": GOOGLE_TOKEN_URI,
                    "redirect_uris": [self.redirect_uri],
                }
            },
            scopes=sorted(scopes),
            state=state,
            redirect_uri=self.redirect_uri,
            code_verifier=code_verifier,
        )

    @staticmethod
    def _read_back_credentials(
        credentials: Credentials,
        *,
        requested_scopes: frozenset[str],
    ) -> ProviderReadback:
        try:
            userinfo_response = AuthorizedSession(credentials).get(
                GOOGLE_USERINFO_URI,
                timeout=15,
            )
            userinfo_response.raise_for_status()
            userinfo = userinfo_response.json()
            verified_value = userinfo.get("email_verified")
            email_verified = verified_value is True or verified_value == "true"
            identity = ProviderIdentity(
                provider=GOOGLE_PROVIDER,
                subject=str(userinfo["sub"]),
                email=str(userinfo["email"]),
                email_verified=email_verified,
            )
            calendar = (
                build("calendar", "v3", credentials=credentials, cache_discovery=False)
                .calendars()
                .get(calendarId="primary")
                .execute()
            )
            calendar_id = str(calendar["id"])
            calendar_timezone = str(calendar.get("timeZone", "unknown"))
            granted = frozenset(credentials.granted_scopes or requested_scopes)
            return ProviderReadback(
                identity=identity,
                scopes=granted,
                resource_context=(
                    f"google-calendar:primary:{calendar_id}:timezone={calendar_timezone}"
                ),
            )
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status == 401:
                raise AuthenticationExpiredError(
                    "Google rejected the refreshed authorization."
                ) from exc
            if status == 403:
                raise InsufficientScopeError(
                    "Google authorization cannot read the primary Calendar context."
                ) from exc
            raise ProviderVerificationError(
                "Google Calendar credential read-back failed."
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderVerificationError(
                "Google identity or Calendar read-back was malformed."
            ) from exc
        except Exception as exc:
            if isinstance(
                exc,
                (
                    AuthenticationExpiredError,
                    InsufficientScopeError,
                    ProviderVerificationError,
                ),
            ):
                raise
            raise ProviderVerificationError(
                "Google identity or Calendar read-back could not be verified."
            ) from exc

"""Provider-neutral records for the Generation 1 security boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


GOOGLE_PROVIDER = "google"
GOOGLE_IDENTITY_SCOPES = frozenset({"openid", "email"})
GOOGLE_CALENDAR_SCOPES = frozenset(
    {
        "https://www.googleapis.com/auth/calendar.events.owned",
        "https://www.googleapis.com/auth/calendar.calendars.readonly",
    }
)
GENERATION1_GOOGLE_SCOPES = GOOGLE_IDENTITY_SCOPES | GOOGLE_CALENDAR_SCOPES


@dataclass(frozen=True)
class ProviderIdentity:
    provider: str
    subject: str
    email: str
    email_verified: bool

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.subject.strip():
            raise ValueError("Provider identity requires provider and subject.")
        if not self.email.strip() or "@" not in self.email:
            raise ValueError("Provider identity requires a valid email address.")

    @property
    def normalized_email(self) -> str:
        return self.email.strip().casefold()


@dataclass(frozen=True)
class ProviderGrant:
    identity: ProviderIdentity
    scopes: frozenset[str]
    refresh_token: str = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scopes", frozenset(self.scopes))
        if not self.refresh_token:
            raise ValueError("Provider grant did not include a refresh token.")


@dataclass(frozen=True)
class StoredProviderCredential:
    identity: ProviderIdentity
    scopes: frozenset[str]
    refresh_token: str = field(repr=False)
    key_version: str
    stored_at: datetime
    last_verified_at: datetime | None


@dataclass(frozen=True)
class ProviderReadback:
    identity: ProviderIdentity
    scopes: frozenset[str]
    resource_context: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "scopes", frozenset(self.scopes))
        if not self.resource_context.strip():
            raise ValueError("Provider read-back requires resource context.")


@dataclass(frozen=True)
class AuthorizationStart:
    authorization_url: str
    expires_at: datetime


@dataclass(frozen=True)
class OperatorSession:
    operator: ProviderIdentity
    token: str = field(repr=False)
    expires_at: datetime

    def cookie_header(self, *, name: str = "mission_control_session") -> str:
        seconds = max(0, int((self.expires_at - datetime.now(self.expires_at.tzinfo)).total_seconds()))
        return (
            f"{name}={self.token}; Max-Age={seconds}; Path=/; "
            "Secure; HttpOnly; SameSite=Lax"
        )


@dataclass(frozen=True)
class CredentialVerification:
    provider: str
    operator_subject: str
    operator_email: str
    resource_context: str
    scopes: frozenset[str]
    verified_at: datetime


class OAuthProvider(Protocol):
    name: str

    def authorization_url(
        self,
        *,
        state: str,
        code_verifier: str,
        scopes: frozenset[str],
    ) -> str: ...

    def exchange_callback(
        self,
        *,
        authorization_response: str,
        state: str,
        code_verifier: str,
        scopes: frozenset[str],
    ) -> ProviderGrant: ...

    def read_back(
        self,
        *,
        refresh_token: str,
        scopes: frozenset[str],
    ) -> ProviderReadback: ...

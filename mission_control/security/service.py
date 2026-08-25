"""Single-operator authentication and provider-authorization orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from mission_control.security.config import SecurityBoundaryConfig
from mission_control.security.errors import (
    AuthenticationExpiredError,
    InsufficientScopeError,
    ProviderAuthorizationError,
    ProviderVerificationError,
    WrongOperatorError,
)
from mission_control.security.models import (
    AuthorizationStart,
    CredentialVerification,
    OAuthProvider,
    OperatorSession,
    ProviderIdentity,
)
from mission_control.security.storage import (
    SqliteCredentialVault,
    SqliteSecurityRuntimeStore,
)


@dataclass(frozen=True)
class SingleOperatorSecurityBoundary:
    """Mission Control-owned policy around replaceable provider and stores."""

    expected_operator_email: str
    required_scopes: frozenset[str]
    credential_vault: SqliteCredentialVault
    runtime_store: SqliteSecurityRuntimeStore

    def begin_authorization(
        self,
        provider: OAuthProvider,
        *,
        now: datetime | None = None,
    ) -> AuthorizationStart:
        transaction = self.runtime_store.begin_oauth(provider.name, now=now)
        try:
            url = provider.authorization_url(
                state=transaction.state,
                code_verifier=transaction.code_verifier,
                scopes=self.required_scopes,
            )
        except Exception as exc:
            self.runtime_store.audit(
                "oauth_begin", "failure", provider=provider.name, recorded_at=now
            )
            if isinstance(exc, ProviderAuthorizationError):
                raise
            raise ProviderAuthorizationError(
                "Provider authorization URL could not be created."
            ) from exc
        self.runtime_store.audit(
            "oauth_begin", "success", provider=provider.name, recorded_at=now
        )
        return AuthorizationStart(url, transaction.expires_at)

    def complete_authorization(
        self,
        provider: OAuthProvider,
        *,
        authorization_response: str,
        state: str,
        now: datetime | None = None,
    ) -> OperatorSession:
        timestamp = _utc(now)
        transaction = self.runtime_store.consume_oauth(
            provider.name,
            state,
            now=timestamp,
        )
        try:
            grant = provider.exchange_callback(
                authorization_response=authorization_response,
                state=state,
                code_verifier=transaction.code_verifier,
                scopes=self.required_scopes,
            )
            if grant.identity.provider != provider.name:
                raise ProviderAuthorizationError(
                    "Provider callback returned a foreign provider identity."
                )
            self._require_scopes(grant.scopes)
            operator = self.runtime_store.enroll_or_validate_operator(
                grant.identity,
                expected_email=self.expected_operator_email,
                now=timestamp,
            )
            self.credential_vault.save(grant, stored_at=timestamp)
            session = self.runtime_store.create_session(operator, now=timestamp)
        except Exception:
            self.runtime_store.audit(
                "oauth_complete",
                "rejected",
                provider=provider.name,
                recorded_at=timestamp,
            )
            raise
        self.runtime_store.audit(
            "oauth_complete",
            "success",
            provider=provider.name,
            operator_subject=operator.subject,
            recorded_at=timestamp,
        )
        return session

    def authenticate_session(
        self,
        session_token: str,
        *,
        now: datetime | None = None,
    ) -> ProviderIdentity:
        return self.runtime_store.authenticate_session(session_token, now=now)

    def logout(self, session_token: str, *, now: datetime | None = None) -> None:
        self.runtime_store.revoke_session(session_token, now=now)

    def verify_persisted_authorization(
        self,
        provider: OAuthProvider,
        *,
        now: datetime | None = None,
    ) -> CredentialVerification:
        timestamp = _utc(now)
        operator = self.runtime_store.load_operator()
        stored = self.credential_vault.load(provider.name)
        if (
            stored.identity.provider != operator.provider
            or stored.identity.subject != operator.subject
            or stored.identity.normalized_email != operator.normalized_email
        ):
            raise WrongOperatorError(
                "Persisted credential does not belong to the enrolled operator."
            )
        self._require_scopes(stored.scopes)
        try:
            readback = provider.read_back(
                refresh_token=stored.refresh_token,
                scopes=stored.scopes,
            )
        except Exception as exc:
            self.runtime_store.audit(
                "credential_readback",
                "failure",
                provider=provider.name,
                operator_subject=operator.subject,
                recorded_at=timestamp,
            )
            if isinstance(
                exc,
                (
                    AuthenticationExpiredError,
                    InsufficientScopeError,
                    ProviderAuthorizationError,
                    ProviderVerificationError,
                    WrongOperatorError,
                ),
            ):
                raise
            raise ProviderVerificationError(
                "Provider credential read-back failed."
            ) from exc
        if (
            readback.identity.provider != operator.provider
            or readback.identity.subject != operator.subject
            or readback.identity.normalized_email != operator.normalized_email
            or not readback.identity.email_verified
        ):
            raise WrongOperatorError(
                "Provider read-back returned a different operator account."
            )
        self._require_scopes(readback.scopes)
        self.credential_vault.mark_verified(
            provider.name,
            operator_subject=operator.subject,
            verified_at=timestamp,
        )
        self.runtime_store.audit(
            "credential_readback",
            "success",
            provider=provider.name,
            operator_subject=operator.subject,
            recorded_at=timestamp,
        )
        return CredentialVerification(
            provider=provider.name,
            operator_subject=operator.subject,
            operator_email=operator.normalized_email,
            resource_context=readback.resource_context,
            scopes=readback.scopes,
            verified_at=timestamp,
        )

    def _require_scopes(self, actual: frozenset[str]) -> None:
        missing = self.required_scopes - frozenset(actual)
        if missing:
            raise InsufficientScopeError(
                "Provider authorization lacks required scopes: "
                + ", ".join(sorted(missing))
            )


def bootstrap_security_boundary(
    config: SecurityBoundaryConfig,
) -> SingleOperatorSecurityBoundary:
    """Explicitly initialize both external security stores once."""

    config.validate()
    cipher = config.credential_cipher()
    vault = SqliteCredentialVault.bootstrap(
        config.storage.credential_database_path,
        cipher,
    )
    runtime = SqliteSecurityRuntimeStore.bootstrap(
        config.storage.runtime_database_path,
        cipher,
    )
    return SingleOperatorSecurityBoundary(
        expected_operator_email=config.expected_operator_email,
        required_scopes=config.required_google_scopes,
        credential_vault=vault,
        runtime_store=runtime,
    )


def open_security_boundary(
    config: SecurityBoundaryConfig,
) -> SingleOperatorSecurityBoundary:
    """Open expected stores without creating silent replacements."""

    config.validate()
    cipher = config.credential_cipher()
    return SingleOperatorSecurityBoundary(
        expected_operator_email=config.expected_operator_email,
        required_scopes=config.required_google_scopes,
        credential_vault=SqliteCredentialVault(
            config.storage.credential_database_path,
            cipher,
        ),
        runtime_store=SqliteSecurityRuntimeStore(
            config.storage.runtime_database_path,
            cipher,
        ),
    )


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Security timestamps must be timezone-aware.")
    return value.astimezone(UTC)

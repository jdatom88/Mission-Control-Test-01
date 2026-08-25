import base64
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from mission_control.security.config import (
    SecurityBoundaryConfig,
    SecurityStorageBoundary,
)
from mission_control.security.crypto import CredentialCipher, EncryptedValue
from mission_control.security.errors import (
    AuthenticationExpiredError,
    AuthenticationRejectedError,
    CredentialMissingError,
    CredentialUnreadableError,
    InsufficientScopeError,
    OAuthTransactionError,
    SecurityConfigurationError,
    SecurityStorageCompatibilityError,
    SecurityStorageUnavailableError,
    WrongOperatorError,
)
from mission_control.security.google_oauth import GoogleOAuthProvider
from mission_control.security.models import (
    GENERATION1_GOOGLE_SCOPES,
    GOOGLE_PROVIDER,
    ProviderGrant,
    ProviderIdentity,
    ProviderReadback,
)
from mission_control.security.service import (
    bootstrap_security_boundary,
    open_security_boundary,
)
from mission_control.security.storage import (
    SqliteCredentialVault,
    SqliteSecurityRuntimeStore,
)


NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
SYNTHETIC_REFRESH_TOKEN = "synthetic-refresh-token-never-use-live"


@dataclass
class SyntheticGoogleProvider:
    identity: ProviderIdentity
    scopes: frozenset[str] = GENERATION1_GOOGLE_SCOPES
    refresh_token: str = SYNTHETIC_REFRESH_TOKEN
    resource_context: str = "google-calendar:primary:synthetic:timezone=UTC"
    name: str = GOOGLE_PROVIDER

    def authorization_url(self, *, state, code_verifier, scopes):
        assert code_verifier
        assert scopes == GENERATION1_GOOGLE_SCOPES
        return f"https://accounts.example.test/oauth?state={state}"

    def exchange_callback(
        self,
        *,
        authorization_response,
        state,
        code_verifier,
        scopes,
    ):
        assert parse_qs(urlparse(authorization_response).query)["state"] == [state]
        assert code_verifier
        return ProviderGrant(self.identity, self.scopes, self.refresh_token)

    def read_back(self, *, refresh_token, scopes):
        assert refresh_token == self.refresh_token
        return ProviderReadback(self.identity, self.scopes, self.resource_context)


def _identity(*, subject="synthetic-google-subject", email="operator@example.test"):
    return ProviderIdentity(GOOGLE_PROVIDER, subject, email, True)


def _config(tmp_path, *, key=None):
    encoded_key = key or base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
    return SecurityBoundaryConfig(
        storage=SecurityStorageBoundary(
            repository_root=tmp_path / "repo",
            operator_knowledge_root=tmp_path / "operator-knowledge",
            credential_store_root=tmp_path / "credentials",
            runtime_state_root=tmp_path / "runtime-state",
        ),
        expected_operator_email="operator@example.test",
        google_oauth_client_id="synthetic-client-id",
        google_oauth_client_secret="synthetic-client-secret",
        google_oauth_redirect_uri="https://mission-control.example.test/auth/google/callback",
        encryption_key=encoded_key,
        encryption_key_version="test-v1",
    )


def _complete(boundary, provider, *, now=NOW):
    started = boundary.begin_authorization(provider, now=now)
    state = parse_qs(urlparse(started.authorization_url).query)["state"][0]
    callback = f"https://mission-control.example.test/auth/google/callback?code=fake&state={state}"
    return boundary.complete_authorization(
        provider,
        authorization_response=callback,
        state=state,
        now=now,
    )


def test_security_configuration_requires_separate_external_roots(tmp_path):
    config = _config(tmp_path)
    config.validate()

    nested = SecurityStorageBoundary(
        repository_root=tmp_path / "repo",
        operator_knowledge_root=tmp_path / "private",
        credential_store_root=tmp_path / "private" / "credentials",
        runtime_state_root=tmp_path / "runtime",
    )
    with pytest.raises(SecurityConfigurationError, match="distinct, non-nested"):
        nested.validate()


def test_environment_config_fails_loudly_without_secret_values(tmp_path):
    with pytest.raises(SecurityConfigurationError, match="GOOGLE_OAUTH_CLIENT_SECRET"):
        SecurityBoundaryConfig.from_environment(
            repository_root=tmp_path / "repo",
            environ={},
        )


def test_config_rejects_non_https_callback_and_bad_key(tmp_path):
    config = _config(tmp_path)
    insecure = SecurityBoundaryConfig(
        **{
            **config.__dict__,
            "google_oauth_redirect_uri": "http://example.test/callback",
        }
    )
    with pytest.raises(SecurityConfigurationError, match="absolute HTTPS"):
        insecure.validate()

    invalid_key = SecurityBoundaryConfig(
        **{
            **config.__dict__,
            "encryption_key": base64.urlsafe_b64encode(b"short").decode("ascii"),
        }
    )
    with pytest.raises(SecurityConfigurationError, match="exactly 32 bytes"):
        invalid_key.validate()


def test_secret_values_are_redacted_from_repr(tmp_path):
    config = _config(tmp_path)
    assert "synthetic-client-secret" not in repr(config)
    assert config.encryption_key not in repr(config)

    grant = ProviderGrant(_identity(), GENERATION1_GOOGLE_SCOPES, SYNTHETIC_REFRESH_TOKEN)
    assert SYNTHETIC_REFRESH_TOKEN not in repr(grant)


def test_aes_gcm_detects_tamper_wrong_key_and_context():
    cipher = CredentialCipher(b"a" * 32, key_version="v1")
    envelope = cipher.encrypt("secret", context="expected-context")
    assert cipher.decrypt(envelope, context="expected-context") == "secret"

    tampered_bytes = bytearray(base64.urlsafe_b64decode(envelope.ciphertext))
    tampered_bytes[0] ^= 1
    tampered = EncryptedValue(
        key_version=envelope.key_version,
        nonce=envelope.nonce,
        ciphertext=base64.urlsafe_b64encode(tampered_bytes).decode("ascii"),
    )
    with pytest.raises(CredentialUnreadableError):
        cipher.decrypt(tampered, context="expected-context")
    with pytest.raises(CredentialUnreadableError):
        cipher.decrypt(envelope, context="different-context")
    with pytest.raises(CredentialUnreadableError):
        CredentialCipher(b"b" * 32, key_version="v1").decrypt(
            envelope,
            context="expected-context",
        )


def test_bootstrap_is_explicit_and_open_never_creates_missing_stores(tmp_path):
    config = _config(tmp_path)
    with pytest.raises(SecurityStorageUnavailableError):
        open_security_boundary(config)
    assert not config.storage.credential_database_path.exists()
    assert not config.storage.runtime_database_path.exists()

    bootstrap_security_boundary(config)
    assert config.storage.credential_database_path.is_file()
    assert config.storage.runtime_database_path.is_file()
    assert config.storage.credential_database_path != config.storage.runtime_database_path

    with pytest.raises(SecurityStorageUnavailableError, match="already exists"):
        bootstrap_security_boundary(config)


def test_store_deleted_after_open_is_not_silently_recreated(tmp_path):
    config = _config(tmp_path)
    boundary = bootstrap_security_boundary(config)
    credential_path = config.storage.credential_database_path
    credential_path.unlink()

    with pytest.raises(SecurityStorageUnavailableError, match="no replacement"):
        boundary.credential_vault.load(GOOGLE_PROVIDER)
    assert not credential_path.exists()


def test_full_synthetic_oauth_session_encryption_and_restart_readback(tmp_path):
    config = _config(tmp_path)
    boundary = bootstrap_security_boundary(config)
    provider = SyntheticGoogleProvider(_identity())

    session = _complete(boundary, provider)
    assert boundary.authenticate_session(session.token, now=NOW) == _identity()
    cookie = session.cookie_header()
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie

    credential_bytes = config.storage.credential_database_path.read_bytes()
    runtime_bytes = config.storage.runtime_database_path.read_bytes()
    assert SYNTHETIC_REFRESH_TOKEN.encode() not in credential_bytes
    assert SYNTHETIC_REFRESH_TOKEN.encode() not in runtime_bytes
    assert session.token.encode() not in runtime_bytes

    restarted = open_security_boundary(config)
    assert restarted.authenticate_session(session.token, now=NOW) == _identity()
    verification = restarted.verify_persisted_authorization(provider, now=NOW)
    assert verification.operator_subject == _identity().subject
    assert verification.resource_context == provider.resource_context
    assert restarted.credential_vault.load(GOOGLE_PROVIDER).last_verified_at == NOW

    audit_text = config.storage.runtime_database_path.read_text(errors="ignore")
    assert SYNTHETIC_REFRESH_TOKEN not in audit_text
    assert session.token not in audit_text


def test_oauth_state_is_one_time_and_expiring(tmp_path):
    boundary = bootstrap_security_boundary(_config(tmp_path))
    provider = SyntheticGoogleProvider(_identity())
    started = boundary.begin_authorization(provider, now=NOW)
    state = parse_qs(urlparse(started.authorization_url).query)["state"][0]
    transaction = boundary.runtime_store.consume_oauth(provider.name, state, now=NOW)
    assert transaction.code_verifier

    with pytest.raises(OAuthTransactionError, match="already been consumed"):
        boundary.runtime_store.consume_oauth(provider.name, state, now=NOW)

    expired = boundary.runtime_store.begin_oauth(provider.name, now=NOW)
    with pytest.raises(OAuthTransactionError, match="expired"):
        boundary.runtime_store.consume_oauth(
            provider.name,
            expired.state,
            now=NOW + timedelta(minutes=11),
        )


def test_wrong_email_is_rejected_without_persisting_credential(tmp_path):
    boundary = bootstrap_security_boundary(_config(tmp_path))
    provider = SyntheticGoogleProvider(_identity(email="attacker@example.test"))
    with pytest.raises(WrongOperatorError, match="unexpected operator"):
        _complete(boundary, provider)
    with pytest.raises(CredentialMissingError):
        boundary.credential_vault.load(GOOGLE_PROVIDER)


def test_second_subject_cannot_replace_enrolled_operator(tmp_path):
    boundary = bootstrap_security_boundary(_config(tmp_path))
    _complete(boundary, SyntheticGoogleProvider(_identity(subject="first")))
    with pytest.raises(WrongOperatorError, match="different operator"):
        _complete(boundary, SyntheticGoogleProvider(_identity(subject="second")))
    assert boundary.runtime_store.load_operator().subject == "first"
    assert boundary.credential_vault.load(GOOGLE_PROVIDER).identity.subject == "first"


def test_missing_scope_is_rejected_before_credential_persistence(tmp_path):
    boundary = bootstrap_security_boundary(_config(tmp_path))
    provider = SyntheticGoogleProvider(
        _identity(),
        scopes=frozenset({"openid", "email"}),
    )
    with pytest.raises(InsufficientScopeError, match="lacks required scopes"):
        _complete(boundary, provider)
    with pytest.raises(CredentialMissingError):
        boundary.credential_vault.load(GOOGLE_PROVIDER)


def test_wrong_account_readback_fails_after_restart(tmp_path):
    config = _config(tmp_path)
    boundary = bootstrap_security_boundary(config)
    _complete(boundary, SyntheticGoogleProvider(_identity()))

    wrong_provider = SyntheticGoogleProvider(_identity(subject="foreign-subject"))
    with pytest.raises(WrongOperatorError, match="different operator"):
        open_security_boundary(config).verify_persisted_authorization(
            wrong_provider,
            now=NOW,
        )


def test_expired_provider_authorization_fails_loudly(tmp_path):
    class ExpiredProvider(SyntheticGoogleProvider):
        def read_back(self, *, refresh_token, scopes):
            raise AuthenticationExpiredError("synthetic token expired")

    config = _config(tmp_path)
    boundary = bootstrap_security_boundary(config)
    _complete(boundary, SyntheticGoogleProvider(_identity()))
    with pytest.raises(AuthenticationExpiredError, match="synthetic token expired"):
        open_security_boundary(config).verify_persisted_authorization(
            ExpiredProvider(_identity()),
            now=NOW,
        )


def test_session_expiry_and_revocation_fail_loudly(tmp_path):
    boundary = bootstrap_security_boundary(_config(tmp_path))
    session = _complete(boundary, SyntheticGoogleProvider(_identity()))
    with pytest.raises(AuthenticationExpiredError):
        boundary.authenticate_session(session.token, now=NOW + timedelta(hours=13))

    second = boundary.runtime_store.create_session(_identity(), now=NOW)
    boundary.logout(second.token, now=NOW)
    with pytest.raises(AuthenticationRejectedError, match="invalid or revoked"):
        boundary.authenticate_session(second.token, now=NOW)


def test_corrupt_ciphertext_and_wrong_key_version_fail_loudly(tmp_path):
    config = _config(tmp_path)
    boundary = bootstrap_security_boundary(config)
    _complete(boundary, SyntheticGoogleProvider(_identity()))

    with sqlite3.connect(config.storage.credential_database_path) as connection:
        row = connection.execute(
            "SELECT encrypted_refresh_token FROM provider_credentials"
        ).fetchone()[0]
        connection.execute(
            "UPDATE provider_credentials SET encrypted_refresh_token = ?",
            (row.replace('"ciphertext":"', '"ciphertext":"A', 1),),
        )
        connection.commit()
    with pytest.raises(CredentialUnreadableError):
        open_security_boundary(config).credential_vault.load(GOOGLE_PROVIDER)

    other_config = _config(
        tmp_path,
        key=base64.urlsafe_b64encode(b"z" * 32).decode("ascii"),
    )
    with pytest.raises(CredentialUnreadableError):
        open_security_boundary(other_config).credential_vault.load(GOOGLE_PROVIDER)


def test_foreign_store_role_is_rejected(tmp_path):
    config = _config(tmp_path)
    boundary = bootstrap_security_boundary(config)
    with pytest.raises(SecurityStorageCompatibilityError, match="role mismatch"):
        SqliteCredentialVault(
            config.storage.runtime_database_path,
            config.credential_cipher(),
        )
    boundary.runtime_store.load_operator


def test_google_adapter_preserves_state_pkce_redirect_and_offline_consent():
    captured = {}

    class FakeFlow:
        def authorization_url(self, **kwargs):
            captured["authorization_kwargs"] = kwargs
            return "https://accounts.google.test/authorize", "state-123"

    def factory(config, **kwargs):
        captured["config"] = config
        captured["flow_kwargs"] = kwargs
        return FakeFlow()

    provider = GoogleOAuthProvider(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://mission-control.example.test/auth/google/callback",
        flow_factory=factory,
    )
    url = provider.authorization_url(
        state="state-123",
        code_verifier="v" * 64,
        scopes=GENERATION1_GOOGLE_SCOPES,
    )
    assert url == "https://accounts.google.test/authorize"
    assert captured["flow_kwargs"]["state"] == "state-123"
    assert captured["flow_kwargs"]["code_verifier"] == "v" * 64
    assert captured["flow_kwargs"]["redirect_uri"].startswith("https://")
    assert captured["authorization_kwargs"] == {
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
    }
    assert "client-secret" not in repr(provider)


def test_google_adapter_exchanges_callback_on_server_with_persisted_pkce(monkeypatch):
    captured = {}

    class FakeCredentials:
        refresh_token = "server-returned-refresh-token"

    class FakeFlow:
        credentials = FakeCredentials()

        def fetch_token(self, **kwargs):
            captured["fetch_kwargs"] = kwargs

    def factory(config, **kwargs):
        captured["flow_kwargs"] = kwargs
        return FakeFlow()

    monkeypatch.setattr(
        GoogleOAuthProvider,
        "_read_back_credentials",
        staticmethod(
            lambda credentials, *, requested_scopes: ProviderReadback(
                _identity(),
                requested_scopes,
                "google-calendar:primary:synthetic:timezone=UTC",
            )
        ),
    )
    provider = GoogleOAuthProvider(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://mission-control.example.test/auth/google/callback",
        flow_factory=factory,
    )
    grant = provider.exchange_callback(
        authorization_response="https://mission-control.example.test/auth/google/callback?code=fake&state=state-123",
        state="state-123",
        code_verifier="v" * 64,
        scopes=GENERATION1_GOOGLE_SCOPES,
    )
    assert captured["flow_kwargs"]["state"] == "state-123"
    assert captured["flow_kwargs"]["code_verifier"] == "v" * 64
    assert captured["fetch_kwargs"]["authorization_response"].endswith(
        "code=fake&state=state-123"
    )
    assert grant.identity == _identity()
    assert grant.refresh_token == "server-returned-refresh-token"

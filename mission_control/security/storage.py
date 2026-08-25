"""Separate persistent stores for encrypted credentials and security runtime state."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mission_control.security.crypto import CredentialCipher, EncryptedValue
from mission_control.security.errors import (
    AuthenticationExpiredError,
    AuthenticationRejectedError,
    CredentialMissingError,
    OAuthTransactionError,
    SecurityStorageCompatibilityError,
    SecurityStorageCorruptionError,
    SecurityStorageError,
    SecurityStorageUnavailableError,
    WrongOperatorError,
)
from mission_control.security.models import (
    OperatorSession,
    ProviderGrant,
    ProviderIdentity,
    StoredProviderCredential,
)


SECURITY_STORE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class OAuthTransaction:
    provider: str
    state: str
    code_verifier: str
    expires_at: datetime


class SqliteCredentialVault:
    """Store only authenticated ciphertext plus non-secret credential metadata."""

    STORE_ROLE = "provider-credentials"

    def __init__(self, database_path: str | Path, cipher: CredentialCipher) -> None:
        self.database_path = Path(database_path)
        self._cipher = cipher
        _validate_existing_database(self.database_path, self.STORE_ROLE)

    @classmethod
    def bootstrap(
        cls,
        database_path: str | Path,
        cipher: CredentialCipher,
    ) -> "SqliteCredentialVault":
        path = Path(database_path)
        _bootstrap_database(path, cls.STORE_ROLE, _CREDENTIAL_SCHEMA)
        return cls(path, cipher)

    def save(self, grant: ProviderGrant, *, stored_at: datetime | None = None) -> None:
        timestamp = _utc(stored_at)
        scopes_json = json.dumps(sorted(grant.scopes), separators=(",", ":"))
        context = _credential_context(grant.identity.provider, grant.identity.subject)
        envelope = self._cipher.encrypt(grant.refresh_token, context=context)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO provider_credentials(
                        provider, operator_subject, operator_email, scopes_json,
                        encrypted_refresh_token, key_version, stored_at,
                        last_verified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                    ON CONFLICT(provider) DO UPDATE SET
                        operator_subject = excluded.operator_subject,
                        operator_email = excluded.operator_email,
                        scopes_json = excluded.scopes_json,
                        encrypted_refresh_token = excluded.encrypted_refresh_token,
                        key_version = excluded.key_version,
                        stored_at = excluded.stored_at,
                        last_verified_at = NULL
                    """,
                    (
                        grant.identity.provider,
                        grant.identity.subject,
                        grant.identity.normalized_email,
                        scopes_json,
                        envelope.to_json(),
                        envelope.key_version,
                        timestamp.isoformat(),
                    ),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise SecurityStorageError(
                "Encrypted provider credential could not be persisted."
            ) from exc

    def load(self, provider: str) -> StoredProviderCredential:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM provider_credentials WHERE provider = ?",
                    (provider,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise SecurityStorageCorruptionError(
                "Credential vault is unavailable or corrupt."
            ) from exc
        if row is None:
            raise CredentialMissingError(
                f"No persisted authorization exists for provider '{provider}'."
            )
        try:
            identity = ProviderIdentity(
                provider=row["provider"],
                subject=row["operator_subject"],
                email=row["operator_email"],
                email_verified=True,
            )
            scopes_payload = json.loads(row["scopes_json"])
            if not isinstance(scopes_payload, list) or not all(
                isinstance(scope, str) and scope for scope in scopes_payload
            ):
                raise ValueError
            envelope = EncryptedValue.from_json(row["encrypted_refresh_token"])
            if envelope.key_version != row["key_version"]:
                raise ValueError
            refresh_token = self._cipher.decrypt(
                envelope,
                context=_credential_context(identity.provider, identity.subject),
            )
            return StoredProviderCredential(
                identity=identity,
                scopes=frozenset(scopes_payload),
                refresh_token=refresh_token,
                key_version=row["key_version"],
                stored_at=_parse_datetime(row["stored_at"]),
                last_verified_at=(
                    _parse_datetime(row["last_verified_at"])
                    if row["last_verified_at"]
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SecurityStorageCorruptionError(
                "Persisted credential metadata is corrupt or incompatible."
            ) from exc

    def mark_verified(
        self,
        provider: str,
        *,
        operator_subject: str,
        verified_at: datetime | None = None,
    ) -> None:
        timestamp = _utc(verified_at)
        try:
            with self._connect() as connection:
                result = connection.execute(
                    """
                    UPDATE provider_credentials
                    SET last_verified_at = ?
                    WHERE provider = ? AND operator_subject = ?
                    """,
                    (timestamp.isoformat(), provider, operator_subject),
                )
                if result.rowcount != 1:
                    raise CredentialMissingError(
                        "Credential verification did not match persisted operator context."
                    )
                connection.commit()
        except CredentialMissingError:
            raise
        except sqlite3.Error as exc:
            raise SecurityStorageError(
                "Credential verification receipt could not be persisted."
            ) from exc

    def delete(self, provider: str) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM provider_credentials WHERE provider = ?",
                    (provider,),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise SecurityStorageError(
                "Persisted provider credential could not be deleted safely."
            ) from exc

    def validate_integrity(self) -> None:
        _validate_integrity(self.database_path, self.STORE_ROLE)
        try:
            with self._connect() as connection:
                providers = tuple(
                    row[0]
                    for row in connection.execute(
                        "SELECT provider FROM provider_credentials ORDER BY provider"
                    )
                )
            for provider in providers:
                self.load(provider)
        except SecurityStorageError:
            raise
        except sqlite3.Error as exc:
            raise SecurityStorageCorruptionError(
                "Credential vault integrity validation failed."
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        return _connect(self.database_path, self.STORE_ROLE)


class SqliteSecurityRuntimeStore:
    """Persist operator identity, one-time OAuth state, sessions, and safe audit."""

    STORE_ROLE = "security-runtime"

    def __init__(self, database_path: str | Path, cipher: CredentialCipher) -> None:
        self.database_path = Path(database_path)
        self._cipher = cipher
        _validate_existing_database(self.database_path, self.STORE_ROLE)

    @classmethod
    def bootstrap(
        cls,
        database_path: str | Path,
        cipher: CredentialCipher,
    ) -> "SqliteSecurityRuntimeStore":
        path = Path(database_path)
        _bootstrap_database(path, cls.STORE_ROLE, _RUNTIME_SCHEMA)
        return cls(path, cipher)

    def begin_oauth(
        self,
        provider: str,
        *,
        now: datetime | None = None,
        lifetime: timedelta = timedelta(minutes=10),
    ) -> OAuthTransaction:
        issued_at = _utc(now)
        if lifetime <= timedelta(0) or lifetime > timedelta(minutes=30):
            raise OAuthTransactionError(
                "OAuth transaction lifetime must be positive and no more than 30 minutes."
            )
        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        state_hash = _token_hash(state)
        expires_at = issued_at + lifetime
        encrypted_verifier = self._cipher.encrypt(
            code_verifier,
            context=_oauth_context(provider, state_hash),
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO oauth_transactions(
                        state_hash, provider, encrypted_code_verifier,
                        created_at, expires_at, consumed_at
                    ) VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        state_hash,
                        provider,
                        encrypted_verifier.to_json(),
                        issued_at.isoformat(),
                        expires_at.isoformat(),
                    ),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise SecurityStorageError(
                "OAuth transaction state could not be persisted."
            ) from exc
        return OAuthTransaction(provider, state, code_verifier, expires_at)

    def consume_oauth(
        self,
        provider: str,
        state: str,
        *,
        now: datetime | None = None,
    ) -> OAuthTransaction:
        consumed_at = _utc(now)
        state_hash = _token_hash(state)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM oauth_transactions WHERE state_hash = ? AND provider = ?",
                    (state_hash, provider),
                ).fetchone()
                if row is None:
                    raise OAuthTransactionError(
                        "OAuth state was not issued by this runtime."
                    )
                if row["consumed_at"] is not None:
                    raise OAuthTransactionError(
                        "OAuth state has already been consumed."
                    )
                expires_at = _parse_datetime(row["expires_at"])
                if consumed_at >= expires_at:
                    raise OAuthTransactionError("OAuth state has expired.")
                verifier = self._cipher.decrypt(
                    EncryptedValue.from_json(row["encrypted_code_verifier"]),
                    context=_oauth_context(provider, state_hash),
                )
                result = connection.execute(
                    """
                    UPDATE oauth_transactions SET consumed_at = ?
                    WHERE state_hash = ? AND provider = ? AND consumed_at IS NULL
                    """,
                    (consumed_at.isoformat(), state_hash, provider),
                )
                if result.rowcount != 1:
                    raise OAuthTransactionError(
                        "OAuth state changed while it was being consumed."
                    )
                connection.commit()
        except OAuthTransactionError:
            raise
        except sqlite3.Error as exc:
            raise SecurityStorageCorruptionError(
                "OAuth transaction state is unavailable or corrupt."
            ) from exc
        return OAuthTransaction(provider, state, verifier, expires_at)

    def enroll_or_validate_operator(
        self,
        identity: ProviderIdentity,
        *,
        expected_email: str,
        now: datetime | None = None,
    ) -> ProviderIdentity:
        timestamp = _utc(now)
        expected = expected_email.strip().casefold()
        if not identity.email_verified or identity.normalized_email != expected:
            raise WrongOperatorError(
                "Google returned an unverified or unexpected operator account."
            )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM enrolled_operator WHERE singleton_id = 1"
                ).fetchone()
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO enrolled_operator(
                            singleton_id, provider, operator_subject,
                            operator_email, enrolled_at
                        ) VALUES (1, ?, ?, ?, ?)
                        """,
                        (
                            identity.provider,
                            identity.subject,
                            identity.normalized_email,
                            timestamp.isoformat(),
                        ),
                    )
                    connection.commit()
                    return identity
                if (
                    row["provider"] != identity.provider
                    or row["operator_subject"] != identity.subject
                    or row["operator_email"] != identity.normalized_email
                ):
                    raise WrongOperatorError(
                        "Google authorization belongs to a different operator account."
                    )
                connection.commit()
                return ProviderIdentity(
                    provider=row["provider"],
                    subject=row["operator_subject"],
                    email=row["operator_email"],
                    email_verified=True,
                )
        except WrongOperatorError:
            raise
        except sqlite3.Error as exc:
            raise SecurityStorageCorruptionError(
                "Enrolled operator state is unavailable or corrupt."
            ) from exc

    def load_operator(self) -> ProviderIdentity:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM enrolled_operator WHERE singleton_id = 1"
                ).fetchone()
        except sqlite3.Error as exc:
            raise SecurityStorageCorruptionError(
                "Enrolled operator state is unavailable or corrupt."
            ) from exc
        if row is None:
            raise AuthenticationRejectedError(
                "No Mission Control operator has been enrolled."
            )
        try:
            return ProviderIdentity(
                provider=row["provider"],
                subject=row["operator_subject"],
                email=row["operator_email"],
                email_verified=True,
            )
        except (TypeError, ValueError) as exc:
            raise SecurityStorageCorruptionError(
                "Enrolled operator identity is corrupt."
            ) from exc

    def create_session(
        self,
        operator: ProviderIdentity,
        *,
        now: datetime | None = None,
        lifetime: timedelta = timedelta(hours=12),
    ) -> OperatorSession:
        created_at = _utc(now)
        if lifetime <= timedelta(0) or lifetime > timedelta(days=7):
            raise AuthenticationRejectedError(
                "Operator session lifetime must be positive and no more than seven days."
            )
        token = secrets.token_urlsafe(48)
        expires_at = created_at + lifetime
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO operator_sessions(
                        token_hash, operator_subject, operator_email,
                        created_at, expires_at, revoked_at
                    ) VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        _token_hash(token),
                        operator.subject,
                        operator.normalized_email,
                        created_at.isoformat(),
                        expires_at.isoformat(),
                    ),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise SecurityStorageError(
                "Operator session could not be persisted."
            ) from exc
        return OperatorSession(operator, token, expires_at)

    def authenticate_session(
        self,
        token: str,
        *,
        now: datetime | None = None,
    ) -> ProviderIdentity:
        checked_at = _utc(now)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM operator_sessions WHERE token_hash = ?",
                    (_token_hash(token),),
                ).fetchone()
        except sqlite3.Error as exc:
            raise SecurityStorageCorruptionError(
                "Operator session state is unavailable or corrupt."
            ) from exc
        if row is None or row["revoked_at"] is not None:
            raise AuthenticationRejectedError("Operator session is invalid or revoked.")
        if checked_at >= _parse_datetime(row["expires_at"]):
            raise AuthenticationExpiredError("Operator session has expired.")
        operator = self.load_operator()
        if (
            row["operator_subject"] != operator.subject
            or row["operator_email"] != operator.normalized_email
        ):
            raise WrongOperatorError(
                "Operator session does not match the enrolled operator."
            )
        return operator

    def revoke_session(self, token: str, *, now: datetime | None = None) -> None:
        timestamp = _utc(now)
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE operator_sessions SET revoked_at = ?
                    WHERE token_hash = ? AND revoked_at IS NULL
                    """,
                    (timestamp.isoformat(), _token_hash(token)),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise SecurityStorageError("Operator session could not be revoked.") from exc

    def audit(
        self,
        action: str,
        outcome: str,
        *,
        provider: str | None = None,
        operator_subject: str | None = None,
        recorded_at: datetime | None = None,
    ) -> None:
        if not action.strip() or outcome not in {"success", "rejected", "failure"}:
            raise SecurityStorageError("Security audit record is invalid.")
        timestamp = _utc(recorded_at)
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO security_audit(
                        action, outcome, provider, operator_subject, recorded_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        action,
                        outcome,
                        provider,
                        operator_subject,
                        timestamp.isoformat(),
                    ),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise SecurityStorageError(
                "Security audit record could not be persisted."
            ) from exc

    def audit_records(self) -> tuple[sqlite3.Row, ...]:
        try:
            with self._connect() as connection:
                return tuple(
                    connection.execute("SELECT * FROM security_audit ORDER BY audit_id")
                )
        except sqlite3.Error as exc:
            raise SecurityStorageCorruptionError(
                "Security audit state is unavailable or corrupt."
            ) from exc

    def validate_integrity(self) -> None:
        self.validate_database_integrity()
        self.load_operator()

    def validate_database_integrity(self) -> None:
        """Validate a bootstrapped runtime store before first enrollment."""

        _validate_integrity(self.database_path, self.STORE_ROLE)

    def _connect(self) -> sqlite3.Connection:
        return _connect(self.database_path, self.STORE_ROLE)


def _bootstrap_database(path: Path, role: str, schema: str) -> None:
    if path.exists() or path.is_symlink():
        raise SecurityStorageUnavailableError(
            f"Security {role} database already exists; bootstrap will not replace it."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(schema)
            connection.executemany(
                "INSERT INTO mc_security_metadata(key, value) VALUES (?, ?)",
                (
                    ("schema_version", str(SECURITY_STORE_SCHEMA_VERSION)),
                    ("store_role", role),
                ),
            )
            connection.commit()
    except sqlite3.Error as exc:
        path.unlink(missing_ok=True)
        raise SecurityStorageError(
            f"Security {role} database could not be initialized."
        ) from exc


def _validate_existing_database(path: Path, role: str) -> None:
    if path.is_symlink() or not path.exists() or not path.is_file():
        raise SecurityStorageUnavailableError(
            f"Expected security {role} database is unavailable; no replacement was created."
        )
    with _connect(path, role):
        pass


def _connect(path: Path, role: str) -> sqlite3.Connection:
    if path.is_symlink() or not path.exists() or not path.is_file():
        raise SecurityStorageUnavailableError(
            f"Expected security {role} database is unavailable; no replacement was created."
        )
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            path.resolve().as_uri() + "?mode=rw",
            timeout=5,
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        rows = dict(connection.execute("SELECT key, value FROM mc_security_metadata"))
        if rows.get("schema_version") != str(SECURITY_STORE_SCHEMA_VERSION):
            raise SecurityStorageCompatibilityError(
                f"Unsupported security store schema for {role}."
            )
        if rows.get("store_role") != role:
            raise SecurityStorageCompatibilityError(
                f"Security store role mismatch: expected {role}."
            )
        return connection
    except SecurityStorageError:
        if connection is not None:
            connection.close()
        raise
    except sqlite3.Error as exc:
        if connection is not None:
            connection.close()
        raise SecurityStorageCorruptionError(
            f"Security {role} database is corrupt or incompatible."
        ) from exc


def _validate_integrity(path: Path, role: str) -> None:
    try:
        with _connect(path, role) as connection:
            rows = tuple(row[0] for row in connection.execute("PRAGMA integrity_check"))
            if rows != ("ok",):
                raise SecurityStorageCorruptionError(
                    f"Security {role} database failed SQLite integrity validation."
                )
    except SecurityStorageError:
        raise
    except sqlite3.Error as exc:
        raise SecurityStorageCorruptionError(
            f"Security {role} database failed integrity validation."
        ) from exc


def _credential_context(provider: str, subject: str) -> str:
    return f"mission-control|credential|v1|{provider}|{subject}"


def _oauth_context(provider: str, state_hash: str) -> str:
    return f"mission-control|oauth-transaction|v1|{provider}|{state_hash}"


def _token_hash(token: str) -> str:
    if not token:
        raise AuthenticationRejectedError("Security token is missing.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Security timestamps must be timezone-aware.")
    return value.astimezone(UTC)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Persisted security timestamp is timezone-naive.")
    return parsed.astimezone(UTC)


_CREDENTIAL_SCHEMA = """
CREATE TABLE mc_security_metadata(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE provider_credentials(
    provider TEXT PRIMARY KEY,
    operator_subject TEXT NOT NULL,
    operator_email TEXT NOT NULL,
    scopes_json TEXT NOT NULL,
    encrypted_refresh_token TEXT NOT NULL,
    key_version TEXT NOT NULL,
    stored_at TEXT NOT NULL,
    last_verified_at TEXT
);
"""


_RUNTIME_SCHEMA = """
CREATE TABLE mc_security_metadata(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE enrolled_operator(
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    provider TEXT NOT NULL,
    operator_subject TEXT NOT NULL,
    operator_email TEXT NOT NULL,
    enrolled_at TEXT NOT NULL
);
CREATE TABLE oauth_transactions(
    state_hash TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    encrypted_code_verifier TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT
);
CREATE TABLE operator_sessions(
    token_hash TEXT PRIMARY KEY,
    operator_subject TEXT NOT NULL,
    operator_email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE TABLE security_audit(
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('success', 'rejected', 'failure')),
    provider TEXT,
    operator_subject TEXT,
    recorded_at TEXT NOT NULL
);
"""

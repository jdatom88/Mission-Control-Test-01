"""Explicit configuration and storage separation for Generation 1 security."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from mission_control.security.crypto import CredentialCipher
from mission_control.security.errors import SecurityConfigurationError
from mission_control.security.models import GENERATION1_GOOGLE_SCOPES


CREDENTIAL_DATABASE_NAME = "provider-credentials.sqlite3"
RUNTIME_DATABASE_NAME = "security-runtime.sqlite3"


@dataclass(frozen=True)
class SecurityStorageBoundary:
    repository_root: Path
    operator_knowledge_root: Path
    credential_store_root: Path
    runtime_state_root: Path

    def __post_init__(self) -> None:
        for name in (
            "repository_root",
            "operator_knowledge_root",
            "credential_store_root",
            "runtime_state_root",
        ):
            object.__setattr__(
                self,
                name,
                Path(getattr(self, name)).expanduser().resolve(strict=False),
            )

    def validate(self) -> None:
        repository = self.repository_root
        external = {
            "operator knowledge": self.operator_knowledge_root,
            "credential store": self.credential_store_root,
            "runtime/audit state": self.runtime_state_root,
        }
        for label, path in external.items():
            if path == repository or repository in path.parents:
                raise SecurityConfigurationError(
                    f"{label} must remain outside the product repository."
                )

        entries = tuple(external.items())
        for index, (left_label, left_path) in enumerate(entries):
            for right_label, right_path in entries[index + 1 :]:
                if (
                    left_path == right_path
                    or left_path in right_path.parents
                    or right_path in left_path.parents
                ):
                    raise SecurityConfigurationError(
                        f"{left_label} and {right_label} must use distinct, non-nested roots."
                    )

    @property
    def credential_database_path(self) -> Path:
        return self.credential_store_root / CREDENTIAL_DATABASE_NAME

    @property
    def runtime_database_path(self) -> Path:
        return self.runtime_state_root / RUNTIME_DATABASE_NAME


@dataclass(frozen=True)
class SecurityBoundaryConfig:
    storage: SecurityStorageBoundary
    expected_operator_email: str
    google_oauth_client_id: str
    google_oauth_redirect_uri: str
    encryption_key_version: str
    google_oauth_client_secret: str = field(repr=False)
    encryption_key: str = field(repr=False)
    required_google_scopes: frozenset[str] = GENERATION1_GOOGLE_SCOPES

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "required_google_scopes",
            frozenset(self.required_google_scopes),
        )

    def validate(self) -> None:
        self.storage.validate()
        if not self.expected_operator_email.strip() or "@" not in self.expected_operator_email:
            raise SecurityConfigurationError(
                "Expected operator email must be an explicit email address."
            )
        required_values = {
            "Google OAuth client ID": self.google_oauth_client_id,
            "Google OAuth client secret": self.google_oauth_client_secret,
            "Google OAuth redirect URI": self.google_oauth_redirect_uri,
            "credential encryption key": self.encryption_key,
            "credential encryption key version": self.encryption_key_version,
        }
        missing = tuple(label for label, value in required_values.items() if not value.strip())
        if missing:
            raise SecurityConfigurationError(
                "Security configuration is incomplete: " + ", ".join(missing)
            )
        parsed = urlparse(self.google_oauth_redirect_uri)
        if parsed.scheme != "https" or not parsed.netloc or parsed.fragment:
            raise SecurityConfigurationError(
                "Google OAuth redirect URI must be an absolute HTTPS URL without a fragment."
            )
        if not self.required_google_scopes:
            raise SecurityConfigurationError(
                "At least one explicit Google OAuth scope is required."
            )
        self.credential_cipher()

    def credential_cipher(self) -> CredentialCipher:
        return CredentialCipher.from_base64(
            self.encryption_key,
            key_version=self.encryption_key_version,
        )

    @classmethod
    def from_environment(
        cls,
        *,
        repository_root: str | Path,
        environ: Mapping[str, str] | None = None,
    ) -> "SecurityBoundaryConfig":
        values = os.environ if environ is None else environ
        names = (
            "MISSION_CONTROL_OPERATOR_KNOWLEDGE_ROOT",
            "MISSION_CONTROL_CREDENTIAL_STORE_ROOT",
            "MISSION_CONTROL_SECURITY_RUNTIME_ROOT",
            "MISSION_CONTROL_OPERATOR_GOOGLE_EMAIL",
            "GOOGLE_OAUTH_CLIENT_ID",
            "GOOGLE_OAUTH_CLIENT_SECRET",
            "GOOGLE_OAUTH_REDIRECT_URI",
            "MISSION_CONTROL_CREDENTIAL_ENCRYPTION_KEY",
            "MISSION_CONTROL_CREDENTIAL_KEY_VERSION",
        )
        missing = tuple(name for name in names if not values.get(name, "").strip())
        if missing:
            raise SecurityConfigurationError(
                "Security environment is incomplete: " + ", ".join(missing)
            )
        config = cls(
            storage=SecurityStorageBoundary(
                repository_root=Path(repository_root),
                operator_knowledge_root=Path(values[names[0]]),
                credential_store_root=Path(values[names[1]]),
                runtime_state_root=Path(values[names[2]]),
            ),
            expected_operator_email=values[names[3]].strip(),
            google_oauth_client_id=values[names[4]].strip(),
            google_oauth_client_secret=values[names[5]],
            google_oauth_redirect_uri=values[names[6]].strip(),
            encryption_key=values[names[7]],
            encryption_key_version=values[names[8]].strip(),
        )
        config.validate()
        return config

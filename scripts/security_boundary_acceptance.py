"""Separate-process synthetic acceptance for Issue #23 Phase A."""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlparse

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from mission_control.security.config import (
    SecurityBoundaryConfig,
    SecurityStorageBoundary,
)
from mission_control.security.errors import CredentialUnreadableError, WrongOperatorError
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


SYNTHETIC_EMAIL = "operator@example.test"
SYNTHETIC_SUBJECT = "synthetic-google-operator"
SYNTHETIC_REFRESH_TOKEN = "synthetic-issue23-refresh-token"
FIXED_NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


@dataclass
class SyntheticProvider:
    identity: ProviderIdentity
    name: str = GOOGLE_PROVIDER

    def authorization_url(self, *, state, code_verifier, scopes):
        assert code_verifier
        assert scopes == GENERATION1_GOOGLE_SCOPES
        return f"https://accounts.example.test/authorize?state={state}"

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
        return ProviderGrant(
            identity=self.identity,
            scopes=scopes,
            refresh_token=SYNTHETIC_REFRESH_TOKEN,
        )

    def read_back(self, *, refresh_token, scopes):
        assert refresh_token == SYNTHETIC_REFRESH_TOKEN
        return ProviderReadback(
            identity=self.identity,
            scopes=scopes,
            resource_context="google-calendar:primary:synthetic:timezone=UTC",
        )


def _identity(*, subject: str = SYNTHETIC_SUBJECT) -> ProviderIdentity:
    return ProviderIdentity(GOOGLE_PROVIDER, subject, SYNTHETIC_EMAIL, True)


def _config(*, key: str | None = None) -> SecurityBoundaryConfig:
    root = Path(os.environ["MC_SECURITY_ACCEPTANCE_ROOT"])
    return SecurityBoundaryConfig(
        storage=SecurityStorageBoundary(
            repository_root=root / "repository-boundary",
            operator_knowledge_root=root / "operator-knowledge",
            credential_store_root=root / "credentials",
            runtime_state_root=root / "runtime-state",
        ),
        expected_operator_email=SYNTHETIC_EMAIL,
        google_oauth_client_id="synthetic-client-id",
        google_oauth_client_secret="synthetic-client-secret",
        google_oauth_redirect_uri="https://mission-control.example.test/auth/google/callback",
        encryption_key=key or os.environ["MC_SECURITY_ACCEPTANCE_KEY"],
        encryption_key_version="acceptance-v1",
    )


def _seed() -> None:
    boundary = bootstrap_security_boundary(_config())
    provider = SyntheticProvider(_identity())
    started = boundary.begin_authorization(provider, now=FIXED_NOW)
    state = parse_qs(urlparse(started.authorization_url).query)["state"][0]
    session = boundary.complete_authorization(
        provider,
        authorization_response=(
            "https://mission-control.example.test/auth/google/callback"
            f"?code=synthetic&state={state}"
        ),
        state=state,
        now=FIXED_NOW,
    )
    Path(os.environ["MC_SECURITY_ACCEPTANCE_SESSION"]).write_text(session.token)


def _restart_readback() -> None:
    boundary = open_security_boundary(_config())
    token = Path(os.environ["MC_SECURITY_ACCEPTANCE_SESSION"]).read_text()
    operator = boundary.authenticate_session(token, now=FIXED_NOW)
    assert operator == _identity()
    verification = boundary.verify_persisted_authorization(
        SyntheticProvider(_identity()),
        now=FIXED_NOW,
    )
    assert verification.operator_subject == SYNTHETIC_SUBJECT
    assert verification.resource_context.startswith("google-calendar:primary:synthetic")


def _negative_checks() -> None:
    boundary = open_security_boundary(_config())
    try:
        boundary.verify_persisted_authorization(
            SyntheticProvider(_identity(subject="wrong-google-subject")),
            now=FIXED_NOW,
        )
    except WrongOperatorError:
        pass
    else:
        raise AssertionError("Wrong-account read-back was not rejected.")

    wrong_key = base64.urlsafe_b64encode(b"z" * 32).decode("ascii")
    wrong_key_boundary = open_security_boundary(_config(key=wrong_key))
    try:
        wrong_key_boundary.credential_vault.load(GOOGLE_PROVIDER)
    except CredentialUnreadableError:
        pass
    else:
        raise AssertionError("Unreadable credential was not rejected.")


def _run_stage(stage: str, environment: dict[str, str]) -> None:
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), stage],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> None:
    with TemporaryDirectory(prefix="mission-control-security-") as directory:
        root = Path(directory)
        environment = os.environ.copy()
        environment["MC_SECURITY_ACCEPTANCE_ROOT"] = str(root)
        environment["MC_SECURITY_ACCEPTANCE_KEY"] = base64.urlsafe_b64encode(
            b"k" * 32
        ).decode("ascii")
        environment["MC_SECURITY_ACCEPTANCE_SESSION"] = str(root / "session-token")

        _run_stage("seed", environment)
        _run_stage("restart-readback", environment)
        _run_stage("negative-checks", environment)

        session_token = Path(environment["MC_SECURITY_ACCEPTANCE_SESSION"]).read_text()
        credential_bytes = (root / "credentials/provider-credentials.sqlite3").read_bytes()
        runtime_bytes = (root / "runtime-state/security-runtime.sqlite3").read_bytes()
        assert SYNTHETIC_REFRESH_TOKEN.encode() not in credential_bytes
        assert SYNTHETIC_REFRESH_TOKEN.encode() not in runtime_bytes
        assert session_token.encode() not in runtime_bytes

    print("GEN1_SECURITY_PHASE_A_ACCEPTANCE=PASS")
    print("SEPARATE_PROCESS_RESTART=VERIFIED")
    print("ENCRYPTED_REFRESH_TOKEN=VERIFIED")
    print("OPERATOR_AND_PROVIDER_READBACK=VERIFIED")
    print("WRONG_ACCOUNT_AND_WRONG_KEY=FAIL_LOUD")
    print("REAL_OPERATOR_DATA=0")
    print("LIVE_GOOGLE_CALLS=0")
    print("EXTERNAL_ACTIONS=0")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        main()
    elif sys.argv[1] == "seed":
        _seed()
    elif sys.argv[1] == "restart-readback":
        _restart_readback()
    elif sys.argv[1] == "negative-checks":
        _negative_checks()
    else:
        raise SystemExit(f"Unknown acceptance stage: {sys.argv[1]}")

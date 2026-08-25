import base64
import json
import os
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY_ROOT / "scripts/gen1_security_boundary.py"


def test_explicit_bootstrap_then_no_create_check(tmp_path):
    environment = os.environ.copy()
    environment.update(
        {
            "MISSION_CONTROL_OPERATOR_KNOWLEDGE_ROOT": str(tmp_path / "knowledge"),
            "MISSION_CONTROL_CREDENTIAL_STORE_ROOT": str(tmp_path / "credentials"),
            "MISSION_CONTROL_SECURITY_RUNTIME_ROOT": str(tmp_path / "runtime"),
            "MISSION_CONTROL_OPERATOR_GOOGLE_EMAIL": "operator@example.test",
            "GOOGLE_OAUTH_CLIENT_ID": "synthetic-client-id",
            "GOOGLE_OAUTH_CLIENT_SECRET": "synthetic-client-secret",
            "GOOGLE_OAUTH_REDIRECT_URI": (
                "https://mission-control.example.test/auth/google/callback"
            ),
            "MISSION_CONTROL_CREDENTIAL_ENCRYPTION_KEY": base64.urlsafe_b64encode(
                b"k" * 32
            ).decode("ascii"),
            "MISSION_CONTROL_CREDENTIAL_KEY_VERSION": "test-v1",
        }
    )

    bootstrapped = _run("bootstrap", environment)
    assert bootstrapped.returncode == 0
    receipt = json.loads(bootstrapped.stdout)
    assert receipt == {
        "operation": "bootstrap",
        "operator_enrolled": False,
        "status": "verified",
        "stores": ["provider-credentials", "security-runtime"],
    }

    checked = _run("check", environment)
    assert checked.returncode == 0
    assert json.loads(checked.stdout)["status"] == "verified"

    duplicate = _run("bootstrap", environment)
    assert duplicate.returncode == 2
    assert "already exists" in duplicate.stderr
    assert "synthetic-client-secret" not in duplicate.stderr
    assert (
        environment["MISSION_CONTROL_CREDENTIAL_ENCRYPTION_KEY"]
        not in duplicate.stderr
    )


def _run(operation, environment):
    return subprocess.run(
        [sys.executable, str(SCRIPT), operation],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

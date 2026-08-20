import pytest

from mission_control.runtime.calendar_storage import (
    RuntimeStorageConfigurationError,
)
from mission_control.runtime.pilot_guardian import PilotGuardianConfig


def test_guardian_defaults_to_daily_backup_and_minute_checks():
    config = PilotGuardianConfig.from_environment({})

    assert config.port == 8080
    assert config.storage_check_seconds == 60
    assert config.backup_interval_seconds == 86_400
    assert config.backup_on_start is False


def test_guardian_reads_explicit_runtime_values():
    config = PilotGuardianConfig.from_environment(
        {
            "PORT": "9000",
            "MISSION_CONTROL_STORAGE_CHECK_SECONDS": "15",
            "MISSION_CONTROL_BACKUP_INTERVAL_SECONDS": "3600",
            "MISSION_CONTROL_BACKUP_ON_START": "true",
        }
    )

    assert config == PilotGuardianConfig(9000, 15, 3600, True)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MISSION_CONTROL_STORAGE_CHECK_SECONDS", "4"),
        ("MISSION_CONTROL_BACKUP_INTERVAL_SECONDS", "299"),
        ("MISSION_CONTROL_BACKUP_ON_START", "yes"),
    ],
)
def test_guardian_rejects_unsafe_schedule_values(name, value):
    with pytest.raises(RuntimeStorageConfigurationError):
        PilotGuardianConfig.from_environment({name: value})

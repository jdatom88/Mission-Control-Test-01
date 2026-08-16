"""Canonical connector states for Mission Control OS."""

from enum import Enum


class ConnectorState(str, Enum):
    HEALTHY_DATA_FOUND = "connected_authorized_data_found"
    HEALTHY_NO_MATCHING_DATA = "connected_authorized_no_matching_data"
    INSUFFICIENT_SCOPE = "connected_insufficient_scope"
    WRONG_ACCOUNT = "connected_wrong_account"
    AUTH_EXPIRED = "authentication_expired"
    RUNTIME_CAPABILITY_UNAVAILABLE = "runtime_capability_unavailable"
    CONNECTOR_UNAVAILABLE = "connector_unavailable"
    EXECUTION_FAILURE = "execution_failure"
    VERIFICATION_FAILURE = "verification_failure"
    UNKNOWN = "unknown"


def user_message(state: ConnectorState) -> str:
    messages = {
        ConnectorState.HEALTHY_DATA_FOUND: "Connected and working.",
        ConnectorState.HEALTHY_NO_MATCHING_DATA: "Connected and working; no matching data was found.",
        ConnectorState.INSUFFICIENT_SCOPE: "Connected, but this resource is not authorized.",
        ConnectorState.WRONG_ACCOUNT: "Connected, but authenticated to the wrong account.",
        ConnectorState.AUTH_EXPIRED: "Authentication has expired and must be renewed.",
        ConnectorState.RUNTIME_CAPABILITY_UNAVAILABLE: (
            "This execution runtime cannot invoke the connector capability, but the connector itself may still be healthy."
        ),
        ConnectorState.CONNECTOR_UNAVAILABLE: "The external connector or provider is currently unavailable.",
        ConnectorState.EXECUTION_FAILURE: "The connector was reached, but the requested operation failed.",
        ConnectorState.VERIFICATION_FAILURE: "The operation ran, but its result could not be verified.",
        ConnectorState.UNKNOWN: "Connector state could not be determined.",
    }
    return messages[state]

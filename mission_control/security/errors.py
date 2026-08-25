"""Fail-loud errors for the Generation 1 single-operator boundary."""


class SecurityBoundaryError(RuntimeError):
    """The security boundary could not establish a trusted result."""


class SecurityConfigurationError(SecurityBoundaryError):
    """Required security configuration is absent, invalid, or unsafe."""


class SecurityStorageError(SecurityBoundaryError):
    """Security state could not be stored or read safely."""


class SecurityStorageUnavailableError(SecurityStorageError):
    """An expected security store is absent or inaccessible."""


class SecurityStorageCompatibilityError(SecurityStorageError):
    """A security store uses an unsupported or foreign layout."""


class SecurityStorageCorruptionError(SecurityStorageError):
    """Security state exists but is corrupt or internally inconsistent."""


class CredentialMissingError(SecurityBoundaryError):
    """No persisted credential exists for the requested provider."""


class CredentialUnreadableError(SecurityBoundaryError):
    """Encrypted credential material cannot be authenticated or decrypted."""


class AuthenticationExpiredError(SecurityBoundaryError):
    """A session or provider authorization has expired."""


class AuthenticationRejectedError(SecurityBoundaryError):
    """Operator authentication was not accepted."""


class WrongOperatorError(AuthenticationRejectedError):
    """The provider identity is not the enrolled Mission Control operator."""


class InsufficientScopeError(SecurityBoundaryError):
    """The provider authorization lacks a required permission."""


class OAuthTransactionError(AuthenticationRejectedError):
    """The OAuth transaction is missing, expired, consumed, or invalid."""


class ProviderAuthorizationError(SecurityBoundaryError):
    """The provider did not return a usable authorization."""


class ProviderVerificationError(SecurityBoundaryError):
    """Independent provider read-back did not establish trusted context."""

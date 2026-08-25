"""Authenticated encryption for provider credential material."""

from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mission_control.security.errors import (
    CredentialUnreadableError,
    SecurityConfigurationError,
)


@dataclass(frozen=True)
class EncryptedValue:
    key_version: str
    nonce: str
    ciphertext: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "cipher": "AES-256-GCM",
                "key_version": self.key_version,
                "nonce": self.nonce,
                "ciphertext": self.ciphertext,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, value: str) -> "EncryptedValue":
        try:
            payload = json.loads(value)
            if set(payload) != {"cipher", "key_version", "nonce", "ciphertext"}:
                raise ValueError
            if payload["cipher"] != "AES-256-GCM":
                raise ValueError
            return cls(
                key_version=str(payload["key_version"]),
                nonce=str(payload["nonce"]),
                ciphertext=str(payload["ciphertext"]),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CredentialUnreadableError(
                "Encrypted credential envelope is malformed or unsupported."
            ) from exc


class CredentialCipher:
    """Small AES-256-GCM envelope with versioned key identity."""

    def __init__(self, key: bytes, *, key_version: str) -> None:
        if len(key) != 32:
            raise SecurityConfigurationError(
                "Credential encryption key must decode to exactly 32 bytes."
            )
        if not key_version.strip():
            raise SecurityConfigurationError(
                "Credential encryption key version must be explicit."
            )
        self._cipher = AESGCM(key)
        self.key_version = key_version.strip()

    @classmethod
    def from_base64(cls, value: str, *, key_version: str) -> "CredentialCipher":
        try:
            padded = value.strip() + "=" * (-len(value.strip()) % 4)
            key = base64.urlsafe_b64decode(padded.encode("ascii"))
        except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
            raise SecurityConfigurationError(
                "Credential encryption key must be URL-safe base64."
            ) from exc
        return cls(key, key_version=key_version)

    @staticmethod
    def generate_key() -> str:
        return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode(
            "ascii"
        )

    def encrypt(self, plaintext: str, *, context: str) -> EncryptedValue:
        if not plaintext or not context:
            raise SecurityConfigurationError(
                "Credential encryption requires non-empty plaintext and context."
            )
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(
            nonce,
            plaintext.encode("utf-8"),
            context.encode("utf-8"),
        )
        return EncryptedValue(
            key_version=self.key_version,
            nonce=_encode(nonce),
            ciphertext=_encode(ciphertext),
        )

    def decrypt(self, envelope: EncryptedValue, *, context: str) -> str:
        if envelope.key_version != self.key_version:
            raise CredentialUnreadableError(
                "Encrypted credential requires an unavailable key version."
            )
        try:
            plaintext = self._cipher.decrypt(
                _decode(envelope.nonce),
                _decode(envelope.ciphertext),
                context.encode("utf-8"),
            )
            return plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError, ValueError, binascii.Error) as exc:
            raise CredentialUnreadableError(
                "Encrypted credential authentication failed; reauthorization is required."
            ) from exc


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)

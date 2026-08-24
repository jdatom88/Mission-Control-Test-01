"""Enforce the Generation 1 code, knowledge, credential, and state boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class CredentialSource(str, Enum):
    SEALED_ENVIRONMENT = "sealed_environment"
    ENCRYPTED_RUNTIME_STORE = "encrypted_runtime_store"


class KnowledgeBoundaryError(ValueError):
    pass


@dataclass(frozen=True)
class KnowledgeStorageBoundary:
    repository_root: Path
    operator_knowledge_root: Path
    runtime_state_root: Path
    credential_source: CredentialSource

    def validate(self) -> None:
        repository = self.repository_root.resolve()
        knowledge = self.operator_knowledge_root.resolve()
        runtime = self.runtime_state_root.resolve()

        if knowledge == runtime or knowledge in runtime.parents or runtime in knowledge.parents:
            raise KnowledgeBoundaryError(
                "Operator knowledge and runtime state must use distinct, non-nested roots"
            )
        for label, path in (
            ("operator knowledge", knowledge),
            ("runtime state", runtime),
        ):
            if path == repository or repository in path.parents:
                raise KnowledgeBoundaryError(
                    f"{label} root must remain outside the product repository"
                )

        if not isinstance(self.credential_source, CredentialSource):
            raise KnowledgeBoundaryError(
                "Credentials must come from a sealed environment or encrypted runtime store"
            )

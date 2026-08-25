"""Small provider-neutral HTTP contracts for replaceable runtime routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes = b""
    headers: tuple[tuple[str, str], ...] = ()


class HttpRouteHandler(Protocol):
    def __call__(
        self,
        method: str,
        target: str,
        headers: Mapping[str, str],
    ) -> HttpResponse | None: ...

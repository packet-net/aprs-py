"""Exceptions the library raises."""

from __future__ import annotations

from collections.abc import Iterable

from .diagnostics import Diagnostic

__all__ = ["AprsError", "EncodeError", "HeaderError"]


class AprsError(ValueError):
    """Base class of this library's exceptions."""


class HeaderError(AprsError):
    """The packet's header is unusable, so nothing in it could be decoded.

    ``diagnostics`` says why: an ``error`` for the defect that stopped decoding, and any
    warnings noticed before it.
    """

    def __init__(self, message: str, diagnostics: Iterable[Diagnostic]) -> None:
        super().__init__(message)
        self.diagnostics: tuple[Diagnostic, ...] = tuple(diagnostics)


class EncodeError(AprsError):
    """The data cannot be written as APRS without breaking the specification."""

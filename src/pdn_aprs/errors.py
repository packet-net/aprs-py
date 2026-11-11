"""Exceptions the library raises."""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from .diagnostics import Diagnostic

__all__ = ["AprsError", "EncodeError", "HeaderError", "RefusalCode"]


class RefusalCode(str, Enum):
    """Why an encoder or builder refused: one code per rule a program could act on differently.

    The value is the shared kebab-case id the conformance vectors list under ``refusals``. New
    codes may be added in later 1.x releases, so allow for one you do not know.
    ``DOES_NOT_READ_BACK`` is the fallback: the library's own read-back check failed and no rule
    names why.
    """

    INVALID_ADDRESS = "invalid-address"
    AX25_CANNOT_CARRY = "ax25-cannot-carry"
    TNC2_CANNOT_CARRY = "tnc2-cannot-carry"
    INVALID_THIRD_PARTY_HEADER = "invalid-third-party-header"
    INVALID_ADDRESSEE = "invalid-addressee"
    INVALID_NAME = "invalid-name"
    INVALID_MESSAGE_ID = "invalid-message-id"
    PADDING_SPACE = "padding-space"
    TOO_LONG = "too-long"
    MALFORMED = "malformed"
    INVALID_CHARACTER = "invalid-character"
    TEXT_READS_AS_FIELD = "text-reads-as-field"
    NOT_A_NUMBER = "not-a-number"
    VALUE_OUT_OF_RANGE = "value-out-of-range"
    VALUE_HAS_NO_FORM = "value-has-no-form"
    VALUE_GIVEN_TWICE = "value-given-twice"
    INVALID_TIMESTAMP = "invalid-timestamp"
    MISSING_FIELD = "missing-field"
    INVALID_SYMBOL = "invalid-symbol"
    SYMBOL_MISMATCH = "symbol-mismatch"
    EXTENSION_CONFLICT = "extension-conflict"
    FIELD_NOT_ALLOWED = "field-not-allowed"
    INVALID_CODE = "invalid-code"
    INVALID_NMEA = "invalid-nmea"
    NOT_ENCODABLE = "not-encodable"
    DOES_NOT_READ_BACK = "does-not-read-back"


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
    """The data cannot be written as APRS without breaking the specification.

    ``code`` says why, as a :class:`RefusalCode`; the message text is for people and may change.
    """

    def __init__(self, message: str, code: RefusalCode = RefusalCode.DOES_NOT_READ_BACK) -> None:
        super().__init__(message)
        self.code: RefusalCode = code

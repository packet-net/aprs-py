"""Parse options: which tolerable defects a decoder accepts."""

from __future__ import annotations

from dataclasses import dataclass, field

from .diagnostics import DiagnosticCode

__all__ = ["ParseOptions"]

_ALL_TOLERABLE: frozenset[DiagnosticCode] = frozenset(c for c in DiagnosticCode if c.tolerable)


@dataclass(frozen=True, slots=True)
class ParseOptions:
    """Which tolerable defects to accept.

    A lenient decoder (the default) accepts every tolerable defect with a warning; a strict one
    accepts none. In between, each tolerance can be turned on or off on its own:

    >>> from packet_aprs import DiagnosticCode, ParseOptions
    >>> options = ParseOptions.lenient().without(DiagnosticCode.UNPADDED_ADDRESSEE)
    >>> options.tolerates(DiagnosticCode.UNPADDED_ADDRESSEE)
    False
    >>> options.tolerates(DiagnosticCode.NON_UTF8_TEXT)
    True
    """

    tolerated: frozenset[DiagnosticCode] = field(default=_ALL_TOLERABLE)

    def __post_init__(self) -> None:
        wrong = sorted(c.value for c in self.tolerated if not c.tolerable)
        if wrong:
            raise ValueError(f"not tolerable codes: {', '.join(wrong)}")

    @classmethod
    def lenient(cls) -> ParseOptions:
        """Accept every tolerable defect, with a warning for each."""
        return cls(_ALL_TOLERABLE)

    @classmethod
    def strict(cls) -> ParseOptions:
        """Accept no defect: a tolerable one rejects the packet as an error."""
        return cls(frozenset())

    def tolerates(self, code: DiagnosticCode) -> bool:
        """Whether this defect is accepted."""
        return code in self.tolerated

    def tolerating(self, *codes: DiagnosticCode) -> ParseOptions:
        """These options, also accepting the given defects."""
        return ParseOptions(self.tolerated | frozenset(codes))

    def without(self, *codes: DiagnosticCode) -> ParseOptions:
        """These options, no longer accepting the given defects."""
        return ParseOptions(self.tolerated - frozenset(codes))

    @property
    def is_strict(self) -> bool:
        """True when no defect is tolerated."""
        return not self.tolerated


LENIENT = ParseOptions.lenient()
STRICT = ParseOptions.strict()

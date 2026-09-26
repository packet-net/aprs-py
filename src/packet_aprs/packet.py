"""A decoded packet: its header, its raw information field, the data decoded from it, and the
diagnostics the decoder raised."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .diagnostics import Diagnostic, Severity

if TYPE_CHECKING:
    from .devices import Device
    from .model import AprsData

__all__ = ["Packet", "PathEntry", "QConstruct"]

Q_CONSTRUCTS = frozenset({"qAC", "qAX", "qAU", "qAo", "qAO", "qAS", "qAr", "qAR", "qAZ", "qAI"})
"""The APRS-IS q-constructs, including ``qAr`` and ``qAo`` beside ``qAR`` and ``qAO``."""


@dataclass(frozen=True, slots=True)
class PathEntry:
    """One digipeater path entry. ``used``: the packet has been through it (``*`` in TNC2)."""

    call: str
    used: bool = False

    def __str__(self) -> str:
        return self.call + ("*" if self.used else "")


@dataclass(frozen=True, slots=True)
class QConstruct:
    """An APRS-IS q-construct in the path (``qAR``) and the station named after it."""

    construct: str
    station: str | None = None


@dataclass(frozen=True, slots=True)
class Packet:
    """A decoded APRS packet.

    ``info`` is the information field exactly as received. ``data`` is what was decoded from
    it: always present, an :class:`~packet_aprs.model.Unrecognized` when nothing could be.
    ``diagnostics`` lists everything the decoder noticed, header included.
    """

    source: str
    destination: str
    path: tuple[PathEntry, ...]
    info: bytes
    data: AprsData
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def q_construct(self) -> QConstruct | None:
        """The q-construct in the path, when the packet came through APRS-IS."""
        for i, entry in enumerate(self.path):
            if entry.call in Q_CONSTRUCTS:
                station = self.path[i + 1].call if i + 1 < len(self.path) else None
                return QConstruct(entry.call, station)
        return None

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is Severity.WARNING)

    @property
    def device(self) -> Device | None:
        """The sending device, from the aprs-deviceid database: by Mic-E type code and suffix,
        or else by the destination address (the "tocall")."""
        from .devices import identify

        return identify(self)

    @property
    def header(self) -> str:
        """The TNC2 header, ``SOURCE>DEST,PATH``."""
        return ">".join((self.source, ",".join([self.destination, *map(str, self.path)])))

    def to_tnc2(self) -> bytes:
        """The packet as a TNC2 / APRS-IS line (without a line terminator)."""
        return self.header.encode("ascii") + b":" + self.info

    def __str__(self) -> str:
        return self.to_tnc2().decode("utf-8", "backslashreplace")

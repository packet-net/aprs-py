"""A decoded packet: its header, its raw information field, the data decoded from it, and the
diagnostics the decoder raised."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .diagnostics import Diagnostic, Severity
from .errors import EncodeError, RefusalCode

if TYPE_CHECKING:
    from .devices import Device
    from .model import AprsData

__all__ = ["Packet", "PathEntry", "QConstruct"]


def _is_q_construct(call: str) -> bool:
    """``qA`` and a letter: a q-construct, whether or not the APRS-IS algorithm defines it."""
    return len(call) == 3 and call.startswith("qA") and call[2].isascii() and call[2].isalpha()


def _tnc2_path(path: tuple[PathEntry, ...]) -> str:
    """A path as TNC2 writes it: a ``*`` after the last entry used, which implies the ones
    before it."""
    last = max((i for i, p in enumerate(path) if p.used), default=-1)
    return ",".join(p.address + ("*" if i == last else "") for i, p in enumerate(path))


def _skips_a_used_entry(path: tuple[PathEntry, ...]) -> bool:
    """Whether an entry not marked used comes before one that is: a line and a frame both read the
    entry used (an entry before a used one is used), so neither can carry such a path as given."""
    seen_used = False
    for entry in reversed(path):
        if entry.used:
            seen_used = True
        elif seen_used:
            return True
    return False


@dataclass(frozen=True, slots=True)
class PathEntry:
    """One digipeater path entry. ``used``: the packet has been through it (``*`` in TNC2)."""

    address: str
    used: bool = False

    def __str__(self) -> str:
        return self.address + ("*" if self.used else "")


@dataclass(frozen=True, slots=True)
class QConstruct:
    """An APRS-IS q-construct in the path (``qAR``) and the station named after it."""

    construct: str
    station: str | None = None


@dataclass(frozen=True, slots=True)
class Packet:
    """A decoded APRS packet.

    ``info`` is the information field exactly as received. ``data`` is what was decoded from
    it: always present, an :class:`~pdn_aprs.model.Unrecognized` when nothing could be.
    ``diagnostics`` lists everything the decoder noticed, header included. ``third_party`` is
    true for the packet inside a third-party packet (``}``), whose path is kept as sent.
    """

    source: str
    destination: str
    path: tuple[PathEntry, ...]
    info: bytes
    data: AprsData
    diagnostics: tuple[Diagnostic, ...] = ()
    third_party: bool = False

    @property
    def q_construct(self) -> QConstruct | None:
        """The q-construct in the path, when the packet came through APRS-IS. It is only read in
        an outer header: a third-party packet's path is kept as sent, and has none."""
        if self.third_party:
            return None
        for i, entry in enumerate(self.path):
            if _is_q_construct(entry.address):
                station = self.path[i + 1].address if i + 1 < len(self.path) else None
                return QConstruct(entry.address, station)
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
        from .devices import _identify

        return _identify(self)

    @property
    def header(self) -> str:
        """The TNC2 header, ``SOURCE>DEST,PATH``, with a ``*`` on the last used entry.

        It is read back like any header the library writes: a header that does not read back as
        this packet's source, destination and path raises :class:`EncodeError` (``tnc2-cannot-carry``
        for a path with an entry not marked used before one that is)."""
        path = _tnc2_path(self.path)
        text = f"{self.source}>{self.destination}" + ("," + path if path else "")
        self._read_back_tnc2_header(text)
        return text

    def _read_back_tnc2_header(self, text: str) -> None:
        """The header written, read back: the same source, destination and path (entry by entry, each
        used exactly when this packet's is) and no diagnostic the packet does not already carry."""
        from ._decode import Ctx, RejectedError, parse_tnc2_header
        from .errors import HeaderError
        from .options import _LENIENT

        ctx = Ctx(_LENIENT)
        try:
            source, destination, path = parse_tnc2_header(text, ctx, third_party=self.third_party)
        except (HeaderError, RejectedError):
            raise EncodeError(
                f"the header {text!r} is not one a TNC2 line can carry", RefusalCode.INVALID_ADDRESS
            ) from None
        if _skips_a_used_entry(self.path):
            raise EncodeError(
                "a path entry not marked used before one that is would read back used in a TNC2 line",
                RefusalCode.TNC2_CANNOT_CARRY,
            )
        # a defect the packet already carries (an empty destination it was decoded with) is its data
        new = [d for d in ctx.diags if d not in self.diagnostics]
        if (source, destination, path) != (self.source, self.destination, self.path) or new:
            raise EncodeError(
                f"the header {text!r} would not read back as this packet's", RefusalCode.DOES_NOT_READ_BACK
            )

    def to_tnc2(self) -> bytes:
        """The packet as a TNC2 / APRS-IS line (without a line terminator).

        This writes out a packet the program already holds, so it is not an encoder: the information
        field goes through as it stands, with no size check. The header it writes is read back
        (see :attr:`header`).
        """
        return self.header.encode("ascii") + b":" + self.info

    def to_ax25(self) -> bytes:
        """The packet as an AX.25 UI frame without flags or FCS (a KISS payload).

        Every address must be a valid AX.25 address (1-6 upper-case letters and digits, SSID
        0-15), so an APRS-IS path with a q-construct cannot be written. The information field goes
        through as it stands: this is not an encoder, and does not check its size.
        """
        path = self.path
        if len(path) > 8:
            raise EncodeError("an AX.25 frame has at most 8 digipeaters", RefusalCode.AX25_CANNOT_CARRY)
        frame = bytearray(_ax25_address(self.destination, command=True))
        frame += _ax25_address(self.source, last=not path)
        for i, entry in enumerate(path):
            frame += _ax25_address(entry.address, last=i == len(path) - 1, repeated=entry.used)
        frame += b"\x03\xf0"
        self._read_back_ax25_header(bytes(frame))
        return bytes(frame) + self.info

    def _read_back_ax25_header(self, frame: bytes) -> None:
        """The addresses written, read back: the same source, destination and path (the H bit set on
        exactly the entries this packet has used) and no diagnostic the packet does not already carry."""
        from ._decode import decode_ax25
        from .errors import HeaderError

        if _skips_a_used_entry(self.path):
            raise EncodeError(
                "a path entry not marked used before one that is would read back used in an AX.25 frame",
                RefusalCode.AX25_CANNOT_CARRY,
            )
        try:
            again = decode_ax25(frame)
        except HeaderError:
            raise EncodeError(
                "the addresses are not ones an AX.25 frame can carry", RefusalCode.AX25_CANNOT_CARRY
            ) from None
        new = [d for d in again.diagnostics if d not in self.diagnostics]
        if (again.source, again.destination, again.path) != (self.source, self.destination, self.path) or new:
            raise EncodeError("the addresses would not read back as this packet's", RefusalCode.DOES_NOT_READ_BACK)

    def to_kiss(self, port: int = 0) -> bytes:
        """The packet as a KISS data frame, with ``FEND`` delimiters, for a KISS TNC.

        Like :meth:`to_ax25` it writes the information field as it stands, with no size check.
        """
        if not 0 <= port <= 15:
            raise ValueError("a KISS port is 0-15")
        body = self.to_ax25().replace(b"\xdb", b"\xdb\xdd").replace(b"\xc0", b"\xdb\xdc")
        return b"\xc0" + bytes([port << 4]) + body + b"\xc0"

    def __str__(self) -> str:
        return self.to_tnc2().decode("utf-8", "backslashreplace")


def _ax25_address(name: str, *, last: bool = False, command: bool = False, repeated: bool = False) -> bytes:
    call, dash, ssid_text = name.partition("-")
    if dash and not ssid_text:
        # a dash with no SSID would come back from the frame as no dash
        raise EncodeError(
            f"{name!r} is not an AX.25 address as sent: a dash with no SSID", RefusalCode.AX25_CANNOT_CARRY
        )
    if not 1 <= len(call) <= 6 or not all("A" <= c <= "Z" or "0" <= c <= "9" for c in call):
        raise EncodeError(
            f"{name!r} is not an AX.25 address: 1-6 upper-case letters and digits", RefusalCode.AX25_CANNOT_CARRY
        )
    if ssid_text and not (ssid_text.isascii() and ssid_text.isdigit() and int(ssid_text) <= 15):
        raise EncodeError(f"{name!r} is not an AX.25 address: the SSID is 0-15", RefusalCode.AX25_CANNOT_CARRY)
    if ssid_text and (ssid_text != str(int(ssid_text)) or ssid_text == "0"):
        # -00 or -0 would come back from the frame as no SSID, so AX.25 cannot carry it as sent
        raise EncodeError(
            f"{name!r} is not an AX.25 address as sent: the SSID has a leading zero", RefusalCode.AX25_CANNOT_CARRY
        )
    ssid = int(ssid_text) if ssid_text else 0
    flag = 0x80 if (command or repeated) else 0
    return bytes(ord(c) << 1 for c in call.ljust(6)) + bytes([0x60 | flag | (ssid << 1) | (1 if last else 0)])

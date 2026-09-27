"""Decoding: TNC2 lines and AX.25 frames into packets, and information fields into data.

The information field is parsed one character per byte (Latin-1), so that structure is found
byte by byte whatever the text encoding; text fields are then read as UTF-8, or as Latin-1
when they are not UTF-8 (``non-utf8-text``).
"""

from __future__ import annotations

import math
import re
from typing import Any, NoReturn

from . import _util
from ._comment import CommentParts, lift_comment, lift_telemetry_dao, parse_extension
from ._weather import parse_weather_fields, raise_field_defects, weather_tail
from .diagnostics import Diagnostic, DiagnosticCode, Severity
from .errors import HeaderError
from .model import (
    Ack,
    AgreloDf,
    AprsData,
    Beam,
    Bulletin,
    Capabilities,
    CompressionType,
    DirectedQuery,
    Footprint,
    ItemReport,
    MaidenheadBeacon,
    Message,
    MicEMessage,
    MicEReport,
    NmeaFix,
    NmeaSentence,
    NmeaSource,
    NwsBulletin,
    ObjectReport,
    PositionlessWeather,
    PositionReport,
    Query,
    RawWeather,
    RawWeatherFormat,
    Reject,
    StatusReport,
    TelemetryBits,
    TelemetryCoefficients,
    TelemetryNames,
    TelemetryReport,
    TelemetryUnits,
    TestData,
    ThirdParty,
    Timestamp,
    Unrecognized,
    UnrecognizedReason,
    UserDefined,
    Weather,
)
from .options import LENIENT, ParseOptions
from .packet import Packet, PathEntry
from .symbols import Symbol

C = DiagnosticCode

_DIAG: dict[tuple[Severity, DiagnosticCode], Diagnostic] = {
    (s, c): Diagnostic(s, c) for s in Severity for c in DiagnosticCode
}


class RejectedError(Exception):
    """Raised inside the decoder when a packet (or header) cannot be decoded."""


class Ctx:
    """Decoding state: the options, the diagnostics so far, and whether text was not UTF-8."""

    __slots__ = ("diags", "non_utf8", "options")

    def __init__(self, options: ParseOptions) -> None:
        self.options = options
        self.diags: list[Diagnostic] = []
        self.non_utf8 = False

    def info(self, code: DiagnosticCode) -> None:
        self.diags.append(_DIAG[(Severity.INFO, code)])

    def warn(self, code: DiagnosticCode) -> None:
        self.diags.append(_DIAG[(Severity.WARNING, code)])

    def fail(self, code: DiagnosticCode) -> NoReturn:
        self.diags.append(_DIAG[(Severity.ERROR, code)])
        raise RejectedError

    def defect(self, code: DiagnosticCode) -> None:
        """A tolerable defect: a warning when tolerated, else an error that rejects."""
        if self.options.tolerates(code):
            self.diags.append(_DIAG[(Severity.WARNING, code)])
        else:
            self.fail(code)

    def tolerates(self, code: DiagnosticCode) -> bool:
        return self.options.tolerates(code)

    def text(self, raw: str) -> str:
        """A text field read as UTF-8, or kept as Latin-1 (and noted) when it is not."""
        if raw.isascii():
            return raw
        text, ok = _util.utf8_or_latin1(raw)
        if not ok:
            self.non_utf8 = True
        return text

    def flush_text(self) -> None:
        """Raise ``non-utf8-text`` now, for a format that checks the text before its structure."""
        if self.non_utf8:
            self.non_utf8 = False
            self.defect(C.NON_UTF8_TEXT)

    def trial(self) -> Ctx:
        """A scratch context for trying a reading without committing its diagnostics."""
        return Ctx(self.options)


# ------------------------------------------------------------------ header


_ADDRESS = re.compile(r"[A-Za-z0-9-]{1,9}\Z")
_THIRD_PARTY_SOURCE = re.compile(r"[ -9;-=?-~]{1,9}\Z")
"""A third-party header's source: 1-9 printable ASCII characters other than ``>`` and ``:``
(APRS12c ch. 17)."""


def _header_error(ctx: Ctx, code: DiagnosticCode) -> NoReturn:
    ctx.diags.append(_DIAG[(Severity.ERROR, code)])
    raise HeaderError(f"unusable header: {code.value}", ctx.diags)


def _header_defect(ctx: Ctx, code: DiagnosticCode) -> None:
    if ctx.tolerates(code):
        ctx.warn(code)
    else:
        _header_error(ctx, code)


def parse_tnc2_header(header: str, ctx: Ctx, *, third_party: bool = False) -> tuple[str, str, tuple[PathEntry, ...]]:
    """``SOURCE>DEST,PATH`` into its parts.

    With ``third_party`` it is the header inside a third-party packet: the source may be any 1-9
    printable characters other than ``>`` and ``:``, a defect the options tolerate is a warning
    in ``ctx`` (the inner packet's), and anything else raises :class:`RejectedError`, which the
    caller reports as ``invalid-third-party``.
    """

    def bad(code: DiagnosticCode) -> NoReturn:
        if third_party:
            raise RejectedError
        _header_error(ctx, code)

    def defect(code: DiagnosticCode) -> None:
        if ctx.tolerates(code):
            ctx.warn(code)
        else:
            bad(code)

    gt = header.find(">")
    if gt <= 0:
        bad(C.INVALID_HEADER)
    source = header[:gt]
    parts = header[gt + 1 :].split(",")
    destination = parts[0]
    if not (_THIRD_PARTY_SOURCE if third_party else _ADDRESS).match(source):
        bad(C.INVALID_ADDRESS)
    if not destination:
        defect(C.EMPTY_DESTINATION)
    elif not _ADDRESS.match(destination):
        bad(C.INVALID_ADDRESS)
    calls: list[str] = []
    empty = False
    for entry in parts[1:]:
        if not entry:
            empty = True
            continue
        if not _ADDRESS.match(entry[:-1] if entry.endswith("*") else entry):
            bad(C.INVALID_ADDRESS)
        calls.append(entry)
    if empty:
        defect(C.EMPTY_PATH_ENTRY)
    # entries up to the last one marked * are used
    stars = [i for i, call in enumerate(calls) if call.endswith("*")]
    if len(stars) > 1:
        defect(C.MULTIPLE_USED_MARKERS)
    last = stars[-1] if stars else -1
    path = tuple(PathEntry(call.rstrip("*"), i <= last) for i, call in enumerate(calls))
    return source, destination, path


def decode_tnc2(line: bytes | str, options: ParseOptions = LENIENT) -> Packet:
    """Decode a TNC2 / APRS-IS line. A ``str`` is encoded as UTF-8 first."""
    raw = line.encode("utf-8") if isinstance(line, str) else bytes(line)
    ctx = Ctx(options)
    colon = raw.find(b":")
    if colon < 0:
        _header_error(ctx, C.INVALID_HEADER)
    header_bytes = raw[:colon]
    info = raw[colon + 1 :]
    if not header_bytes.isascii():
        head = header_bytes.decode("latin-1")
        gt = head.find(">")
        _header_error(ctx, C.INVALID_HEADER if gt <= 0 else C.INVALID_ADDRESS)
    source, destination, path = parse_tnc2_header(header_bytes.decode("ascii"), ctx)
    data = decode_info(info, destination, ctx)
    return Packet(source, destination, path, info, data, tuple(ctx.diags))


def _ax25_address(ctx: Ctx, raw: bytes) -> tuple[str, bool]:
    """One 7-byte AX.25 address: the name (with ``-SSID``) and its H bit."""
    chars = [b >> 1 for b in raw[:6]]
    if 0 in chars:
        stripped = bytes(chars).rstrip(b"\x00 ")
        if 0 in stripped:
            _header_defect(ctx, C.INVALID_AX25_ADDRESS_CHARACTERS)
        else:
            _header_defect(ctx, C.NUL_PADDED_ADDRESS)
    call = bytes(chars).replace(b"\x00", b" ").rstrip(b" ").decode("latin-1")
    if any(not ("A" <= c <= "Z" or "0" <= c <= "9") for c in call):
        _header_defect(ctx, C.INVALID_AX25_ADDRESS_CHARACTERS)
    ssid = (raw[6] >> 1) & 0x0F
    name = f"{call}-{ssid}" if ssid else call
    return name, bool(raw[6] & 0x80)


def decode_ax25(frame: bytes, options: ParseOptions = LENIENT) -> Packet:
    """Decode an AX.25 UI frame without flags or FCS (the KISS payload)."""
    frame = bytes(frame)
    ctx = Ctx(options)
    addresses: list[bytes] = []
    i = 0
    while True:
        if i + 7 > len(frame):
            _header_error(ctx, C.NOT_APRS_FRAME)
        addresses.append(frame[i : i + 7])
        i += 7
        if frame[i - 1] & 1:
            break
        if len(addresses) > 10:
            _header_error(ctx, C.TOO_MANY_DIGIPEATERS)
    if len(addresses) < 2 or i + 2 > len(frame):
        _header_error(ctx, C.NOT_APRS_FRAME)
    if frame[i] & ~0x10 != 0x03 or frame[i + 1] != 0xF0:
        _header_error(ctx, C.NOT_APRS_FRAME)
    if len(addresses) > 10:
        _header_error(ctx, C.TOO_MANY_DIGIPEATERS)
    destination, _ = _ax25_address(ctx, addresses[0])
    source, _ = _ax25_address(ctx, addresses[1])
    if not source:
        _header_error(ctx, C.INVALID_ADDRESS)
    if not destination:
        _header_defect(ctx, C.EMPTY_DESTINATION)
    digis = [_ax25_address(ctx, a) for a in addresses[2:]]
    if any(not name for name, _ in digis):
        _header_defect(ctx, C.EMPTY_PATH_ENTRY)
    digis = [(name, used) for name, used in digis if name]
    last = max((j for j, (_, used) in enumerate(digis) if used), default=-1)
    path = tuple(PathEntry(name, j <= last) for j, (name, _) in enumerate(digis))
    info = frame[i + 2 :]
    data = decode_info(info, destination, ctx)
    return Packet(source, destination, path, info, data, tuple(ctx.diags))


def decode_kiss(frame: bytes, options: ParseOptions = LENIENT) -> Packet:
    """Decode a KISS data frame: optional ``FEND`` delimiters, the command byte, then an
    escaped AX.25 frame."""
    data = bytes(frame).strip(b"\xc0")
    if not data or data[0] & 0x0F != 0:
        ctx = Ctx(options)
        _header_error(ctx, C.NOT_APRS_FRAME)
    body = data[1:].replace(b"\xdb\xdc", b"\xc0").replace(b"\xdb\xdd", b"\xdb")
    return decode_ax25(body, options)


# ------------------------------------------------------------------ information field


def decode_info(info: bytes, destination: str, ctx: Ctx) -> AprsData:
    """The data in an information field; the diagnostics go into ``ctx``."""
    s = info.decode("latin-1")
    try:
        if s.endswith(("\r", "\n")):
            s = s.rstrip("\r\n")
            ctx.defect(C.TRAILING_LINE_BREAK)
        if not s:
            return Unrecognized(UnrecognizedReason.EMPTY)
        handler = _HANDLERS.get(s[0])
        if handler is None:
            data = _other(s, destination, ctx)
        else:
            data = handler(s, destination, ctx)
        if ctx.non_utf8:
            ctx.defect(C.NON_UTF8_TEXT)
        return data
    except RejectedError:
        return Unrecognized(UnrecognizedReason.MALFORMED)


def _other(s: str, destination: str, ctx: Ctx) -> AprsData:
    """A first byte that is not a data type identifier. An obsolete TNC beacon rule allows a
    ``!`` position further on."""
    bang = s.find("!", 0, 40)
    if bang > 0 and ctx.tolerates(C.POSITION_NOT_AT_START):
        trial = ctx.trial()
        try:
            data = _position(s[bang:], destination, trial)
        except RejectedError:
            pass
        else:
            if isinstance(data, PositionReport):
                ctx.warn(C.POSITION_NOT_AT_START)
                ctx.diags.extend(trial.diags)
                ctx.non_utf8 = trial.non_utf8
                return data
    ctx.info(C.NOT_APRS)
    return Unrecognized(UnrecognizedReason.NOT_APRS)


# ------------------------------------------------------------------ positions


class Pos:
    """A position as read, before the rest of the report is interpreted."""

    __slots__ = ("ambiguity", "compressed", "cs", "lat", "lon", "symbol")

    def __init__(
        self,
        lat: float,
        lon: float,
        symbol: Symbol,
        ambiguity: int,
        compressed: bool,
        cs: tuple[int, int, int] | None,
    ) -> None:
        self.lat = lat
        self.lon = lon
        self.symbol = symbol
        self.ambiguity = ambiguity
        self.compressed = compressed
        self.cs = cs


_AMBIGUITY_UNIT = (0.0, 0.1, 1.0, 10.0, 60.0)
"""The size, in minutes, of the box each ambiguity level leaves."""


def _coordinate(text: str, degree_digits: int, ambiguity: int | None) -> tuple[float, int] | None:
    """``ddmm.hh`` or ``dddmm.hh`` (hemisphere removed) in minutes, with its ambiguity level.

    For a latitude (``ambiguity`` None) the level is its run of trailing spaces, at most 4. For a
    longitude it is the latitude's: each digit place that level blanks is ignored and may hold a
    digit or a space, and every other place must be a digit (vectors interpretations.md,
    "Longitude blanks follow the latitude"). The result is the centre of the box the level
    leaves. Returns None when malformed.
    """
    if len(text) != degree_digits + 5 or text[degree_digits + 2] != ".":
        return None
    digits = text[: degree_digits + 2] + text[degree_digits + 3 :]
    n = len(digits)
    if ambiguity is None:
        level = 0
        while level < n and digits[n - 1 - level] == " ":
            level += 1
        if level > 4:
            return None
    else:
        level = ambiguity
        if any(not ("0" <= ch <= "9" or ch == " ") for ch in digits[n - level :]):
            return None
    if any(not ("0" <= ch <= "9") for ch in digits[: n - level]):
        return None
    kept = digits[: n - level] + "0" * level
    degrees = int(kept[:degree_digits])
    minutes = int(kept[degree_digits : degree_digits + 2]) + int(kept[degree_digits + 2 :]) / 100
    if level:
        minutes += _AMBIGUITY_UNIT[level] / 2
    if int(kept[degree_digits : degree_digits + 2]) > 59:
        return None
    return degrees * 60 + minutes, level


def _uncompressed(s: str, pos: int, ctx: Ctx) -> Pos:
    if len(s) < pos + 19:
        ctx.fail(C.TRUNCATED)
    lat_text = s[pos : pos + 8]
    table = s[pos + 8]
    lon_text = s[pos + 9 : pos + 18]
    code = s[pos + 18]
    hemi = lat_text[7]
    lat = _coordinate(lat_text[:7], 2, None)
    if lat is None or hemi not in "NSns" or lat[0] > 90 * 60:
        ctx.fail(C.INVALID_LATITUDE)
    if hemi in "ns":
        ctx.defect(C.LOWERCASE_HEMISPHERE)
    ambiguity = lat[1]
    if not _util.is_symbol_table(table):
        ctx.fail(C.INVALID_SYMBOL_TABLE)
    ehemi = lon_text[8]
    lon = _coordinate(lon_text[:8], 3, ambiguity)
    if lon is None or ehemi not in "EWew" or lon[0] > 180 * 60:
        ctx.fail(C.INVALID_LONGITUDE)
    if ehemi in "ew":
        ctx.defect(C.LOWERCASE_HEMISPHERE)
    if not _util.is_symbol_code(code):
        ctx.fail(C.INVALID_SYMBOL_CODE)
    latitude = lat[0] / 60
    longitude = lon[0] / 60
    if hemi in "Ss":
        latitude = -latitude
    if ehemi in "Ww":
        longitude = -longitude
    return Pos(latitude, longitude, Symbol(table, code), ambiguity, False, None)


def _compressed(s: str, pos: int, ctx: Ctx) -> Pos:
    if len(s) < pos + 13:
        ctx.fail(C.TRUNCATED)
    table = s[pos]
    body = s[pos + 1 : pos + 9]
    code = s[pos + 9]
    c, sp, t = s[pos + 10], s[pos + 11], s[pos + 12]
    if not _util.is_base91(body):
        ctx.fail(C.INVALID_COMPRESSED_POSITION)
    lat = 90 - _util.base91_value(body[:4]) / 380926
    lon = -180 + _util.base91_value(body[4:]) / 190463
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        ctx.fail(C.INVALID_COMPRESSED_POSITION)
    if not _util.is_symbol_code(code):
        ctx.fail(C.INVALID_SYMBOL_CODE)
    cs: tuple[int, int, int] | None = None
    if c != " ":
        if not _util.is_base91(c + sp + t):
            ctx.fail(C.INVALID_COMPRESSED_POSITION)
        cs = (ord(c) - 33, ord(sp) - 33, ord(t) - 33)
        if cs[2] & 0xC0:
            ctx.defect(C.COMPRESSION_TYPE_RESERVED_BITS)
    if "a" <= table <= "j":
        table = chr(ord(table) - ord("a") + ord("0"))
    return Pos(lat, lon, Symbol(table, code), 0, True, cs)


def read_position(s: str, pos: int, ctx: Ctx) -> Pos:  # noqa: RET503
    """The position at ``pos``: uncompressed if it starts with a digit, else compressed."""
    first = s[pos : pos + 1]
    if not first:
        ctx.fail(C.TRUNCATED)
    if "0" <= first <= "9":
        return _uncompressed(s, pos, ctx)
    if first in "/\\" or "A" <= first <= "Z" or "a" <= first <= "j":
        return _compressed(s, pos, ctx)
    ctx.fail(C.INVALID_POSITION)


def _position_decodes(s: str, pos: int, ctx: Ctx) -> bool:
    trial = ctx.trial()
    try:
        read_position(s, pos, trial)
    except RejectedError:
        return False
    return True


def _is_timestamp7(text: str) -> bool:
    return len(text) == 7 and text[:6].isdigit() and text[:6].isascii() and text[6] in "z/h"


def _position(s: str, destination: str, ctx: Ctx) -> AprsData:
    dti = s[0]
    if dti == "!" and s[1:2] == "!":
        return _raw_weather(s, RawWeatherFormat.ULTIMETER_LOGGING, 2, ctx)
    messaging = dti in "=@"
    timestamp: Timestamp | None = None
    pos = 1
    if dti in "/@":
        ts = s[1:8]
        if _is_timestamp7(ts):
            timestamp = Timestamp(ts)
            if not timestamp.is_valid:
                ctx.defect(C.INVALID_TIMESTAMP)
            pos = 8
        elif _position_decodes(s, 1, ctx):
            ctx.defect(C.MALFORMED_TIMESTAMP)
        elif _position_decodes(s, 8, ctx):
            ctx.defect(C.MALFORMED_TIMESTAMP)
            pos = 8
        else:
            ctx.fail(C.MALFORMED_TIMESTAMP)
    p = read_position(s, pos, ctx)
    fields = positioned_rest(s, pos + (13 if p.compressed else 19), p, ctx)
    return PositionReport(timestamp=timestamp, messaging=messaging, **fields)


def _compressed_cs(p: Pos, ctx: Ctx, fields: dict[str, Any]) -> str | None:
    """Interpret a compressed position's cs and type bytes into ``fields``.

    Returns what the cs bytes held: ``"course"``, ``"range"``, ``"altitude"`` or None.
    """
    if p.cs is None:
        return None
    c, s, t = p.cs
    ctype = CompressionType.from_value(t)
    fields["compression"] = ctype
    if ctype.source is NmeaSource.GGA:
        fields["altitude_feet"] = 1.002 ** (c * 91 + s)
        return "altitude"
    if c == 90:
        fields["range_miles"] = 2 * 1.08**s
        return "range"
    return "course"


def positioned_rest(s: str, pos: int, p: Pos, ctx: Ctx) -> dict[str, Any]:
    """Everything after the position: data extension, weather, comment elements."""
    fields: dict[str, Any] = {
        "latitude": p.lat,
        "longitude": p.lon,
        "symbol": p.symbol,
    }
    if p.ambiguity:
        fields["ambiguity"] = p.ambiguity
    if p.compressed:
        fields["compressed"] = True
    held = _compressed_cs(p, ctx, fields)
    rest = s[pos:]
    if p.symbol.code == "_":
        _weather_report(rest, p, held, ctx, fields)
        return fields
    if held == "course" and p.cs is not None:
        c, sp, _ = p.cs
        fields["course_degrees"] = 360 if c == 0 else c * 4
        fields["speed_knots"] = 1.08**sp - 1
    ext_kind: str | None = None
    if not p.compressed:
        ext = parse_extension(rest, p.symbol, ctx)
        if ext is not None:
            ext_kind, consumed, values = ext
            fields.update(values)
            rest = rest[consumed:]
    range_family = ext_kind in ("phg", "range", "dfs") or held == "range"
    parts = lift_comment(
        rest,
        ctx,
        symbol=p.symbol,
        late_extensions=not range_family,
        area=fields.get("area"),
    )
    _apply_parts(parts, p, ctx, fields)
    return fields


def _apply_parts(parts: CommentParts, p: Pos, ctx: Ctx, fields: dict[str, Any]) -> None:
    """Put the elements lifted out of a comment into the fields, applying a DAO's precision."""
    for key, value in parts.fields.items():
        fields[key] = value
    if parts.dao is not None:
        fields["dao"] = parts.dao
        if p.ambiguity:
            ctx.defect(C.DAO_WITH_AMBIGUITY)
        elif not p.compressed and (parts.dao_lat or parts.dao_lon):
            lat = float(fields["latitude"])
            lon = float(fields["longitude"])
            # the added precision is on the position's own side of the equator or meridian, even
            # at 0 degrees (-0.0 south or west)
            fields["latitude"] = lat + math.copysign(parts.dao_lat / 60, lat)
            fields["longitude"] = lon + math.copysign(parts.dao_lon / 60, lon)
    fields["comment"] = ctx.text(parts.comment)


_WIND_EXT = re.compile(r"([0-9 .]{3})/([0-9 .]{3})")


def _wind_value(text: str) -> int | None:
    t = text.strip(". ")
    if not t:
        return None
    if not t.isdigit() or len(t) != len(text):
        return None
    return int(text)


def _weather_report(rest: str, p: Pos, held: str | None, ctx: Ctx, fields: dict[str, Any]) -> None:
    """A position or object with the weather symbol: wind, weather fields, maybe text."""
    wind: dict[str, Any] = {}
    wind_sent = False
    if held == "course" and p.cs is not None:
        c, sp, _ = p.cs
        wind["wind_direction_degrees"] = c * 4
        wind["wind_speed_mph"] = (1.08**sp - 1) * _util.KNOTS_TO_MPH
        wind_sent = True
    m = _WIND_EXT.match(rest)
    if m and _is_wind_ext(m.group(1)) and _is_wind_ext(m.group(2)):
        if p.compressed:
            ctx.defect(C.WIND_EXTENSION_AFTER_COMPRESSED)
        wind = {}
        direction = _wind_value(m.group(1))
        speed = _wind_value(m.group(2))
        if direction is not None:
            if direction > 360:
                ctx.defect(C.OUT_OF_RANGE_VALUE)
            else:
                wind["wind_direction_degrees"] = direction
        if speed is not None:
            wind["wind_speed_mph"] = speed
        wind_sent = True
        rest = rest[7:]
    result = parse_weather_fields(rest, positionless=False, wind_known=wind_sent)
    if not wind_sent:
        # the wind is judged where its extension belongs, before any field: sent as c and s
        # fields instead, or missing or incomplete (not after a compressed position, whose cs
        # bytes say it is unknown)
        if result.wind_from_fields:
            ctx.defect(C.WIND_FIELDS_INSTEAD_OF_EXTENSION)
        if not p.compressed and not (result.direction_sent and result.speed_sent):
            ctx.defect(C.INCOMPLETE_WEATHER)
    raise_field_defects(result, ctx, positionless=False)
    weather = dict(wind)
    weather.update(result.values)
    if (
        p.compressed
        and "compression" not in fields
        and ("wind_direction_degrees" in weather or "wind_speed_mph" in weather)
    ):
        # wind that was not in the cs bytes gets the default compression type
        fields["compression"] = CompressionType()
    parts = CommentParts()
    text = lift_telemetry_dao(result.text, parts)
    text = weather_tail(text, ctx, weather)
    if text[:1] in (" ", "/"):
        text = text[1:]
    parts.comment = text
    fields["weather"] = Weather(**weather)
    _apply_parts(parts, p, ctx, fields)


def _is_wind_ext(text: str) -> bool:
    return text.isdigit() or text in ("...", "   ")


# ------------------------------------------------------------------ objects and items


def _object(s: str, destination: str, ctx: Ctx) -> AprsData:
    if len(s) < 11:
        ctx.fail(C.TRUNCATED)
    if s[10] in "*_":
        mark = 10
    else:
        mark = -1
        for i in range(1, 10):
            if s[i] in "*_":
                mark = i
                break
        if mark < 0:
            ctx.fail(C.INVALID_OBJECT_NAME)
        ctx.defect(C.OBJECT_NAME_NOT_PADDED)
    name = s[1:mark].rstrip(" ")
    if not name or not _util.is_printable_ascii(name):
        ctx.fail(C.INVALID_OBJECT_NAME)
    killed = s[mark] == "_"
    pos = mark + 1
    timestamp: Timestamp | None = None
    ts = s[pos : pos + 7]
    if _is_timestamp7(ts):
        timestamp = Timestamp(ts)
        if not timestamp.is_valid:
            ctx.defect(C.INVALID_TIMESTAMP)
        pos += 7
    elif (
        len(ts) == 7
        and ((ts[:6].isdigit() and ts[:6].isascii()) or ts[6] in "z/h")
        and _position_decodes(s, pos + 7, ctx)
    ):
        ctx.defect(C.MALFORMED_TIMESTAMP)
        pos += 7
    else:
        ctx.defect(C.OBJECT_WITHOUT_TIMESTAMP)
    p = read_position(s, pos, ctx)
    fields = positioned_rest(s, pos + (13 if p.compressed else 19), p, ctx)
    return ObjectReport(name=name, killed=killed, timestamp=timestamp, **fields)


def _item(s: str, destination: str, ctx: Ctx) -> AprsData:
    mark = -1
    for i in range(4, min(len(s), 11)):
        if s[i] in "!_":
            mark = i
            break
    if mark < 0:
        ctx.fail(C.INVALID_ITEM_NAME)
    name = s[1:mark]
    if not _util.is_printable_ascii(name):
        ctx.fail(C.INVALID_ITEM_NAME)
    killed = s[mark] == "_"
    pos = mark + 1
    p = read_position(s, pos, ctx)
    fields = positioned_rest(s, pos + (13 if p.compressed else 19), p, ctx)
    return ItemReport(name=name, killed=killed, **fields)


# ------------------------------------------------------------------ Mic-E

_MICE_STANDARD = {
    7: MicEMessage.OFF_DUTY,
    6: MicEMessage.EN_ROUTE,
    5: MicEMessage.IN_SERVICE,
    4: MicEMessage.RETURNING,
    3: MicEMessage.COMMITTED,
    2: MicEMessage.SPECIAL,
    1: MicEMessage.PRIORITY,
}
_MICE_CUSTOM = {
    7: MicEMessage.CUSTOM0,
    6: MicEMessage.CUSTOM1,
    5: MicEMessage.CUSTOM2,
    4: MicEMessage.CUSTOM3,
    3: MicEMessage.CUSTOM4,
    2: MicEMessage.CUSTOM5,
    1: MicEMessage.CUSTOM6,
}

_MICE_ALTITUDE = re.compile(r"[!-{]{3}\}")


def _mic_e_destination(destination: str, ctx: Ctx) -> tuple[float, int, str, bool, bool, bool, int]:
    """Latitude, ambiguity, message, north, +100 longitude offset, west, SSID."""
    call, _, ssid_text = destination.partition("-")
    ssid = int(ssid_text) if ssid_text.isdigit() and ssid_text.isascii() else 0
    if len(call) != 6:
        ctx.fail(C.INVALID_MIC_E_DESTINATION)
    digits: list[str] = []
    std = [0, 0, 0]
    custom = [0, 0, 0]
    flags = [False, False, False]
    for i, ch in enumerate(call):
        if "0" <= ch <= "9":
            digit = ch
        elif "A" <= ch <= "J" and i < 3:
            digit = chr(ord(ch) - ord("A") + ord("0"))
            custom[i] = 1
        elif ch == "K" and i < 3:
            digit = " "
            custom[i] = 1
        elif ch == "L":
            digit = " "
        elif "P" <= ch <= "Y":
            digit = chr(ord(ch) - ord("P") + ord("0"))
            if i < 3:
                std[i] = 1
            else:
                flags[i - 3] = True
        elif ch == "Z":
            digit = " "
            if i < 3:
                std[i] = 1
            else:
                flags[i - 3] = True
        else:
            ctx.fail(C.INVALID_MIC_E_DESTINATION)
        digits.append(digit)
    text = "".join(digits)
    blanks = len(text) - len(text.rstrip(" "))
    if blanks > 4 or " " in text.rstrip(" "):
        ctx.fail(C.INVALID_MIC_E_DESTINATION)
    kept = text.rstrip(" ") + "0" * blanks
    degrees = int(kept[:2])
    minutes = int(kept[2:4]) + int(kept[4:6]) / 100
    if int(kept[2:4]) > 59 or degrees > 90 or (degrees == 90 and minutes > 0):
        ctx.fail(C.INVALID_MIC_E_DESTINATION)
    if blanks:
        minutes += _AMBIGUITY_UNIT[blanks] / 2
    lat = degrees + minutes / 60
    if any(std) and any(custom):
        message = MicEMessage.UNKNOWN.value
    elif any(custom):
        message = _MICE_CUSTOM[custom[0] * 4 + custom[1] * 2 + custom[2]].value
    elif any(std):
        message = _MICE_STANDARD[std[0] * 4 + std[1] * 2 + std[2]].value
    else:
        message = MicEMessage.EMERGENCY.value
    north, offset, west = flags
    return (lat if north else -lat), blanks, message, north, offset, west, ssid


def _mic_e(s: str, destination: str, ctx: Ctx) -> AprsData:
    from .devices import mic_e_suffixes

    if s[0] in "\x1c\x1d":
        # the Rev 0 beta data type identifiers, obsolete (APRS12c ch. 10): said at the DTI,
        # before anything else is checked
        ctx.info(C.OBSOLETE_FORMAT)
    lat, ambiguity, message, _north, offset, west, ssid = _mic_e_destination(destination, ctx)
    if len(s) < 9:
        ctx.fail(C.INVALID_MIC_E_INFORMATION)
    d = ord(s[1]) - 28
    m = ord(s[2]) - 28
    h = ord(s[3]) - 28
    # d+28 is 38-127, m+28 38-97, and the rest 28-127 (APRS12c ch. 10)
    if not (10 <= d <= 99 and 10 <= m <= 69 and 0 <= h <= 99):
        ctx.fail(C.INVALID_MIC_E_INFORMATION)
    if offset:
        d += 100
    if 180 <= d <= 189:
        d -= 80
    elif 190 <= d <= 199:
        d -= 190
    if m >= 60:
        m -= 60
    sp = ord(s[4]) - 28
    dc = ord(s[5]) - 28
    se = ord(s[6]) - 28
    code, table = s[7], s[8]
    if not (0 <= d <= 179 and 0 <= m <= 59 and 0 <= h <= 99 and sp >= 0 and dc >= 0 and se >= 0):
        ctx.fail(C.INVALID_MIC_E_INFORMATION)
    if not (sp <= 99 and dc <= 99 and se <= 99):
        ctx.fail(C.INVALID_MIC_E_INFORMATION)
    speed = sp * 10 + dc // 10
    course = (dc % 10) * 100 + se
    if speed >= 800:
        speed -= 800
    if course >= 400:
        course -= 400
    if course > 360:
        ctx.defect(C.OUT_OF_RANGE_VALUE)
    if not _util.is_symbol_table(table):
        ctx.fail(C.INVALID_SYMBOL_TABLE)
    if not _util.is_symbol_code(code):
        ctx.fail(C.INVALID_SYMBOL_CODE)
    # the longitude's blanked digits follow the latitude's ambiguity
    hundredths = h
    minutes = float(m)
    if ambiguity == 1:
        minutes += (hundredths // 10) / 10 + 0.05
    elif ambiguity == 2:
        minutes += 0.5
    elif ambiguity == 3:
        minutes = (m // 10) * 10 + 5.0
    elif ambiguity == 4:
        minutes = 30.0
    else:
        minutes += hundredths / 100
    lon = d + minutes / 60
    if lon > 180:
        ctx.fail(C.INVALID_MIC_E_INFORMATION)
    if west:
        lon = -lon
    fields: dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "symbol": Symbol(table, code),
    }
    if ambiguity:
        fields["ambiguity"] = ambiguity
    if 0 < course <= 360:
        fields["course_degrees"] = course
    fields["speed_knots"] = speed
    rest = s[9:]
    if "\xff" in rest:
        ctx.defect(C.KENWOOD_FF_PADDING)
        rest = rest.replace("\xff", "")
    # Rev 0 binary telemetry, looked for once the 0xFF padding is gone (vectors interpretations.md).
    legacy: tuple[int, ...] = ()
    if len(rest) >= 6 and rest[0] == "\x1d":
        ctx.info(C.OBSOLETE_FORMAT)
        legacy = tuple(ord(c) for c in rest[1:6])
        rest = rest[6:]
    type_code: str | None = None
    if rest[:1] in ("`", "'", ">", "]", " "):
        type_code = rest[0]
        rest = rest[1:]
    elif rest:
        ctx.info(C.MIC_E_MISSING_DEVICE_TYPE)
    suffix: str | None = None
    if type_code is not None and type_code != " ":
        for candidate in mic_e_suffixes(type_code):
            if candidate and rest.endswith(candidate) and len(rest) >= len(candidate):
                suffix = candidate
                rest = rest[: -len(candidate)]
                break
    altitude: float | None = None
    if _MICE_ALTITUDE.match(rest):
        altitude = _util.base91_value(rest[:3]) - 10000
        rest = rest[4:]
    locator: str | None = None
    loc = _mic_e_locator(rest)
    if loc is not None:
        locator, consumed = loc
        rest = rest[consumed:]
        if rest and rest[0] != " ":
            ctx.defect(C.MISSING_SPACE_AFTER_LOCATOR)
        elif rest:
            rest = rest[1:]
    p = Pos(lat, lon, Symbol(table, code), ambiguity, False, None)
    ext = parse_extension(rest, p.symbol, ctx, mic_e=True)
    ext_kind: str | None = None
    if ext is not None:
        ext_kind, consumed, values = ext
        fields.update(values)
        rest = rest[consumed:]
    # an altitude later in the text is looked for once a data extension at the start is lifted,
    # so that its bytes are never read as one (0PH} in PHG3330PH})
    cuts: tuple[int, ...] = ()
    if altitude is None:
        found = _MICE_ALTITUDE.search(rest)
        if found is not None and ctx.tolerates(C.MIC_E_ALTITUDE_NOT_FIRST):
            ctx.warn(C.MIC_E_ALTITUDE_NOT_FIRST)
            altitude = _util.base91_value(found.group()[:3]) - 10000
            rest = rest[: found.start()] + rest[found.end() :]
            cuts = (found.start(),)
    if altitude is not None:
        fields["altitude_feet"] = altitude * _util.FEET_PER_METRE
    parts = lift_comment(
        rest,
        ctx,
        symbol=p.symbol,
        late_extensions=ext_kind not in ("phg", "range", "dfs"),
        cuts=cuts,
    )
    _apply_parts(parts, p, ctx, fields)
    return MicEReport(
        mic_e_message=MicEMessage(message),
        old_data=s[0] in ("'", "\x1d"),
        type_code=type_code,
        device_suffix=suffix,
        locator=locator,
        legacy_telemetry=legacy,
        destination_ssid=ssid,
        **fields,
    )


def _mic_e_locator(text: str) -> tuple[str, int] | None:
    """A grid locator and ``/G`` at the start of Mic-E status text."""
    if len(text) >= 8 and _util.is_locator6(text[:6]) and text[6:8] == "/G":
        return text[:6].upper(), 8
    if len(text) >= 6 and _util.is_locator4(text[:4]) and text[4:6] == "/G":
        return text[:4].upper(), 6
    return None


# ------------------------------------------------------------------ messages

_ID = re.compile(r"[A-Za-z0-9]{1,5}\Z")
_ACK = re.compile(r"(ack|rej)([A-Za-z0-9]{1,5})(?:\}([A-Za-z0-9]{0,5}))?(?:\{([A-Za-z0-9]{1,5}))?\Z")
_DIRECTED = ("APRSD", "APRSH", "APRSM", "APRSO", "APRSP", "APRSS", "APRST", "PING?")
_CALLSIGN = re.compile(r"[A-Za-z0-9-]{1,9}\Z")
_BULLETIN = re.compile(r"BLN[0-9A-Z]")


def _message_id_parts(text: str, *, reply_ack: bool) -> tuple[str, str | None, str | None, bool]:
    """Text, message ID and reply-ack from text ending ``{ID`` (or, with ``reply_ack``, ``{MM}`` or
    ``{MM}AA``), and whether a ``{`` that starts no message ID was left in the text."""
    brace = text.rfind("{")
    if brace < 0:
        return text, None, None, False
    tail = text[brace + 1 :]
    msg_id: str | None = None
    reply: str | None = None
    if _ID.match(tail):
        msg_id = tail
    elif reply_ack and "}" in tail:
        mm, _, aa = tail.partition("}")
        if _ID.match(mm) and (aa == "" or _ID.match(aa)):
            msg_id, reply = mm, aa
    if msg_id is None:
        return text, None, None, True
    body = text[:brace]
    return body, msg_id, reply, "{" in body


def _split_message_id(text: str, ctx: Ctx, *, reply_ack: bool = True) -> tuple[str, str | None, str | None]:
    """:func:`_message_id_parts`, with ``brace-in-message-text`` for a stray ``{``. Bulletins,
    NWS bulletins and telemetry metadata take a message ID but not the reply-ack form."""
    body, msg_id, reply, stray = _message_id_parts(text, reply_ack=reply_ack)
    if stray:
        ctx.defect(C.BRACE_IN_MESSAGE_TEXT)
    return body, msg_id, reply


def _message(s: str, destination: str, ctx: Ctx) -> AprsData:
    if len(s) >= 11 and s[10] == ":":
        raw_addressee = s[1:10]
        body = s[11:]
    else:
        k = s.find(":", 1, 11)
        if k < 0 or k == 1:
            ctx.fail(C.INVALID_MESSAGE)
        ctx.defect(C.UNPADDED_ADDRESSEE)
        raw_addressee = s[1:k]
        body = s[k + 1 :]
    addressee = raw_addressee.rstrip(" ")
    if not addressee or not _util.is_printable_ascii(addressee):
        ctx.fail(C.INVALID_MESSAGE)
    if " " in addressee or ":" in addressee:
        ctx.defect(C.INVALID_ADDRESSEE_CHARACTERS)

    if body.startswith(("PARM.", "UNIT.", "EQNS.", "BITS.")):
        meta = _telemetry_metadata(addressee, body, ctx)
        if meta is not None:
            return meta
    m = _ACK.match(body)
    if m:
        kind, ident, reply, extra = m.groups()
        if extra is not None:
            ctx.defect(C.MESSAGE_ID_ON_ACK)
        if kind == "ack":
            return Ack(addressee, ident, reply)
        return Reject(addressee, ident, reply)
    if _BULLETIN.match(addressee):
        # BLN then a digit or an upper-case letter; anything else is an ordinary message
        if addressee[3].isalpha() and len(addressee) > 4:
            ctx.defect(C.LETTER_GROUP_BULLETIN)
        text, msg_id, _reply = _split_message_id(body, ctx, reply_ack=False)
        return Bulletin(addressee, ctx.text(text), msg_id)
    if addressee.startswith(("NWS-", "NWS_")):
        text, msg_id, _reply = _split_message_id(body, ctx, reply_ack=False)
        return NwsBulletin(addressee, ctx.text(text), msg_id)
    if body.startswith("?"):
        if "{" in body:
            ctx.info(C.INVALID_QUERY)
            text, msg_id, reply = _split_message_id(body, ctx)
            return Message(addressee, ctx.text(text), msg_id, reply)
        query = _directed_query(addressee, body, ctx)
        if query is not None:
            return query
    text, msg_id, reply = _split_message_id(body, ctx)
    return Message(addressee, ctx.text(text), msg_id, reply)


def _directed_query(addressee: str, body: str, ctx: Ctx) -> AprsData | None:
    rest = body[1:]
    qtype: str | None = None
    for known in _DIRECTED:
        if rest.startswith(known):
            qtype = known
            break
    if qtype is None:
        upper = rest.upper()
        if any(upper.startswith(k) for k in _DIRECTED):
            ctx.info(C.INVALID_QUERY)
            return None
        # a type the spec does not define is upper-case letters, then a space or the end
        m = re.match(r"[A-Z]+", rest)
        if not m or (len(rest) > m.end() and rest[m.end()] != " "):
            return None
        qtype = m.group()
    remainder = rest[len(qtype) :]
    if "{" in remainder:
        ctx.info(C.INVALID_QUERY)
        return None
    # spaces after the target are padding (APRSH pads it to 9), and one space before it is a
    # separator (vectors interpretations.md)
    target = remainder.rstrip(" ")
    if target.startswith(" "):
        target = target[1:]
    if not target:
        return DirectedQuery(addressee, qtype, None)
    if not _CALLSIGN.match(target):
        ctx.info(C.INVALID_QUERY)
        return None
    return DirectedQuery(addressee, qtype, target)


_COEFF = re.compile(r" *(-?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?) *\Z")


def _telemetry_metadata(addressee: str, body: str, ctx: Ctx) -> AprsData | None:
    """Telemetry metadata, or None (with an ``invalid-telemetry-metadata`` info) when its prefix
    and list are not well formed, so that it is read as a plain message.

    The structure is checked first, then a stray ``{`` (which stays in the list), then the text's
    encoding.
    """
    text, msg_id, _reply, stray = _message_id_parts(body, reply_ack=False)
    kind = text[:5]
    content = text[5:]
    if kind in ("PARM.", "UNIT."):
        if content.count(",") > 12:
            ctx.info(C.INVALID_TELEMETRY_METADATA)
            return None
        if stray:
            ctx.defect(C.BRACE_IN_MESSAGE_TEXT)
        # the whole list is UTF-8 or Latin-1, not each entry on its own
        values = tuple(ctx.text(content).split(","))
        if kind == "PARM.":
            return TelemetryNames(addressee, values, msg_id)
        return TelemetryUnits(addressee, values, msg_id)
    if kind == "EQNS.":
        stripped = content.rstrip(", ")
        items = stripped.split(",") if stripped else []
        numbers: list[float] = []
        texts: list[str] = []
        for item in items:
            m = _COEFF.match(item)
            value = _number(m.group(1)) if m else math.nan
            if m is None or not math.isfinite(value):
                # not a number, or too large for one (1e400)
                ctx.info(C.INVALID_TELEMETRY_METADATA)
                return None
            texts.append(m.group(1))
            numbers.append(value)
        if not numbers or len(numbers) > 15:
            ctx.info(C.INVALID_TELEMETRY_METADATA)
            return None
        # (a stray { is in a coefficient, which is then not a number)
        return TelemetryCoefficients(addressee, tuple(numbers), msg_id, tuple(texts))
    # BITS.
    bits = content[:8]
    if len(bits) != 8 or any(b not in "01" for b in bits) or (content[8:9] not in ("", ",")):
        ctx.info(C.INVALID_TELEMETRY_METADATA)
        return None
    if stray:
        ctx.defect(C.BRACE_IN_MESSAGE_TEXT)
    project = ctx.text(content[9:])
    return TelemetryBits(addressee, bits, project, msg_id)


def _number(text: str) -> float:
    if re.fullmatch(r"-?[0-9]+", text):
        return int(text)
    return float(text)


# ------------------------------------------------------------------ status

_BEAM = re.compile(r"\^([0-9A-Z])([1-9:;<=>?@A-K])\Z")
"""A beam heading at the very end of status text: a heading code and an ERP code (APRS12c ch. 16,
whose ERP codes run 1-9, ``:`` to ``@``, A-K: there is no 0)."""


def _status(s: str, destination: str, ctx: Ctx) -> AprsData:
    body = s[1:]
    timestamp: Timestamp | None = None
    if len(body) >= 7 and body[:6].isdigit() and body[:6].isascii() and body[6] == "z":
        timestamp = Timestamp(body[:7])
        if not timestamp.is_valid:
            ctx.defect(C.INVALID_TIMESTAMP)
        body = body[7:]
    locator: str | None = None
    symbol: Symbol | None = None
    if timestamp is None:
        grid = _status_locator(body)
        if grid is not None:
            locator, symbol, consumed = grid
            body = body[consumed:]
            if body and body[0] != " ":
                ctx.defect(C.MISSING_SPACE_AFTER_LOCATOR)
            elif body:
                body = body[1:]
    beam: Beam | None = None
    m = _BEAM.search(body)
    if m:
        beam = Beam(m.group(1), m.group(2))
        # the text before it is kept as sent, spaces included
        body = body[: m.start()]
    return StatusReport(ctx.text(body), timestamp, locator, symbol, beam)


def _status_locator(body: str) -> tuple[str, Symbol, int] | None:
    if len(body) >= 6 and _util.is_locator6(body[:6]):
        if len(body) >= 8 and _util.is_symbol_table(body[6]) and _util.is_symbol_code(body[7]):
            return body[:6].upper(), Symbol(body[6], body[7]), 8
        return None
    if (
        len(body) >= 6
        and _util.is_locator4(body[:4])
        and _util.is_symbol_table(body[4])
        and _util.is_symbol_code(body[5])
    ):
        return body[:4].upper(), Symbol(body[4], body[5]), 6
    return None


# ------------------------------------------------------------------ telemetry

_TELEMETRY_NUMBER = re.compile(r"-?(?:[0-9]+\.?[0-9]*|\.[0-9]+)\Z")
"""A telemetry value: an optional ``-``, then digits with an optional decimal point. No ``+``, and
no spaces (vectors interpretations.md, "Numbers in telemetry")."""


def _telemetry(s: str, destination: str, ctx: Ctx) -> AprsData:
    if not s.startswith("T#"):
        ctx.fail(C.INVALID_TELEMETRY)
    rest = s[2:]
    if rest.startswith("MIC"):
        sequence = "MIC"
        rest = rest[3:]
        if rest.startswith(","):
            rest = rest[1:]
    else:
        comma = rest.find(",")
        if comma <= 0:
            ctx.fail(C.INVALID_TELEMETRY)
        sequence = rest[:comma]
        if not (sequence.isascii() and sequence.isalnum()):
            ctx.fail(C.INVALID_TELEMETRY)
        rest = rest[comma + 1 :]
    parts = rest.split(",", 5)
    analog: list[float | None] = []
    texts: list[str] = []
    for part in parts[:5]:
        if part == "":
            analog.append(None)
            texts.append("")
            continue
        m = _TELEMETRY_NUMBER.match(part)
        if not m:
            ctx.fail(C.INVALID_TELEMETRY)
        analog.append(_number(part))
        texts.append(part)
    bits: str | None = None
    comment = ""
    if len(parts) == 6 and len(parts[5]) >= 8 and all(b in "01" for b in parts[5][:8]):
        bits = parts[5][:8]
        comment = ctx.text(parts[5][8:])
    else:
        ctx.defect(C.INVALID_TELEMETRY)
        if len(parts) == 6:
            comment = ctx.text(parts[5])
    return TelemetryReport(sequence, tuple(analog), bits, comment, tuple(texts))


# ------------------------------------------------------------------ weather


def _positionless_weather(s: str, destination: str, ctx: Ctx) -> AprsData:
    ctx.info(C.OBSOLETE_FORMAT)
    ts = s[1:9]
    if len(ts) != 8 or not (ts.isdigit() and ts.isascii()):
        ctx.fail(C.INVALID_TIMESTAMP)
    timestamp = Timestamp(ts)
    if not timestamp.is_valid:
        ctx.defect(C.INVALID_TIMESTAMP)
    result = parse_weather_fields(s[9:], positionless=True, wind_known=False)
    raise_field_defects(result, ctx, positionless=True)
    text = weather_tail(result.text, ctx, result.values)
    return PositionlessWeather(timestamp, Weather(**result.values), ctx.text(text))


def _raw_weather(s: str, fmt: RawWeatherFormat, start: int, ctx: Ctx) -> AprsData:
    ctx.info(C.OBSOLETE_FORMAT)
    data = s[start:]
    if not _util.is_printable_ascii(data):
        ctx.fail(C.INVALID_WEATHER)
    return RawWeather(fmt, data)


def _peet_hash(s: str, destination: str, ctx: Ctx) -> AprsData:
    return _raw_weather(s, RawWeatherFormat.PEET_BROS_HASH, 1, ctx)


def _peet_star(s: str, destination: str, ctx: Ctx) -> AprsData:
    return _raw_weather(s, RawWeatherFormat.PEET_BROS_STAR, 1, ctx)


# ------------------------------------------------------------------ NMEA

_NMEA_ADDRESS = re.compile(r"(?:[A-Z0-9]{5}|P[A-Z0-9]{3,}),")
"""An NMEA 0183 address field and the comma after it: five upper-case letters or digits (a
talker and a sentence formatter, or a query), or ``P`` and a manufacturer's code."""
_NMEA_CHECKSUM = re.compile(r"\*[0-9A-Fa-f]{2}")


def _dollar(s: str, destination: str, ctx: Ctx) -> AprsData:
    """Raw NMEA (``$``): it must be an NMEA 0183 sentence (vectors interpretations.md, "What $
    text is an NMEA sentence"). The sentence ends at its first ``*`` and two hex digits; any text
    after that is the comment."""
    if s.startswith("$ULTW"):
        return _raw_weather(s, RawWeatherFormat.ULTIMETER_PACKET, 5, ctx)
    ctx.info(C.OBSOLETE_FORMAT)
    text = s[1:]
    star = text.find("*")
    comment = ""
    if star < 0:
        sentence = body = text
    elif _NMEA_CHECKSUM.match(text, star):
        sentence = text[: star + 3]
        body = text[:star]
        comment = text[star + 3 :]
    else:
        # a * that starts no checksum is a reserved character in a field
        ctx.fail(C.INVALID_NMEA)
    # the structure is read before the checksum
    if not _util.is_printable_ascii(sentence) or not _NMEA_ADDRESS.match(body) or "$" in body:
        ctx.fail(C.INVALID_NMEA)
    has_checksum = star >= 0
    if has_checksum:
        got = 0
        for ch in body:
            got ^= ord(ch)
        if got != int(sentence[-2:], 16):
            ctx.fail(C.NMEA_CHECKSUM_MISMATCH)
    fields = body.split(",")
    address = fields[0]
    # only an approved address has a sentence formatter: a proprietary one (P...) is not read
    kind = address[2:] if len(address) == 5 and not address.startswith("P") else ""
    values: dict[str, Any] = {}

    def field(i: int) -> str:
        return fields[i] if i < len(fields) else ""

    if kind == "GGA":
        _nmea_time(field(1), values)
        _nmea_position(field(2), field(3), field(4), field(5), values)
        quality = field(6)
        if len(quality) == 1 and "0" <= quality <= "9":
            values["fix"] = NmeaFix.INVALID if quality == "0" else NmeaFix.VALID
        _nmea_float(field(9), "altitude_m", values)
    elif kind == "RMC":
        _nmea_time(field(1), values)
        _nmea_status(field(2), values)
        _nmea_position(field(3), field(4), field(5), field(6), values)
        _nmea_float(field(7), "speed_knots", values)
        _nmea_float(field(8), "course_degrees", values)
    elif kind == "GLL":
        _nmea_position(field(1), field(2), field(3), field(4), values)
        _nmea_time(field(5), values)
        _nmea_status(field(6), values)
    elif kind == "VTG":
        _nmea_float(field(1), "course_degrees", values)
        _nmea_float(field(5), "speed_knots", values)
    elif kind == "WPL":
        _nmea_position(field(1), field(2), field(3), field(4), values)
        if field(5):
            values["waypoint"] = field(5)
    return NmeaSentence(sentence, has_checksum, comment=ctx.text(comment), **values)


_DECIMAL = re.compile(r"-?(?:[0-9]+\.?[0-9]*|\.[0-9]+)\Z")
_NMEA_TIME = re.compile(r"([0-9]{2})([0-9]{2})([0-9]{2})(\.[0-9]*)?\Z")
_NMEA_COORDINATE = re.compile(r"([0-9]+)([0-9]{2}(?:\.[0-9]*)?)\Z")


def _nmea_float(text: str, key: str, values: dict[str, Any]) -> None:
    if _DECIMAL.match(text):
        values[key] = float(text)


def _nmea_status(text: str, values: dict[str, Any]) -> None:
    """RMC's or GLL's status: ``A`` valid, ``V`` invalid, anything else says nothing."""
    if text == "A":
        values["fix"] = NmeaFix.VALID
    elif text == "V":
        values["fix"] = NmeaFix.INVALID


def _nmea_time(text: str, values: dict[str, Any]) -> None:
    """``hhmmss`` with an optional fraction, kept as sent less trailing zeros."""
    m = _NMEA_TIME.match(text)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59 or int(m.group(3)) > 59:
        return
    frac = (m.group(4) or "").rstrip("0").rstrip(".")
    values["time"] = f"{m.group(1)}:{m.group(2)}:{m.group(3)}{frac}"


def _nmea_coordinate(text: str, hemisphere: str, positive: str, negative: str, limit: int) -> float | None:
    """Degrees then two minute digits, with an optional fraction: however many degree digits
    there are, but at least one; minutes below 60; at most ``limit`` degrees."""
    m = _NMEA_COORDINATE.match(text)
    if not m or hemisphere not in (positive, negative):
        return None
    minutes = float(m.group(2))
    if minutes >= 60:
        return None
    value = int(m.group(1)) + minutes / 60
    if value > limit:
        return None
    return -value if hemisphere == negative else value


def _nmea_position(lat: str, ns: str, lon: str, ew: str, values: dict[str, Any]) -> None:
    """A position needs both coordinates."""
    latitude = _nmea_coordinate(lat, ns, "N", "S", 90)
    longitude = _nmea_coordinate(lon, ew, "E", "W", 180)
    if latitude is not None and longitude is not None:
        values["latitude"] = latitude
        values["longitude"] = longitude


# ------------------------------------------------------------------ the rest


def _has_control(text: str) -> bool:
    """Whether ``text`` holds a control character: below U+0020, or U+007F."""
    return any(c < " " or c == "\x7f" for c in text)


def _capabilities(s: str, destination: str, ctx: Ctx) -> AprsData:
    # the whole text is UTF-8 or Latin-1, not each item on its own (vectors README)
    body = ctx.text(s[1:])
    # only U+0020 is padding: a CR at the edge of an item stays in it
    items = [item.strip(" ") for item in body.split(",")]
    items = [item for item in items if item]
    if not items:
        ctx.fail(C.INVALID_CAPABILITIES)
    caps: list[tuple[str, ...]] = []
    free = False
    for item in items:
        token, eq, value = item.partition("=")
        token = token.strip(" ")
        value = value.strip(" ")
        if not token or " " in token or _has_control(token) or _has_control(value):
            free = True
        caps.append((token, value) if eq else (token,))
    ctx.flush_text()
    if free:
        ctx.defect(C.FREE_TEXT_CAPABILITIES)
    return Capabilities(tuple(caps))


_FOOTPRINT = re.compile(r" ?(-?\d+(?:\.\d+)?),(-? ?\d+(?:\.\d+)?),(\d{4})\Z")


def _query(s: str, destination: str, ctx: Ctx) -> AprsData:
    end = s.find("?", 1)
    if end <= 1:
        ctx.fail(C.INVALID_GENERAL_QUERY)
    qtype = s[1:end]
    if not re.fullmatch(r"[A-Z]+", qtype):
        ctx.fail(C.INVALID_GENERAL_QUERY)
    rest = s[end + 1 :]
    footprint: Footprint | None = None
    if rest:
        m = _FOOTPRINT.match(rest)
        if not m:
            ctx.fail(C.INVALID_GENERAL_QUERY)
        footprint = Footprint(float(m.group(1)), float(m.group(2).replace(" ", "")), int(m.group(3)))
        if abs(footprint.latitude) > 90 or abs(footprint.longitude) > 180:
            # no such place: dropping the footprint would make the query one to every station
            ctx.fail(C.INVALID_GENERAL_QUERY)
    return Query(qtype, footprint)


def _maidenhead(s: str, destination: str, ctx: Ctx) -> AprsData:
    ctx.info(C.OBSOLETE_FORMAT)
    end = s.find("]")
    loc = s[1:end] if end > 0 else ""
    if end < 0 or not _util.is_locator(loc):
        ctx.fail(C.INVALID_LOCATOR)
    return MaidenheadBeacon(loc.upper(), ctx.text(s[end + 1 :]))


def _user_defined(s: str, destination: str, ctx: Ctx) -> AprsData:
    if len(s) < 3:
        ctx.fail(C.INVALID_USER_DEFINED)
    return UserDefined(s[1], s[2], s[3:])


def _test(s: str, destination: str, ctx: Ctx) -> AprsData:
    return TestData(ctx.text(s[1:]))


def _agrelo(s: str, destination: str, ctx: Ctx) -> AprsData:
    m = re.fullmatch(r"%([0-9]{3})/([0-9])", s)
    if not m or int(m.group(1)) > 360:
        # a bearing is a direction, 000 to 360 (vectors interpretations.md)
        ctx.fail(C.INVALID_AGRELO_DF)
    return AgreloDf(int(m.group(1)), int(m.group(2)))


def _reserved(s: str, destination: str, ctx: Ctx) -> AprsData:
    ctx.info(C.RESERVED_DATA_TYPE)
    return Unrecognized(UnrecognizedReason.RESERVED_DATA_TYPE)


def _third_party(s: str, destination: str, ctx: Ctx) -> AprsData:
    body = s[1:]
    colon = body.find(":")
    if colon < 0:
        ctx.fail(C.INVALID_THIRD_PARTY)
    header = body[:colon]
    if not header.isascii():
        ctx.fail(C.INVALID_THIRD_PARTY)
    # a defect the inner header may tolerate is the inner packet's warning (vectors README)
    inner = Ctx(ctx.options)
    try:
        source, dest, path = parse_tnc2_header(header, inner, third_party=True)
    except RejectedError:
        ctx.fail(C.INVALID_THIRD_PARTY)
    info = body[colon + 1 :].encode("latin-1")
    data = decode_info(info, dest, inner)
    return ThirdParty(Packet(source, dest, path, info, data, tuple(inner.diags)))


_HANDLERS = {
    "!": _position,
    "=": _position,
    "/": _position,
    "@": _position,
    ";": _object,
    ")": _item,
    ":": _message,
    ">": _status,
    "<": _capabilities,
    "?": _query,
    "T": _telemetry,
    "_": _positionless_weather,
    "#": _peet_hash,
    "*": _peet_star,
    "$": _dollar,
    "`": _mic_e,
    "'": _mic_e,
    "\x1c": _mic_e,
    "\x1d": _mic_e,
    "[": _maidenhead,
    "{": _user_defined,
    "}": _third_party,
    ",": _test,
    "%": _agrelo,
    "&": _reserved,
    "+": _reserved,
    ".": _reserved,
}

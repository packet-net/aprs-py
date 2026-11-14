"""The conformance vectors' neutral data form: plain dicts and lists, JSON-ready.

The rules (from the vectors' README) make absence meaningful: ``None``, empty strings and empty
lists are left out (except ``reply_ack``, where ``""`` says the sender supports reply-acks),
booleans are written only when true, enumerations are kebab-case strings, timestamps and
symbols are written as on air.

>>> from pdn_aprs import decode_tnc2
>>> from pdn_aprs._neutral import to_neutral
>>> to_neutral(decode_tnc2("N0CALL>APZ001:>Net Control Center").data)
{'type': 'status', 'text': 'Net Control Center'}
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from .diagnostics import Diagnostic
from .errors import AprsError, EncodeError, RefusalCode
from .model import (
    Ack,
    AgreloDf,
    AprsData,
    AreaColor,
    AreaObject,
    AreaShape,
    Beam,
    Bulletin,
    Capabilities,
    CommentTelemetry,
    CompressionFix,
    CompressionOrigin,
    CompressionSource,
    CompressionType,
    Dao,
    DaoPrecision,
    DfBearing,
    Dfs,
    DirectedQuery,
    Footprint,
    ItemReport,
    MaidenheadBeacon,
    Message,
    MicEMessage,
    MicEReport,
    NmeaFix,
    NmeaSentence,
    NwsBulletin,
    ObjectReport,
    Phg,
    PositionlessWeather,
    PositionReport,
    Query,
    RawWeather,
    RawWeatherFormat,
    Reject,
    StatusReport,
    Storm,
    StormType,
    TelemetryBits,
    TelemetryCoefficients,
    TelemetryNames,
    TelemetryReport,
    TelemetryUnits,
    TestData,
    ThirdParty,
    Timestamp,
    ToneType,
    Unrecognized,
    UnrecognizedReason,
    UserDefined,
    VoiceFrequency,
    Weather,
    WeatherExtra,
)
from .packet import Packet, PathEntry
from .symbols import Symbol

__all__ = [
    "NeutralFormError",
    "from_neutral",
    "header_to_neutral",
    "packet_to_neutral",
    "to_neutral",
]


class NeutralFormError(AprsError):
    """The neutral form holds something the data model cannot."""


_SKIP = frozenset({"analog_text", "coefficients_text", "latitude_text", "longitude_text", "altitude_in_comment"})
_KEEP_EMPTY = frozenset({"reply_ack"})
_OMIT_ZERO = frozenset({"ambiguity", "destination_ssid"})

TYPES: dict[str, type[AprsData]] = {
    cls.kind: cls
    for cls in (
        PositionReport,
        MicEReport,
        ObjectReport,
        ItemReport,
        Message,
        Ack,
        Reject,
        Bulletin,
        NwsBulletin,
        TelemetryNames,
        TelemetryUnits,
        TelemetryCoefficients,
        TelemetryBits,
        DirectedQuery,
        StatusReport,
        TelemetryReport,
        PositionlessWeather,
        RawWeather,
        NmeaSentence,
        MaidenheadBeacon,
        Query,
        Capabilities,
        ThirdParty,
        UserDefined,
        TestData,
        AgreloDf,
        Unrecognized,
    )
}


def _value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (Symbol, Timestamp)):
        return str(value)
    if isinstance(value, Packet):
        return packet_to_neutral(value, inner=True)
    if is_dataclass(value) and not isinstance(value, type):
        return _object(value)
    if isinstance(value, tuple):
        return [_value(v) for v in value]
    return value


def _object(obj: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in fields(obj):
        name = f.name
        if name in _SKIP:
            continue
        value = getattr(obj, name)
        if value is None or value is False:
            continue
        if value == "" and name not in _KEEP_EMPTY:
            continue
        if isinstance(value, tuple) and not value:
            continue
        if name in _OMIT_ZERO and value == 0:
            continue
        out[name] = _value(value)
    return out


def to_neutral(data: AprsData) -> dict[str, Any]:
    """Decoded data in the neutral form, with its ``type``.

    A chain of third-party packets is walked in a loop, so one built by a caller thousands deep
    does not exhaust the stack."""
    if not isinstance(data, ThirdParty):
        out: dict[str, Any] = {"type": data.kind}
        out.update(_object(data))
        return out
    top: dict[str, Any] = {"type": data.kind}
    target = top
    current: AprsData = data
    while isinstance(current, ThirdParty):
        packet = current.packet
        inner: dict[str, Any] = {"source": packet.source, "destination": packet.destination}
        if packet.path:
            inner["path"] = [str(p) for p in packet.path]
        target["packet"] = inner
        if isinstance(packet.data, ThirdParty):
            nested: dict[str, Any] = {"type": packet.data.kind}
            inner["data"] = nested
            target = nested
        else:
            inner["data"] = to_neutral(packet.data)
        if packet.diagnostics:
            inner["diagnostics"] = [str(d) for d in packet.diagnostics]
        current = packet.data
    return top


def header_to_neutral(packet: Packet) -> dict[str, Any]:
    """The header in the neutral form: ``source``, ``destination``, ``path``, ``q_construct``."""
    out: dict[str, Any] = {"source": packet.source, "destination": packet.destination}
    if packet.path:
        out["path"] = [str(p) for p in packet.path]
    q = packet.q_construct
    if q is not None:
        out["q_construct"] = {"construct": q.construct}
        if q.station is not None:
            out["q_construct"]["station"] = q.station
    return out


def packet_to_neutral(packet: Packet, *, inner: bool = False) -> dict[str, Any]:
    """A packet as the vectors' differential dump writes it (``header``, ``data``,
    ``diagnostics``), or with ``inner`` as a third-party packet's ``packet``."""
    diagnostics = [str(d) for d in packet.diagnostics]
    if inner:
        out: dict[str, Any] = {"source": packet.source, "destination": packet.destination}
        if packet.path:
            out["path"] = [str(p) for p in packet.path]
        out["data"] = to_neutral(packet.data)
        if diagnostics:
            out["diagnostics"] = diagnostics
        return out
    return {
        "header": header_to_neutral(packet),
        "data": to_neutral(packet.data),
        "diagnostics": diagnostics,
    }


# ---------------------------------------------------------------- back again


def _compression(d: dict[str, Any]) -> CompressionType:
    return CompressionType(
        CompressionFix(d.get("fix", "current")),
        CompressionSource(d.get("source", "other")),
        CompressionOrigin(d.get("origin", "software")),
    )


def _weather(d: dict[str, Any]) -> Weather:
    values = dict(d)
    if "extra" in values:
        values["extra"] = tuple(WeatherExtra(e["letter"], e["value"]) for e in values["extra"])
    return Weather(**values)


def _frequency(d: dict[str, Any]) -> VoiceFrequency:
    values = dict(d)
    if "tone" in values:
        values["tone"] = ToneType(values["tone"])
    return VoiceFrequency(**values)


def _area(d: dict[str, Any]) -> AreaObject:
    values = dict(d)
    values["shape"] = AreaShape(values["shape"])
    values["color"] = AreaColor(values["color"])
    return AreaObject(**values)


def _storm(d: dict[str, Any]) -> Storm:
    values = dict(d)
    values["type"] = StormType(values["type"])
    return Storm(**values)


def _comment_telemetry(d: dict[str, Any]) -> CommentTelemetry:
    return CommentTelemetry(d["sequence"], tuple(d.get("analog", ())), d.get("digital"))


def _packet(d: dict[str, Any]) -> Packet:
    path = tuple(PathEntry(p.rstrip("*"), p.endswith("*")) for p in d.get("path", ()))
    diagnostics = tuple(Diagnostic.parse(x) for x in d.get("diagnostics", ()))
    # a header's source and destination are always written, even when empty; one left out is empty
    source, destination = d.get("source", ""), d.get("destination", "")
    return Packet(source, destination, path, b"", _from_neutral(d["data"]), diagnostics, third_party=True)


_CONVERT: dict[str, Any] = {
    "symbol": Symbol.parse,
    "timestamp": Timestamp,
    "compression": _compression,
    "phg": lambda d: Phg(**d),
    "dfs": lambda d: Dfs(**d),
    "area": _area,
    "df_bearing": lambda d: DfBearing(**d),
    "storm": _storm,
    "dao": lambda d: Dao(d["datum"], DaoPrecision(d["precision"])),
    "frequency": _frequency,
    "weather": _weather,
    "mic_e_message": MicEMessage,
    "format": RawWeatherFormat,
    "reason": UnrecognizedReason,
    "beam": lambda d: Beam(**d),
    "footprint": lambda d: Footprint(**d),
    "packet": _packet,
    "capabilities": lambda caps: tuple(tuple(c) for c in caps),
    "names": tuple,
    "units": tuple,
    "coefficients": tuple,
    "analog": tuple,
    "legacy_telemetry": tuple,
}


def from_neutral(data: dict[str, Any]) -> AprsData:
    """Data from the neutral form (the inverse of :func:`to_neutral`).

    Third-party packets nest at most four deep: the input's depth is counted in a loop before
    anything recurses, and a deeper chain raises :class:`EncodeError`
    (``invalid-third-party-header``), as the encoder refuses it."""
    depth = 0
    node: Any = data
    while isinstance(node, dict) and node.get("type") == "third-party":
        depth += 1
        if depth > 4:
            raise EncodeError("third-party packets nest at most 4 deep", RefusalCode.INVALID_THIRD_PARTY_HEADER)
        packet = node.get("packet")
        node = packet.get("data") if isinstance(packet, dict) else None
    return _from_neutral(data)


def _from_neutral(data: dict[str, Any]) -> AprsData:
    kind = data["type"]
    try:
        cls = TYPES[kind]
    except KeyError:
        raise ValueError(f"unknown data type {kind!r}") from None
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        if key == "type":
            continue
        if key == "telemetry" and kind != "telemetry":
            kwargs[key] = _comment_telemetry(value)
        elif key == "fix" and kind == "nmea":
            kwargs[key] = NmeaFix(value)
        elif key in _CONVERT:
            kwargs[key] = _CONVERT[key](value)
        else:
            kwargs[key] = value
    # text the neutral form leaves out is empty text, which the encoder refuses as such
    # (vectors interpretations.md, "Absent text is empty text")
    if cls in (Query, DirectedQuery) and "query_type" not in kwargs:
        kwargs["query_type"] = ""
    if cls in (ObjectReport, ItemReport) and "name" not in kwargs:
        kwargs["name"] = ""
    if cls in (PositionReport, MicEReport, ObjectReport, ItemReport) and "symbol" not in kwargs:
        kwargs["symbol"] = Symbol.parse("x-")  # an unknown table: invalid-symbol
    if "addressee" in cls.__dataclass_fields__ and "addressee" not in kwargs:
        kwargs["addressee"] = ""
    if cls in (Message, Bulletin, NwsBulletin) and "text" not in kwargs:
        # empty text is left out of the neutral form
        kwargs["text"] = ""
    try:
        return cls(**kwargs)
    except TypeError as e:
        raise NeutralFormError(f"{kind}: {e}") from None


def _refusal_for_unrepresentable(data: dict[str, Any]) -> RefusalCode | None:
    """The refusal an encoder gives data this library's data model cannot hold, or None.

    An ack or a reject has no message ID of its own, so one given is a field the report has no
    place for (``field-not-allowed``); the data's other faults are judged without it, and a code
    that comes before ``field-not-allowed`` in the vectors' order wins.
    """
    from .encode import _PRIORITY, encode_info

    kind = data.get("type")
    if kind not in ("ack", "reject") or "message_id" not in data:
        return None
    rest = {k: v for k, v in data.items() if k != "message_id"}
    try:
        encode_info(from_neutral(rest))
    except EncodeError as e:
        if _PRIORITY[e.code] < _PRIORITY[RefusalCode.FIELD_NOT_ALLOWED]:
            return e.code
    except (NeutralFormError, ValueError, KeyError, TypeError):
        return None
    return RefusalCode.FIELD_NOT_ALLOWED

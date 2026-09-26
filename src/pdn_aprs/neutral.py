"""The conformance vectors' neutral data form: plain dicts and lists, JSON-ready.

The rules (from the vectors' README) make absence meaningful: ``None``, empty strings and empty
lists are left out (except ``reply_ack``, where ``""`` says the sender supports reply-acks),
booleans are written only when true, enumerations are kebab-case strings, timestamps and
symbols are written as on air.

>>> from pdn_aprs import decode
>>> from pdn_aprs.neutral import to_neutral
>>> to_neutral(decode("N0CALL>APZ001:>Net Control Center").data)
{'type': 'status', 'text': 'Net Control Center'}
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from .diagnostics import Diagnostic
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
    CompressionOrigin,
    CompressionType,
    Dao,
    DaoPrecision,
    DfBearing,
    Dfs,
    DirectedQuery,
    Fix,
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

__all__ = ["NeutralFormError", "from_neutral", "header_to_neutral", "packet_to_neutral", "to_neutral"]


class NeutralFormError(ValueError):
    """The neutral form holds something the data model cannot."""


_SKIP = frozenset({"analog_text", "coefficients_text"})
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
    """Decoded data in the neutral form, with its ``type``."""
    out: dict[str, Any] = {"type": data.kind}
    out.update(_object(data))
    return out


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
        Fix(d.get("fix", "current")),
        NmeaSource(d.get("source", "other")),
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
    return Packet(d["source"], d["destination"], path, b"", from_neutral(d["data"]), diagnostics)


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
    """Data from the neutral form (the inverse of :func:`to_neutral`)."""
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
    if cls is Message and "text" not in kwargs:
        kwargs["text"] = ""
    try:
        return cls(**kwargs)
    except TypeError as e:
        raise NeutralFormError(f"{kind}: {e}") from None

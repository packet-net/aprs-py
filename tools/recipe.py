"""Building a packet from a conformance-vectors builder recipe, through the library's own builder.

Shared by the differential dump tool (``diff_dump.py --build``) and the conformance test runner
(``tests/conformance.py``, for the vectors' ``build`` cases), so both call the builder the same way.
A recipe is ``{"station": {...}, "report": "...", "args": {...}}`` (the vectors' README, "Build
records"); only the keys it gives are passed, so the library's own defaults are what is built.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from pdn_aprs import (
    Beam,
    CommentTelemetry,
    MicEMessage,
    Packet,
    Phg,
    Station,
    Symbol,
    Timestamp,
    ToneType,
    VoiceFrequency,
)


class UnsupportedError(Exception):
    """The builder has no way to say something a recipe asks for."""


def _timestamp(stamp: dict[str, Any], *, positionless: bool = False) -> datetime | Timestamp:
    """A recipe's time: the datetime itself where the builder makes the report's format from it
    (day/hour/minute, or a positionless weather report's month/day/hour/minute), and otherwise
    the timestamp in the format asked for."""
    # fromisoformat takes a trailing Z only from Python 3.11
    moment = datetime.fromisoformat(stamp["utc"].replace("Z", "+00:00"))
    form = stamp.get("format")
    if form == "hms":
        return Timestamp.hms(moment.hour, moment.minute, moment.second)
    if form == "dhm":
        return Timestamp.dhm(moment.day, moment.hour, moment.minute) if positionless else moment
    if form == "mdhm":
        return moment if positionless else Timestamp.mdhm(moment.month, moment.day, moment.hour, moment.minute)
    raise UnsupportedError(f"timestamp: the builder has no format {form!r}")


def _frequency(f: dict[str, Any]) -> VoiceFrequency:
    for key in f:
        if key not in ("mhz", "tone", "tone_value", "offset_khz"):
            raise UnsupportedError(f"frequency: the builder has no {key}")
    tone = f.get("tone")
    return VoiceFrequency(
        f["mhz"],
        tone=None if tone is None else ToneType(tone),
        tone_value=f.get("tone_value"),
        offset_khz=f.get("offset_khz"),
    )


def _same(value: Any) -> Any:
    return value


# The keyword each positioned recipe key goes to a Station method as, and its conversion.
_POSITIONED: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "name": ("name", _same),
    "latitude": ("latitude", _same),
    "longitude": ("longitude", _same),
    "symbol": ("symbol", Symbol.parse),
    "comment": ("comment", _same),
    "killed": ("killed", _same),
    "timestamp": ("timestamp", _timestamp),
    "course_degrees": ("course_degrees", _same),
    "speed_knots": ("speed_knots", _same),
    "speed_kmh": ("speed_kmh", _same),
    "altitude_feet": ("altitude_feet", _same),
    "altitude_m": ("altitude_m", _same),
    "phg": ("phg", lambda d: Phg(**d)),
    "range_miles": ("range_miles", _same),
    "frequency": ("frequency", _frequency),
    "compressed": ("compressed", _same),
    "ambiguity": ("ambiguity", _same),
    "dao": ("dao", _same),
    "telemetry": ("telemetry", lambda t: CommentTelemetry(t["sequence"], tuple(t["analog"]), t.get("digital"))),
    "mic_e_message": ("mic_e_message", MicEMessage),
}

_UNITS = {"course_degrees", "speed_knots", "speed_kmh", "altitude_feet", "altitude_m"}
_EXTRAS = {"phg", "range_miles", "frequency", "compressed", "ambiguity", "dao", "telemetry"}

# The recipe keys each Station method takes.
_TAKES: dict[str, set[str]] = {
    "position": {
        "latitude",
        "longitude",
        "symbol",
        "comment",
        "timestamp",
        *_UNITS,
        "phg",
        "range_miles",
        "frequency",
        "compressed",
        "ambiguity",
        "dao",
        "telemetry",
    },
    "object": {
        "name",
        "latitude",
        "longitude",
        "symbol",
        "comment",
        "killed",
        "timestamp",
        *_UNITS,
        *_EXTRAS,
    },
    "item": {"name", "latitude", "longitude", "symbol", "comment", "killed", *_UNITS, *_EXTRAS},
    "mic-e": {
        "latitude",
        "longitude",
        "symbol",
        "mic_e_message",
        "comment",
        *_UNITS,
        "frequency",
        "ambiguity",
        "dao",
        "telemetry",
    },
    "weather": {
        "latitude",
        "longitude",
        "symbol",
        "timestamp",
        "wind_direction_degrees",
        "wind_speed_mph",
        "wind_gust_mph",
        "temperature_f",
        "temperature_c",
        "rain_1h_in",
        "rain_24h_in",
        "rain_midnight_in",
        "rain_1h_mm",
        "rain_24h_mm",
        "rain_midnight_mm",
        "humidity_percent",
        "pressure_mbar",
        "luminosity_w_m2",
        "snow_24h_in",
    },
    "message": {"addressee", "text", "message_id", "reply_ack"},
    "ack": {"addressee", "message_id"},
    "reject": {"addressee", "message_id"},
    "bulletin": {"id", "group", "text"},
    "status": {"text", "timestamp", "locator", "symbol", "beam"},
    "telemetry": {"sequence", "analog", "bits", "comment"},
    "telemetry-names": {"names", "addressee"},
    "telemetry-units": {"units", "addressee"},
    "telemetry-coefficients": {"coefficients", "addressee"},
    "telemetry-bits": {"bits", "project", "addressee"},
}

# The recipe keys that go to Station.weather by the same name.
_WEATHER = {
    "latitude",
    "longitude",
    "wind_direction_degrees",
    "wind_speed_mph",
    "wind_gust_mph",
    "temperature_f",
    "temperature_c",
    "rain_1h_in",
    "rain_24h_in",
    "rain_midnight_in",
    "rain_1h_mm",
    "rain_24h_mm",
    "rain_midnight_mm",
    "humidity_percent",
    "pressure_mbar",
    "luminosity_w_m2",
    "snow_24h_in",
}


def build(recipe: dict[str, Any]) -> Packet:
    """The packet a recipe describes, from the Station methods, as a program would build it."""
    header = recipe["station"]
    report = recipe["report"]
    args = dict(recipe.get("args", {}))
    for key in header:
        if key not in ("source", "destination", "path"):
            raise UnsupportedError(f"station: the builder has no {key}")
    # a station says whether it can message, which position and Mic-E reports announce; only what
    # the recipe gives is passed, so the Station's own defaults are what is built
    station_args: dict[str, Any] = {}
    if "path" in header:
        station_args["path"] = header["path"]
    if "destination" in header:
        station_args["destination"] = header["destination"]
    if report in ("position", "mic-e") and "messaging" in args:
        station_args["messaging"] = bool(args.pop("messaging"))
    station = Station(header["source"], **station_args)
    takes = _TAKES.get(report)
    if takes is None:
        raise UnsupportedError(f"the builder has no {report} report")
    for key in args:
        if key not in takes:
            raise UnsupportedError(f"{report}: the builder has no {key}")

    if report in ("position", "object", "item", "mic-e"):
        kwargs = {}
        for key, value in args.items():
            name, convert = _POSITIONED[key]
            kwargs[name] = convert(value)
        if report == "position":
            return station.position(**kwargs)
        if report == "object":
            return station.object(**kwargs)
        if report == "item":
            return station.item(**kwargs)
        return station.mic_e(**kwargs)
    if report == "weather":
        weather = {key: value for key, value in args.items() if key in _WEATHER}
        if "symbol" in args:
            if "latitude" not in args:
                raise UnsupportedError("weather: a positionless report has no symbol")
            weather["symbol"] = Symbol.parse(args["symbol"])
        if "timestamp" in args:
            weather["timestamp"] = _timestamp(args["timestamp"], positionless="latitude" not in args)
        return station.weather(**weather)
    if report == "message":
        return station.message(
            args["addressee"], args.get("text", ""), message_id=args.get("message_id"), reply_ack=args.get("reply_ack")
        )
    if report == "ack":
        return station.ack(args["addressee"], args["message_id"])
    if report == "reject":
        return station.reject(args["addressee"], args["message_id"])
    if report == "bulletin":
        return station.bulletin(args["id"], args.get("text", ""), group=args.get("group", ""))
    if report == "status":
        return station.status(
            args.get("text", ""),
            timestamp=_timestamp(args["timestamp"]) if "timestamp" in args else None,
            locator=args.get("locator"),
            symbol=Symbol.parse(args["symbol"]) if "symbol" in args else None,
            beam=Beam(**args["beam"]) if "beam" in args else None,
        )
    if report == "telemetry":
        given = {key: args[key] for key in ("sequence", "analog", "bits", "comment") if key in args}
        return station.telemetry(**given)
    if report == "telemetry-names":
        return station.telemetry_names(args["names"], addressee=args.get("addressee"))
    if report == "telemetry-units":
        return station.telemetry_units(args["units"], addressee=args.get("addressee"))
    if report == "telemetry-coefficients":
        return station.telemetry_coefficients(args["coefficients"], addressee=args.get("addressee"))
    return station.telemetry_bits(args["bits"], args.get("project", ""), addressee=args.get("addressee"))

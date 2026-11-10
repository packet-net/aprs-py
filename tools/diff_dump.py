#!/usr/bin/env python3
"""Differential dump: run every line of an input through the library and write what was made of
it, in the form the conformance vectors' ``tools/compare.py`` reads (the vectors' README,
"Comparing implementations").

  python3 tools/diff_dump.py lines.hex.gz py.jsonl.gz [--jobs N] [--limit N]
  python3 tools/diff_dump.py --encode data.jsonl.gz py.jsonl.gz
  python3 tools/diff_dump.py --build recipes.jsonl.gz py.jsonl.gz

Decode (the default) reads one hex-encoded TNC2 line per line (packet.net's ``aprs-corpus diff
lines`` or the vectors' ``tools/mutate.py`` writes it) and writes

  {"n": 0, "lenient": R, "strict": R, "reencode": "identical|equivalent|refused|fails|none",
   "written": "hex", "written_destination": "...", "api": A}

where R is ``{"header", "data", "diagnostics"}`` in the vectors' neutral form, or
``{"header_error": [...]}``; ``reencode`` says how the lenient data encodes again, ``written`` is
the information field it wrote (whenever it wrote one) and ``written_destination`` the Mic-E
destination it computed; ``api`` is what the library's public API says about the lenient packet.

Encode (``--encode``) reads ``{"n", "data", "exact"}`` lines of neutral data (the vectors'
``tools/generate.py``), encodes each and writes ``{"n", "result", "info", "destination",
"again"}``, or a ``reason`` when the result is ``refused`` or ``unsupported``.

Build (``--build``) reads builder recipes (``tools/generate.py --recipes``), calls the
``Station`` methods as a program would and writes ``{"n", "result", "tnc2", "again"}``, or a
``reason``; a recipe key the builder cannot express is ``unsupported``, and the reason names it.

The work is spread over processes; the output keeps the input's order.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from multiprocessing import Pool
from typing import Any

from pdn_aprs import (
    CommentTelemetry,
    EncodeError,
    HeaderError,
    MicEMessage,
    MicEReport,
    Packet,
    ParseOptions,
    Phg,
    Station,
    Symbol,
    ThirdParty,
    Timestamp,
    ToneType,
    Unrecognized,
    VoiceFrequency,
    decode_tnc2,
)
from pdn_aprs.encode import DEFAULT_DESTINATION, encode_info, mic_e_destination
from pdn_aprs.neutral import NeutralFormError, from_neutral, packet_to_neutral, to_neutral

LENIENT = ParseOptions.lenient()
STRICT = ParseOptions.strict()


def _number_equal(a: float, b: float) -> bool:
    scale = max(abs(a), abs(b))
    return abs(a - b) <= 1e-9 * (scale if scale >= 1 else 1)


def same(a: Any, b: Any) -> bool:
    """Equal by the vectors' rules: exact keys, numbers within 1e-9."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _number_equal(a, b)
    return bool(a == b)


def dumps(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def crash(n: int, e: Exception) -> str:
    """A crash is a bug: it is recorded, so that the comparison shows it."""
    print(f"line {n}: {type(e).__name__}: {e}", file=sys.stderr)
    return dumps({"n": n, "result": "crash", "reason": f"{type(e).__name__}: {e}"})


# ---------------------------------------------------------------- decode


def result(line: bytes, options: ParseOptions) -> tuple[dict[str, Any], Packet | None]:
    try:
        packet = decode_tnc2(line, options)
    except HeaderError as e:
        return {"header_error": [str(d) for d in e.diagnostics]}, None
    return packet_to_neutral(packet), packet


def reencode(packet: Packet | None) -> tuple[str, dict[str, str]]:
    """How the lenient data encodes again, and what it wrote. The bytes written are decoded again
    under a well-formed header (for Mic-E, the destination the encoder computed), so that a defect
    in the original header, an empty destination say, is not counted against the encoder."""
    if packet is None or isinstance(packet.data, Unrecognized):
        return "none", {}
    data = packet.data
    try:
        info = encode_info(data)
        destination = mic_e_destination(data) if isinstance(data, MicEReport) else DEFAULT_DESTINATION
    except EncodeError:
        return "refused", {}
    written = {"written": info.hex()}
    if isinstance(data, MicEReport):
        written["written_destination"] = destination
    same_destination = not isinstance(data, MicEReport) or destination == packet.destination
    if info == packet.info.rstrip(b"\r\n") and same_destination:
        return "identical", written
    try:
        again = decode_tnc2(f"{packet.source}>{destination}".encode("ascii") + b":" + info, LENIENT)
    except HeaderError:
        return "fails", written
    if any(d.severity.value != "info" for d in again.diagnostics):
        return "fails", written
    return ("equivalent" if same(to_neutral(data), to_neutral(again.data)) else "fails"), written


def api_view(packet: Packet) -> dict[str, Any]:
    """What the library's public API says about a packet (the vectors' README, "The API view"),
    read through its accessors as a program would, not through the neutral form."""
    q = packet.q_construct
    view: dict[str, Any] = {
        "source": packet.source,
        "destination": packet.destination,
        "path": [str(entry) for entry in packet.path],
        "q_construct": None,
        "third_party": packet.third_party,
        "has_errors": bool(packet.errors),
        "has_warnings": bool(packet.warnings),
        "tnc2": packet.to_tnc2().hex(),
    }
    if q is not None:
        view["q_construct"] = {"construct": q.construct}
        if q.station is not None:
            view["q_construct"]["station"] = q.station
    try:
        view["ax25"] = packet.to_ax25().hex()
    except EncodeError:
        view["ax25"] = "refused"
    device = packet.device
    view["device"] = None
    if device is not None:
        found = (("vendor", device.vendor), ("model", device.model), ("class", device.device_class))
        view["device"] = {key: value for key, value in found if value}
    data = packet.data
    symbol = getattr(data, "symbol", None)
    if isinstance(symbol, Symbol) and symbol.description is not None:
        view["symbol"] = {"description": symbol.description}
    phg = getattr(data, "phg", None)
    if isinstance(phg, Phg):
        view["phg"] = {
            "watts": phg.power_watts,
            "height_feet": phg.height_feet,
            "gain_db": phg.gain_dbi,
            "directivity_degrees": phg.directivity_degrees,
        }
    if isinstance(data, ThirdParty):
        view["inner"] = api_view(data.packet)
    return view


def dump_line(n: int, hex_line: str) -> str:
    line = bytes.fromhex(hex_line)
    try:
        lenient, packet = result(line, LENIENT)
        strict, _ = result(line, STRICT)
        how, written = reencode(packet)
        api = None if packet is None else api_view(packet)
    except Exception as e:  # a crash is a bug: record it so the comparison shows it
        print(f"line {n}: {type(e).__name__}: {e}", file=sys.stderr)
        failed = {"header_error": [f"error:crash-{type(e).__name__}"]}
        return json.dumps({"n": n, "lenient": failed, "strict": failed, "reencode": "none"})
    record: dict[str, Any] = {"n": n, "lenient": lenient, "strict": strict, "reencode": how, **written}
    if api is not None:
        record["api"] = api
    return dumps(record)


# ---------------------------------------------------------------- encode


def encode_line(n: int, text: str) -> str:
    item = json.loads(text)
    n = item.get("n", n)
    try:
        try:
            data = from_neutral(item["data"])
        except (NeutralFormError, ValueError, KeyError, TypeError) as e:
            # this library's data cannot hold something in the neutral data
            return dumps({"n": n, "result": "unsupported", "reason": f"{type(e).__name__}: {e}"})
        try:
            info = encode_info(data)
            destination = mic_e_destination(data) if isinstance(data, MicEReport) else DEFAULT_DESTINATION
        except EncodeError as e:
            return dumps({"n": n, "result": "refused", "reason": str(e)})
        try:
            packet = decode_tnc2(f"N0CALL>{destination}".encode("ascii") + b":" + info, LENIENT)
            again: dict[str, Any] = {
                "data": to_neutral(packet.data),
                "diagnostics": [str(d) for d in packet.diagnostics],
            }
        except HeaderError as e:
            again = {"header_error": [str(d) for d in e.diagnostics]}
    except Exception as e:
        return crash(n, e)
    return dumps({"n": n, "result": "written", "info": info.hex(), "destination": destination, "again": again})


# ---------------------------------------------------------------- build


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
    "course_degrees": ("course", _same),
    "speed_knots": ("speed", _same),
    "speed_kmh": ("speed_kmh", _same),
    "altitude_feet": ("altitude", _same),
    "altitude_m": ("altitude_m", _same),
    "phg": ("phg", lambda d: Phg(**d)),
    "range_miles": ("range_miles", _same),
    "frequency": ("frequency", _frequency),
    "compressed": ("compressed", _same),
    "ambiguity": ("ambiguity", _same),
    "dao": ("precise", _same),
    "telemetry": ("telemetry", lambda t: CommentTelemetry(t["sequence"], tuple(t["analog"]), t.get("digital"))),
    "mic_e_message": ("message", MicEMessage),
}

_UNITS = {"course_degrees", "speed_knots", "speed_kmh", "altitude_feet", "altitude_m"}

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
    "object": {"name", "latitude", "longitude", "symbol", "comment", "killed", "timestamp", *_UNITS, "frequency"},
    "item": {"name", "latitude", "longitude", "symbol", "comment", "killed"},
    "mic-e": {"latitude", "longitude", "symbol", "mic_e_message", "comment", *_UNITS},
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
    "status": {"text", "timestamp", "locator", "symbol"},
    "telemetry": {"sequence", "analog", "bits", "comment"},
    "telemetry-names": {"names", "addressee"},
    "telemetry-units": {"units", "addressee"},
    "telemetry-coefficients": {"coefficients", "addressee"},
    "telemetry-bits": {"bits", "project", "addressee"},
}

# The keyword each weather recipe key goes to Station.weather as.
_WEATHER = {
    "latitude": "latitude",
    "longitude": "longitude",
    "wind_direction_degrees": "wind_direction",
    "wind_speed_mph": "wind_speed",
    "wind_gust_mph": "gust",
    "temperature_f": "temperature",
    "temperature_c": "temperature_c",
    "rain_1h_in": "rain_1h",
    "rain_24h_in": "rain_24h",
    "rain_midnight_in": "rain_since_midnight",
    "rain_1h_mm": "rain_1h_mm",
    "rain_24h_mm": "rain_24h_mm",
    "rain_midnight_mm": "rain_since_midnight_mm",
    "humidity_percent": "humidity",
    "pressure_mbar": "pressure",
    "luminosity_w_m2": "luminosity",
    "snow_24h_in": "snow_24h",
}


def build(recipe: dict[str, Any]) -> Packet:
    """The packet a recipe describes, from the Station methods, as a program would build it."""
    header = recipe["station"]
    report = recipe["report"]
    args = dict(recipe.get("args", {}))
    for key in header:
        if key not in ("source", "destination", "path"):
            raise UnsupportedError(f"station: the builder has no {key}")
    # a station says whether it can message, which position and Mic-E reports announce
    messaging = args.pop("messaging", False) if report in ("position", "mic-e") else False
    station = Station(
        header["source"],
        via=header.get("path", ()),
        destination=header.get("destination", DEFAULT_DESTINATION),
        messaging=bool(messaging),
    )
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
        if args.get("symbol", "/_") != "/_":
            raise UnsupportedError(f"weather: the builder has no symbol {args['symbol']!r}, only /_")
        weather = {_WEATHER[key]: value for key, value in args.items() if key in _WEATHER}
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
        )
    if report == "telemetry":
        return station.telemetry(
            args["sequence"], args["analog"], args.get("bits", "00000000"), comment=args.get("comment", "")
        )
    if report == "telemetry-names":
        return station.telemetry_names(args["names"], station=args.get("addressee"))
    if report == "telemetry-units":
        return station.telemetry_units(args["units"], station=args.get("addressee"))
    if report == "telemetry-coefficients":
        return station.telemetry_coefficients(args["coefficients"], station=args.get("addressee"))
    return station.telemetry_bits(args["bits"], args.get("project", ""), station=args.get("addressee"))


def build_line(n: int, text: str) -> str:
    recipe = json.loads(text)
    n = recipe.get("n", n)
    try:
        try:
            packet = build(recipe)
        except UnsupportedError as e:
            return dumps({"n": n, "result": "unsupported", "reason": str(e)})
        except (EncodeError, ValueError) as e:
            # the builder or the encoder declined
            return dumps({"n": n, "result": "refused", "reason": str(e)})
        line = packet.to_tnc2()
        try:
            again = packet_to_neutral(decode_tnc2(line, LENIENT))
        except HeaderError as e:
            again = {"header_error": [str(d) for d in e.diagnostics]}
    except Exception as e:
        return crash(n, e)
    return dumps({"n": n, "result": "built", "tnc2": line.hex(), "again": again})


# ---------------------------------------------------------------- driving it

MODES: dict[str, Callable[[int, str], str]] = {"decode": dump_line, "encode": encode_line, "build": build_line}


def dump_chunk(chunk: tuple[str, int, list[str]]) -> list[str]:
    mode, start, lines = chunk
    work = MODES[mode]
    return [work(start + i, line) for i, line in enumerate(lines)]


def chunks(mode: str, path: str, size: int, limit: int | None) -> Iterator[tuple[str, int, list[str]]]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        batch: list[str] = []
        start = 0
        for n, raw in enumerate(f):
            if limit is not None and n >= limit:
                break
            batch.append(raw.strip())
            if len(batch) == size:
                yield mode, start, batch
                start += size
                batch = []
        if batch:
            yield mode, start, batch


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("input", help="hex TNC2 lines, or with --encode neutral data, or with --build recipes")
    ap.add_argument("out")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--encode", action="store_true", help="encode neutral data (the vectors' tools/generate.py)")
    mode.add_argument("--build", action="store_true", help="build packets from recipes (generate.py --recipes)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--chunk", type=int, default=5000)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    which = "encode" if args.encode else "build" if args.build else "decode"

    started = time.monotonic()
    count = 0
    with gzip.open(args.out, "wt", encoding="utf-8", compresslevel=3) as out, Pool(args.jobs) as pool:
        for records in pool.imap(dump_chunk, chunks(which, args.input, args.chunk, args.limit), chunksize=1):
            out.write("\n".join(records))
            out.write("\n")
            count += len(records)
            if count % 500_000 < args.chunk:
                rate = count / (time.monotonic() - started)
                print(f"{count:,} lines, {rate:,.0f}/s", file=sys.stderr)
    print(f"{count:,} lines in {time.monotonic() - started:,.0f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

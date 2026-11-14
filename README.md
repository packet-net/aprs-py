# pdn-aprs

[![CI](https://github.com/packet-net/aprs-py/actions/workflows/ci.yml/badge.svg)](https://github.com/packet-net/aprs-py/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pdn-aprs)](https://pypi.org/project/pdn-aprs/)

An APRS (Automatic Packet Reporting System) decoder and encoder for Python, checked against the language-neutral conformance vectors in [packet-net/aprs-vectors](https://github.com/packet-net/aprs-vectors).

Conforms to [aprs-vectors](https://github.com/packet-net/aprs-vectors) 1.2: every case passes.

- Decodes TNC2 / APRS-IS lines (`str` or `bytes`), AX.25 UI frames and KISS frames, into a packet with its header, the raw information field, the decoded data and diagnostics.
- Every data type in the APRS 1.2 specification: positions (plain, compressed, with timestamps, weather, DF, storms, area objects), Mic-E, objects, items, messages, acks, bulletins, telemetry and its metadata, status, queries, capabilities, NMEA, raw weather, third-party, user-defined.
- Lenient by default, strict on request, and every tolerable defect can be accepted or rejected on its own.
- An encoder for every type that writes only what the specification allows, and a `Station` builder for the packets an application typically sends.
- Every symbol by name, and device identification from the [aprs-deviceid](https://github.com/aprsorg/aprs-deviceid) database.
- Pure Python 3.10+, no dependencies, fully typed.

It is one of six independent implementations that cross-check each other: C# ([packet-net/aprs-cs](https://github.com/packet-net/aprs-cs)), Rust ([packet-net/aprs-rs](https://github.com/packet-net/aprs-rs)), Go ([packet-net/aprs-go](https://github.com/packet-net/aprs-go)), TypeScript ([packet-net/aprs-ts](https://github.com/packet-net/aprs-ts)) and C ([packet-net/aprs-c](https://github.com/packet-net/aprs-c)) pass the same vectors. The C# and Rust ones also agree with this one on every packet of a 6.9-million-packet APRS-IS capture.

## Install

```sh
pip install pdn-aprs
```

The import name is `pdn_aprs`.

## Decoding

```python
>>> import pdn_aprs as aprs
>>> packet = aprs.decode_tnc2("M0LTE-9>APDR16,WIDE1-1,qAR,M0LTE-10:=5127.00N/00058.80W>088/036/A=000123Mobile")
>>> packet.source, packet.destination, packet.q_construct
('M0LTE-9', 'APDR16', QConstruct(construct='qAR', station='M0LTE-10'))
>>> packet.data
PositionReport(latitude=51.45, longitude=-0.98, symbol=Symbol('/>'), course_degrees=88, speed_knots=36, altitude_feet=123, comment='Mobile', messaging=True)
>>> packet.data.symbol.description
'Car'
>>> print(packet.device)
Open Source APRSdroid

```

Fields keep the units APRS sends, with the unit in the name (`speed_knots`, `altitude_feet`, `temperature_f`). `packet.data` is always there: when nothing could be decoded it is an `Unrecognized`, and the diagnostics say why.

```python
>>> packet = aprs.decode_tnc2("N0CALL>APZ001:@092345z4903.50N/07201.75W_220/004g005t-07r000p000P000h50b09900wRSW")
>>> weather = packet.data.weather
>>> weather.wind_direction_degrees, weather.wind_speed_mph, weather.temperature_f, weather.pressure_mbar
(220, 4, -7, 990)

```

Mic-E reports carry half their position in the destination address; the device that sent one is identified by its type code and suffix:

```python
>>> packet = aprs.decode_tnc2("N1JCM-9>TRQP7T,WA1PLE-4*:`c'wl|+>/`\"4-}_%")
>>> packet.data.latitude, packet.data.longitude, packet.data.mic_e_message
(42.179, -71.1985, <MicEMessage.OFF_DUTY: 'off-duty'>)
>>> print(packet.device)
Yaesu FTM-400DR

```

AX.25 frames (the KISS payload, without flags or FCS) and whole KISS frames decode too:

```python
>>> frame = bytes.fromhex("82A0B4606062E09A6098A88A40729A6098A88A40E2AE92888A64406303F03E68656C6C6F")
>>> print(aprs.decode_ax25(frame))
M0LTE-9>APZ001,M0LTE-1*,WIDE2-1:>hello

```

## Defects: lenient, strict, or in between

Real packets have defects. By default the decoder accepts every defect it can make sense of, with a warning; a strict decoder rejects the packet instead. Each defect has a code from the vectors' `codes.json`, and each tolerable one can be accepted or rejected on its own.

```python
>>> line = "N1EOE>APN391,N1NCI-3*,WIDE2-1:!4216.95n/07243.20w#phg6230/ Easthampton MA"
>>> packet = aprs.decode_tnc2(line)
>>> packet.data.latitude, [str(d) for d in packet.diagnostics]
(42.2825, ['warning:lowercase-hemisphere', 'warning:lowercase-hemisphere'])
>>> strict = aprs.decode_tnc2(line, aprs.ParseOptions.strict())
>>> strict.data, [str(d) for d in strict.diagnostics]
(Unrecognized(reason=<UnrecognizedReason.MALFORMED: 'malformed'>), ['error:lowercase-hemisphere'])
>>> options = aprs.ParseOptions.lenient().without(aprs.DiagnosticCode.LOWERCASE_HEMISPHERE)
>>> aprs.decode_tnc2(line, options).data.kind
'unrecognized'

```

A header that cannot be read at all raises `HeaderError`, whose `diagnostics` say why.

## Building packets

A `Station` holds what stays the same from packet to packet, and has a method for each kind of packet an application typically sends. Each returns an encoded `Packet`: `str(packet)` is its TNC2 line, `packet.to_kiss()` its KISS frame.

```python
>>> from pdn_aprs import Station, Symbol
>>> m0lte = Station("M0LTE-9", path="WIDE1-1,WIDE2-1", symbol=Symbol.CAR, messaging=True)
>>> print(m0lte.position(51.45, -0.98, course_degrees=88, speed_knots=36, comment="Mobile"))
M0LTE-9>APZ001,WIDE1-1,WIDE2-1:=5127.00N/00058.80W>088/036Mobile
>>> print(m0lte.position(51.45, -0.98, compressed=True, frequency=aprs.VoiceFrequency(145.5, tone=aprs.ToneType.TONE, tone_value=77)))
M0LTE-9>APZ001,WIDE1-1,WIDE2-1:=/4M<<N7Jo> sT145.500MHz T077
>>> print(m0lte.mic_e(51.4575, -0.9811, speed_knots=12, course_degrees=94))
M0LTE-9>UQRWTU,WIDE1-1,WIDE2-1:`vVsm4z>/`
>>> print(m0lte.message("G4ABC", "See you at the club", message_id="42"))
M0LTE-9>APZ001,WIDE1-1,WIDE2-1::G4ABC    :See you at the club{42
>>> print(m0lte.ack("G4ABC", "7"))
M0LTE-9>APZ001,WIDE1-1,WIDE2-1::G4ABC    :ack7
>>> print(m0lte.object("LEADER", 49.0583, -72.0292, timestamp=aprs.Timestamp.dhm(9, 23, 45), course_degrees=88, speed_knots=36))
M0LTE-9>APZ001,WIDE1-1,WIDE2-1:;LEADER   *092345z4903.50N/07201.75W>088/036
>>> wx = Station("M0LTE-13")
>>> print(wx.weather(51.45, -0.98, wind_direction_degrees=220, wind_speed_mph=4, wind_gust_mph=5, temperature_f=58, humidity_percent=81, pressure_mbar=1013.2))
M0LTE-13>APZ001:!5127.00N/00058.80W_220/004g005t058h81b10132
>>> print(wx.telemetry(5, [199, 0, 255, 73, 123], "01101001"))
M0LTE-13>APZ001:T#005,199,000,255,073,123,01101001
>>> print(wx.telemetry_names(["Battery", "Temp"]))
M0LTE-13>APZ001::M0LTE-13 :PARM.Battery,Temp

```

The destination defaults to `APZ001`, the experimental tocall; give your application's own with `Station(..., destination="APxxxx")`. Quantities are in APRS's units: degrees, knots and feet, and for weather mph, degrees Fahrenheit, inches and millibars. Every keyword has the name of the data field it fills (`course_degrees`, `speed_knots`, `wind_gust_mph`...); a metric alternative changes only the unit (`speed_kmh`, `altitude_m`, `temperature_c`, `rain_1h_mm`). Position, object, item and Mic-E reports all take the same options where they apply: `compressed`, `ambiguity`, `phg`, `range_miles`, `frequency` (MHz, or a `VoiceFrequency` to give a tone or offset), `telemetry` and `dao` (a `!DAO!`), and a course, speed and altitude in APRS's or metric units. A request that cannot be sent (a telemetry sequence over 999, a quantity given in both units, no symbol anywhere) raises `EncodeError`, which is a `ValueError` and carries a reason code. `weather` takes any `symbol`, and `status` a meteor scatter `beam`.

What a builder writes for an input you leave out depends only on what you give it, never on the clock:

- No `timestamp`: an object or a positionless weather report is refused (`missing-field`); any other report has none. For the time now, pass it yourself: `timestamp=datetime.now(timezone.utc)` (`timestamp=True` is gone).
- A `Station` that is not said to message (`messaging=False`, the default) writes `!` or `/` for a position and the type code `'` for Mic-E. A Mic-E report with no `mic_e_message` is off duty.
- No symbol on a position, object, item or Mic-E report (and none on the `Station`) is refused (`invalid-symbol`); a weather report's is `/_`.
- A telemetry report with no sequence is refused (`missing-field`); with no `bits` it writes `00000000`, and with no `analog` five empty channels.
- No path, the destination `APZ001`, no ambiguity, no compression, no message ID, an object or item alive, telemetry metadata to the sending station, and a weather value left out written as unknown dots for `c`, `s`, `g` and `t`; Mic-E speed is 0.
- A Mic-E altitude, in feet or metres, goes in the Mic-E altitude bytes, rounded once to the nearest metre (1000 feet is 305 m); outside -10,000 to 743,570 m it is refused (`value-out-of-range`).

## Encoding

Any decoded or constructed data can be encoded. The encoder writes only what the specification allows and raises `EncodeError` otherwise. It checks free text by decoding what it wrote: a comment that would read back as something else gets a `/` delimiter, or is refused. An information field is at most 256 bytes (UTF-8, number text included; for a third-party packet the outermost field), and a longer one is refused as `too-long`. Text with a control character (a byte below 0x20 or 0x7F, a TAB or a line break included) is refused as `invalid-character`. Decoding has no size limit, and warns of a control character in text (`control-character-in-text`), so a strict decoder rejects it.

```python
>>> from pdn_aprs import PositionReport, encode_info
>>> report = PositionReport(latitude=49.0583333, longitude=-72.0291667, symbol=Symbol.HOUSE, comment="123/456")
>>> encode_info(report)
b'!4903.50N/07201.75W-/123/456'
>>> encode_info(PositionReport(latitude=49.0583333, longitude=-72.0291667, symbol=Symbol.HOUSE, comment="/A=001234"))
Traceback (most recent call last):
    ...
pdn_aprs.errors.EncodeError: the text '/A=001234' would not read back as written
>>> encode_info(aprs.Message("N0CALL", "x" * 68))
Traceback (most recent call last):
    ...
pdn_aprs.errors.EncodeError: message text is over 67 characters

```

### Why it refused

An `EncodeError` carries a `code`, a `RefusalCode` that says which rule the data broke, so a program can act on it without reading the message (which is for people and may change):

```python
>>> from pdn_aprs import RefusalCode
>>> try:
...     encode_info(aprs.Message("N0CALL", "x" * 68))
... except aprs.EncodeError as e:
...     print(e.code.value, e.code is RefusalCode.TOO_LONG)
too-long True

```

The values are the shared ids in the conformance vectors' `codes.json` under `refusals`, the same in all six implementations. A new code may be added in a later 1.x release, so keep a default for one you do not know. `does-not-read-back` is the fallback for the encoder's own read-back check when no rule names the cause; `to_ax25` refuses with `ax25-cannot-carry`.

`build_packet(source, data, destination=..., path=...)` gives a whole packet, and computes a Mic-E report's destination.

## Symbols

Every symbol the APRS symbol tables define is available by name, with its description; the names match Packet.Aprs's.

```python
>>> Symbol.CAR, Symbol.WEATHER_STATION, Symbol.DIGIPEATER
(Symbol('/>'), Symbol('/_'), Symbol('/#'))
>>> Symbol.OVERLAY_DIGIPEATER.with_overlay("S")
Symbol('S#')
>>> Symbol.parse("S#").description
'Digi (green star)'
>>> Symbol.from_name("fire truck")
Symbol('/f')

```

## Conformance

The vectors are a git submodule at `vectors/`, and `tests/test_vectors.py` runs every check their README defines for every case, one parametrised test per check with the case id as the test id: the lenient decoding, the strict one, the single-tolerance check, the re-encoding (byte for byte against the case's canonical bytes), and the encode cases. Every case passes. A check that should be skipped goes in `tests/known_differences.json` with its reason; there are none.

### The dump tool

`tools/diff_dump.py` runs a file of inputs through the library and writes what it made of each, as gzip-compressed JSON lines in the input's order, in the form the vectors' `tools/compare.py` reads (the vectors' README, "Comparing implementations"). It has the three modes that README describes:

```sh
python3 tools/diff_dump.py lines.hex.gz py.jsonl.gz                     # decode
python3 tools/diff_dump.py --encode data.jsonl.gz py-encode.jsonl.gz    # encode
python3 tools/diff_dump.py --build recipes.jsonl.gz py-build.jsonl.gz   # build
python3 vectors/tools/compare.py py.jsonl.gz ts.jsonl.gz --names py ts --input lines.hex.gz
```

- **Decode** (the default) reads one hex-encoded TNC2 line per line (the vectors' `tools/mutate.py` writes them). Each record holds the lenient and strict results in the neutral form, how the lenient data encodes again (`reencode`), the information field the encoder wrote (`written`, hex) and for Mic-E the destination it computed (`written_destination`), and `api`: what the public API says about the packet (source, destination, path, q-construct, whether it came from inside a third-party packet, `has_errors` and `has_warnings`, the TNC2 and AX.25 forms, the device, the symbol's description and what the PHG codes stand for, and the same for a third-party packet's inner packet).
- **Encode** (`--encode`) reads neutral data from the vectors' `tools/generate.py`, encodes it with `encode_info` and writes the bytes, the destination and what they decode to, or `refused` with the encoder's reason.
- **Build** (`--build`) reads builder recipes (`generate.py --recipes`) and calls the `Station` methods as a program would, passing only the keys a recipe gives, so that the builder's own defaults are what is written, and writing the TNC2 line and what it decodes to, or `refused`. A recipe key the `Station` methods do not take is `unsupported`, and the reason names it. This library has no fixed capacity, so it never writes `implementation-limit`.

The work is spread over processes: `--jobs N` (all cores by default) and `--chunk N` lines at a time (5,000); `--limit N` stops after N lines. A 6.9-million-line capture takes about two minutes to decode.

On the 6,879,893-packet APRS-IS capture the C# and Rust implementations were compared on, this one agrees with both on every packet: lenient and strict decoding and re-encoding.

## Development

```sh
git clone --recurse-submodules https://github.com/packet-net/aprs-py
cd aprs-py
python3 -m venv .venv && . .venv/bin/activate
pip install -e . pytest mypy ruff
pytest                # the vectors, the unit tests and this README's examples
ruff check . && ruff format --check .
mypy
```

`tools/generate_devices.py` regenerates the device database from an aprs-deviceid checkout.

## Licence

MIT; see [LICENSE](LICENSE). The device identification data comes from the aprs-deviceid database, under CC BY-SA 2.0; see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

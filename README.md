# pdn-aprs

[![CI](https://github.com/packet-net/aprs-py/actions/workflows/ci.yml/badge.svg)](https://github.com/packet-net/aprs-py/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pdn-aprs)](https://pypi.org/project/pdn-aprs/)

An APRS (Automatic Packet Reporting System) decoder and encoder for Python, checked against the language-neutral conformance vectors in [packet-net/aprs-vectors](https://github.com/packet-net/aprs-vectors).

- Decodes TNC2 / APRS-IS lines (`str` or `bytes`), AX.25 UI frames and KISS frames, into a packet with its header, the raw information field, the decoded data and diagnostics.
- Every data type in the APRS 1.2 specification: positions (plain, compressed, with timestamps, weather, DF, storms, area objects), Mic-E, objects, items, messages, acks, bulletins, telemetry and its metadata, status, queries, capabilities, NMEA, raw weather, third-party, user-defined.
- Lenient by default, strict on request, and every tolerable defect can be accepted or rejected on its own.
- An encoder for every type that writes only what the specification allows, and a `Station` builder for the packets an application typically sends.
- Every symbol by name, and device identification from the [aprs-deviceid](https://github.com/aprsorg/aprs-deviceid) database.
- Pure Python 3.10+, no dependencies, fully typed.

It is one of several independent implementations that cross-check each other: Packet.Aprs (C#, in [packet-net/packet.net](https://github.com/packet-net/packet.net)) and pdn-aprs for Rust ([packet-net/aprs-rs](https://github.com/packet-net/aprs-rs)) pass the same vectors and agree with this one on every packet of a 6.9-million-packet APRS-IS capture.

## Install

```sh
pip install pdn-aprs
```

The import name is `pdn_aprs`.

## Decoding

```python
>>> import pdn_aprs as aprs
>>> packet = aprs.decode("M0LTE-9>APDR16,WIDE1-1,qAR,M0LTE-10:=5127.00N/00058.80W>088/036/A=000123Mobile")
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
>>> packet = aprs.decode("N0CALL>APZ001:@092345z4903.50N/07201.75W_220/004g005t-07r000p000P000h50b09900wRSW")
>>> weather = packet.data.weather
>>> weather.wind_direction_degrees, weather.wind_speed_mph, weather.temperature_f, weather.pressure_mbar
(220, 4, -7, 990)

```

Mic-E reports carry half their position in the destination address; the device that sent one is identified by its type code and suffix:

```python
>>> packet = aprs.decode("N1JCM-9>TRQP7T,WA1PLE-4*:`c'wl|+>/`\"4-}_%")
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
>>> packet = aprs.decode(line)
>>> packet.data.latitude, [str(d) for d in packet.diagnostics]
(42.2825, ['warning:lowercase-hemisphere', 'warning:lowercase-hemisphere'])
>>> strict = aprs.decode(line, aprs.ParseOptions.strict())
>>> strict.data, [str(d) for d in strict.diagnostics]
(Unrecognized(reason=<UnrecognizedReason.MALFORMED: 'malformed'>), ['error:lowercase-hemisphere'])
>>> options = aprs.ParseOptions.lenient().without(aprs.DiagnosticCode.LOWERCASE_HEMISPHERE)
>>> aprs.decode(line, options).data.kind
'unrecognized'

```

A header that cannot be read at all raises `HeaderError`, whose `diagnostics` say why.

## Building packets

A `Station` holds what stays the same from packet to packet, and has a method for each kind of packet an application typically sends. Each returns an encoded `Packet`: `str(packet)` is its TNC2 line, `packet.to_kiss()` its KISS frame.

```python
>>> from pdn_aprs import Station, Symbol
>>> m0lte = Station("M0LTE-9", via="WIDE1-1,WIDE2-1", symbol=Symbol.CAR, messaging=True)
>>> print(m0lte.position(51.45, -0.98, course=88, speed=36, comment="Mobile"))
M0LTE-9>APZ001,WIDE1-1,WIDE2-1:=5127.00N/00058.80W>088/036Mobile
>>> print(m0lte.position(51.45, -0.98, compressed=True, frequency=145.5, tone=77))
M0LTE-9>APZ001,WIDE1-1,WIDE2-1:=/4M<<N7Jo> sT145.500MHz T077
>>> print(m0lte.mic_e(51.4575, -0.9811, speed=12, course=94))
M0LTE-9>U1RWTU,WIDE1-1,WIDE2-1:`vVsm4z>/`
>>> print(m0lte.message("G4ABC", "See you at the club", message_id="42"))
M0LTE-9>APZ001,WIDE1-1,WIDE2-1::G4ABC    :See you at the club{42
>>> print(m0lte.ack("G4ABC", "7"))
M0LTE-9>APZ001,WIDE1-1,WIDE2-1::G4ABC    :ack7
>>> print(m0lte.object("LEADER", 49.0583, -72.0292, timestamp=aprs.Timestamp.dhm(9, 23, 45), course=88, speed=36))
M0LTE-9>APZ001,WIDE1-1,WIDE2-1:;LEADER   *092345z4903.50N/07201.75W>088/036
>>> wx = Station("M0LTE-13")
>>> print(wx.weather(51.45, -0.98, wind_direction=220, wind_speed=4, gust=5, temperature=58, humidity=81, pressure=1013.2))
M0LTE-13>APZ001:!5127.00N/00058.80W_220/004g005t058h81b10132
>>> print(wx.telemetry(5, [199, 0, 255, 73, 123], "01101001"))
M0LTE-13>APZ001:T#005,199,000,255,073,123,01101001
>>> print(wx.telemetry_names(["Battery", "Temp"]))
M0LTE-13>APZ001::M0LTE-13 :PARM.Battery,Temp

```

The destination defaults to `APZ001`, the experimental tocall; give your application's own with `Station(..., destination="APxxxx")`. Quantities are in APRS's units: degrees, knots and feet, and for weather mph, degrees Fahrenheit, inches and millibars.

## Encoding

Any decoded or constructed data can be encoded. The encoder writes only what the specification allows and raises `EncodeError` otherwise. It checks free text by decoding what it wrote: a comment that would read back as something else gets a `/` delimiter, or is refused.

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

## The neutral form

`pdn_aprs.neutral` converts data to and from the conformance vectors' neutral form: plain dicts and lists, ready for JSON.

```python
>>> from pdn_aprs.neutral import to_neutral
>>> to_neutral(aprs.decode("N0CALL>APZ001::WU2Z     :Testing{003").data)
{'type': 'message', 'addressee': 'WU2Z', 'text': 'Testing', 'message_id': '003'}

```

## Conformance

The vectors are a git submodule at `vectors/`, and `tests/test_vectors.py` runs every check their README defines for every case, one parametrised test per check with the case id as the test id: the lenient decoding, the strict one, the single-tolerance check, the re-encoding, and the encode cases. All 5,987 checks pass. A check that should be skipped goes in `tests/known_differences.json` with its reason; there are none.

`tools/diff_dump.py` decodes a whole capture and writes the JSONL that the vectors' `tools/compare.py` reads, spread over all cores (a 6.9-million-line capture takes about two minutes):

```sh
python3 tools/diff_dump.py lines.hex.gz py.jsonl.gz
python3 vectors/tools/compare.py py.jsonl.gz rs.jsonl.gz --names Python Rust --lines lines.hex.gz
```

On the 6,879,893-packet APRS-IS capture the other implementations were compared on, this one agrees with both on every packet: lenient and strict decoding and re-encoding.

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

AGPL-3.0-or-later; see [LICENSE](LICENSE). The device identification data comes from the aprs-deviceid database, under CC BY-SA 2.0; see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

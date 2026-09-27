# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

## [0.1.1]

### Changed

- Mic-E Rev 0 binary telemetry (0x1D and five bytes after the symbol) is read into `legacy_telemetry`, with an `obsolete-format` info, and written back; it was left in the comment and refused on encoding. A value of 255 is refused. The ruling is shared by all five implementations (packet-net/aprs-vectors, "Mic-E Rev 0 binary telemetry").

## [0.1.0]

First release.

### Added

- Decoding of TNC2 / APRS-IS lines, AX.25 UI frames and KISS frames into a `Packet`: source, destination, path with used flags, q-construct, the raw information field, the decoded data and diagnostics.
- Every APRS data type the conformance vectors cover: positions (plain and compressed, with timestamps, data extensions, weather, DF bearings, storm data, area objects, signposts, `!DAO!`, base-91 telemetry, voice frequencies), Mic-E, objects, items, messages, acks and rejects with reply-acks, bulletins, NWS bulletins, telemetry and its metadata, directed and general queries, status reports, station capabilities, positionless and raw weather, NMEA, Maidenhead beacons, third-party packets, user-defined and test data, Agrelo DF.
- `ParseOptions`: lenient (the default), strict, or any tolerable defect accepted or rejected on its own. Diagnostics use the vectors' codes.
- An encoder for every data type (`encode_info`, `build_packet`, `mic_e_destination`) that writes only what the spec allows and raises `EncodeError` otherwise, checking free text by decoding what it wrote.
- `Station`, a builder for the packets an application typically sends, and `Packet.to_ax25()` and `Packet.to_kiss()`.
- `Symbol`, with every defined symbol by name and description, and an overlay helper.
- Device identification from the aprs-deviceid database (commit 845e3f8, 2026-09-18).
- `pdn_aprs.neutral`: the conformance vectors' neutral data form.
- The aprs-vectors conformance suite as a submodule: all 5,594 checks pass.
- `tools/diff_dump.py`, the differential dump the vectors' `tools/compare.py` reads. On the 6,879,893-packet APRS-IS capture it agrees with aprs-rs and Packet.Aprs on every packet.

[Unreleased]: https://github.com/packet-net/aprs-py/compare/v0.1.0...HEAD [0.1.0]: https://github.com/packet-net/aprs-py/releases/tag/v0.1.0

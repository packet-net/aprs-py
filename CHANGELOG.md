# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

Brought into line with the rulings from five rounds of differential fuzzing of all five implementations (packet-net/aprs-vectors: 153 new cases, and new rules in its README and interpretations.md). All 5,999 of the vectors' checks pass.

### Added

- `NmeaSentence.comment`: text sent after the checksum (TinyTrack sends one), kept as sent, and written back after the checksum.
- `Packet.third_party`: true for the packet inside a third-party packet. Its `q_construct` is now always None, since a q-construct is only read in the outer header and a third-party path is kept as sent; it used to report one found in the inner path.

### Changed

- NMEA: text after `$` must be an NMEA 0183 sentence, or it is `invalid-nmea`: printable ASCII, an address of five upper-case letters or digits (or `P` and three or more of them), then at least one field. The sentence ends at its first `*` and two hex digits, and the checksum is verified; a `*` that starts no checksum is `invalid-nmea`. The structure is checked before the checksum. Only GGA, GLL, RMC, VTG and WPL from a five-character address that does not start `P` are read. A coordinate needs a degree digit, minutes below 60 and a value in range, and a position needs both; the time must be exactly `hhmmss` in range; `fix` needs a status of `A` or `V`, or a one-digit GGA quality.
- Mic-E: the 0x1C and 0x1D data type identifiers get an `obsolete-format` info, before anything else is checked. A destination whose ambiguity centres its latitude past 90 degrees (`90LLLL`) is `invalid-mic-e-destination`, and the encoder refuses an ambiguous position at 90 or 180 degrees. A PHG straight after the type code is read before an altitude is looked for later in the text, so `0PH}` in `PHG3330PH}` is not an altitude.
- Positions: the latitude alone sets the ambiguity. A longitude place it blanks may hold a digit or a space; a space anywhere else is `invalid-longitude`.
- `!DAO!`: a digit datum is only read with spaces for A and O, and a DAO is five bytes as sent, never joined across removed telemetry or a Mic-E altitude. The precision it adds stays south or west of 0 degrees: a Mic-E latitude of 0 degrees south with a DAO is now negative.
- Only `\l` is an area object and only `\m` a signpost; with an overlay, `l` and `m` are ordinary symbols. A signpost is the first braces holding 1-3 printable ASCII characters that are not braces, wherever they are; braces that do not qualify stay in the comment and do not stop the search. Base-91 comment telemetry's `digital` is the eight binary channels, 0-255.
- Weather: the wind is judged where the `DDD/SSS` extension belongs, before any field, so missing wind, or wind sent as fields, is reported first. When the wind comes as fields, `s` is the wind speed until the speed is known, wherever it comes. A repeated extra field letter no longer ends the fields. `s.` and `s..` are an unknown snowfall with a width warning, but a snowfall value that holds a digit is a number of three characters (`s.50`), so `s.5h` is not a field.
- Station capabilities: a control character in a token or a value makes the report free text, only spaces are trimmed, and the whole text is read as UTF-8 or Latin-1, not each item on its own. Telemetry names and units are read as one text in the same way.
- Messages: an addressee is a bulletin only when `BLN` is followed by a digit or an upper-case letter. Bulletins, NWS bulletins and telemetry metadata take a message ID but not the reply-ack form, which stays in the text with `brace-in-message-text`. A stray `{` in a `PARM.`, `UNIT.` or `BITS.` list keeps it metadata, and a strict decoder now names the error. Only a message can be telemetry metadata or a directed query: bulletin and NWS bulletin text starting `PARM.`, `EQNS.`, `?` and so on is just text, and the encoder refuses metadata or a query to a bulletin addressee.
- Directed queries: one space before the target is a separator, and spaces after it are padding.
- Telemetry: a value with a space in it is `invalid-telemetry`, and an `EQNS.` coefficient that is not a finite number (`1e400`) makes it a plain message.
- Status: `0` is not an ERP code, so `^B0` is text, and the text before a beam heading keeps its spaces.
- A general query footprint beyond 90 or 180 degrees is `invalid-general-query`, and an Agrelo bearing over 360 is `invalid-agrelo-df`. A DF report's `/BRG/NRQ` with a bearing over 360 is `out-of-range-value` and is dropped.
- Third-party packets: the inner source may be 1-9 printable ASCII characters other than `>` and `:`. A defect the inner header may tolerate (several used markers, an empty path entry) is decoded leniently, with its warning on the inner packet; a strict decoder rejects the packet as `invalid-third-party`.
- Encoding: the encoder writes an equivalent form or refuses, never bytes that read back as different data. It writes Mic-E status text that would start with a type code character or 0x1D after a `/`, an APRSH query target padded to 9 characters and another undefined type's target after a space, a third-party packet's empty inner information field as received, and an NMEA comment after the checksum, and a snowfall exactly in its three characters, with a decimal point where it needs one (0.32 as `.32`; it used to write `0.3`). It refuses a compressed range that is not one of the cs bytes' steps (saying so, where it used to say the comment would not read back), compressed cs data without a compression type, a third-party packet whose inner header has a tolerated defect, an out-of-range footprint, an Agrelo bearing over 360, a capability value with a control character or padding spaces, a coefficient that is not finite, a digit DAO datum with added precision, a snowfall three characters cannot hold exactly, an area object with an overlay, comment telemetry binary over 255, a signpost that is not printable ASCII or has an overlaid symbol, a DF bearing over 360, a beam ERP code of 0, and `BLN` followed by a lower-case letter.
- `tools/diff_dump.py` decodes a re-encoded packet again under a well-formed header (for Mic-E, the destination the encoder computed), so a defect in the original header is no longer counted against the encoder.
- The conformance tests no longer check that a Mic-E case without `device` identifies no device: the vectors' README says such a case says nothing about device identification.

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

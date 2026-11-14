# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

### Fixed

- A telemetry value that is a whole number outside 0-999 is written as the shortest decimal that reads back as it, with no exponent, as the shared Encoding rule says: `1e23` is `1` and 23 zeros, not `99999999999999991611392`.
- `decode_tnc2` given a `str` holding the lone surrogates `bytes.decode("utf-8", "surrogateescape")` makes no longer raises `UnicodeEncodeError`: the original bytes are restored. Any other lone surrogate is read as U+FFFD, or makes the header unusable if it is in the header.
- Builders and `encode_info` raise only `EncodeError` for bad numbers and text: `ambiguity=1.0`, a `Decimal` NaN and an integer too large for a float no longer leak `TypeError`, `InvalidOperation` or `OverflowError`; a number too large to use is `value-out-of-range`; a lone surrogate in text is `text-reads-as-field`, not `not-a-number`.
- `Decimal` is accepted wherever another real number is (a `Decimal('51.45')` latitude was refused).
- Decoding no longer takes quadratic time on a very long run of digits in `EQNS.` coefficients, telemetry values and query footprints; accepted text is unchanged.

### Changed

- `identify_tocall` and `identify_mic_e` are exported from the package top level.

Round 4 rulings of the vectors (aprs-vectors `round-4`, commit fb1a6f8), shared by all six libraries as 1.2.0. Conforms to aprs-vectors 1.2.

- The licence is now MIT from this release; versions up to 1.1.0 were published under AGPL-3.0-or-later and keep it. The conformance vectors are CC0.

- An encoder or builder refuses an information field over 256 bytes with the new code `information-field-too-long` (`RefusalCode.INFORMATION_FIELD_TOO_LONG`, last in the refusal order; `too-long` now means only a field over its own limit), counted in UTF-8 with number text included, and for a third-party packet the outermost field. The size is the last check, on the bytes actually written, after every other check including the read-back: a record any other rule refuses gets that rule's code, and only an otherwise sound record over 256 bytes is refused for its size (a field over its own limit, such as message text over 67 characters, keeps its place in the refusal order). Decoding has no limit: a decoded packet over 256 bytes re-encodes `refused`, `information-field-too-long`. `Packet.to_tnc2`, `to_ax25` and `to_kiss` write a packet the program already holds and are not encoders: the information field goes through as it stands, with no size check. `INFORMATION_FIELD_LIMIT` is exported from `pdn_aprs.encode`.
- Text with a control character (a byte below 0x20 or 0x7F, a TAB, or a CR or LF inside the text) in a comment, status text, message, bulletin or NWS bulletin text, telemetry name, unit or project title, capability value, or the free text a report leaves: a decoder gives one `warning:control-character-in-text` per packet's text and keeps the text as sent; a strict decoder rejects it. User-defined, raw weather and test data, Mic-E fixed bytes and Rev 0 telemetry are not judged; object and item names keep their own rules. Encoders and builders refuse such text as `invalid-character` (not only CR and LF), and a Mic-E status text starting with 0x1D is refused, not written after a `/`.
- A fixed-width weather field whose digits run on by two or more, followed by the end of the information field or by a defined field the run goes on to read, is `warning:out-of-range-value`, the value dropped, and the fields carry on after the run (`t2147483647r000` has a rain of 0 and no temperature). The dropped value counts as present for `incomplete-weather`.
- A Mic-E altitude goes in the Mic-E altitude bytes. A builder rounds it once to the nearest metre from the value given (1000 ft is 305 m) and refuses one outside -10,000 to 743,570 m (`value-out-of-range`); it never writes a `/A=`. An encoder writes neutral data in a `/A=` only when only a `/A=` holds it exactly (whole feet within six digits that are not whole metres, or are outside the bytes' range: -50000 ft is `/A=-50000`); otherwise in the Mic-E bytes, rounded to the metre (100.5 ft is 31 m). An altitude read from a `/A=` is written back as one.
- Builder defaults are written down and never read the clock: no timestamp on an object or positionless weather report is `missing-field`; a Mic-E report with no message is off duty; no symbol on a position, object, item or Mic-E report is `invalid-symbol`; a telemetry report with no sequence is `missing-field`, with no bits writes `00000000`, with no analog values five empty channels. `Station.telemetry` takes `sequence`, `analog` and `bits` as optional arguments for this.
- A Mic-E altitude that no `/A=` holds exactly (not whole feet, or beyond six digits) and that the Mic-E bytes cannot carry in place (the first byte would read as a type code, and no type code is given) is `value-has-no-form`, not `text-reads-as-field`.
- A status symbol given with no locator is `missing-field` (`Station.status` and neutral data alike), not `field-not-allowed`.
- Neutral telemetry data with no `sequence` is `missing-field`, not `malformed` (and no longer unsupported by the dump tool); an empty sequence given is absent, so `missing-field` too (it was `malformed`).
- A builder that left out a field it needs (a sequence, a timestamp) names that fault, not the size of the record it would have written.
- Run 2 rulings (aprs-vectors `round-4`, commit c423a29): a builder given one quantity in two units (`speed_knots` and `speed_kmh`, `altitude_feet` and `altitude_m`, and the weather pairs) names `value-given-twice` even when each one-unit build would be over 256 bytes; a result refused only for the information field's size ranks after it. An Agrelo bearing given to an encoder is rounded to the nearest degree like a course, then range-checked (12.5 is `013`, 360.5 is `value-out-of-range`; a fractional bearing was `not-a-number`). A Mic-E PHG or RNG straight after a locator whose space is missing is lifted before a later altitude is looked for (this library already read it so).
- A NaN or infinity in a field that has no place (a weather report's altitude, inside a third-party packet too) no longer makes the record `not-a-number`: the field has no checks, so it is `field-not-allowed`. A compressed GGA altitude that is NaN or infinite is `not-a-number`, not written as 1 ft.
- The dump tool's encode mode reports an ack or a reject given a message ID inside third-party packets as the refusal its value decides (`field-not-allowed`, or an earlier code), marked `"via": "tool"`, instead of `unsupported`; none of the five 100,000-line sets of either seed gives `unsupported` or `crash` any more.
- The conformance runner runs the vectors' `build` cases (`cases/builder.json`) through the real `Station` methods, with the same recipe code the dump tool's build mode uses (`tools/recipe.py`).
- `DiagnosticCode.CONTROL_CHARACTER_IN_TEXT` (tolerable) and `DiagnosticCode.IMPLEMENTATION_LIMIT` are new. This library has no fixed capacity, so it never gives the second.
- The dump tool's build mode passes only the keys a recipe gives, never filling in an absent one, and reports a missing key as `unsupported` rather than crashing.

- Storm data's fields are digits: a field of dots is not storm data (it stays comment text), a whole gale radius that is not digits ends the storm data and starts the comment (it was dropped, `%4.4` vanished), and an encoder given storm data missing a required field refuses it as `missing-field` (it wrote dots).
- A telemetry sequence of `MIC` followed by more characters is `malformed` for an encoder (the form `T#MIC` cannot carry it).
- In a positioned weather report the end of the weather text is the start of a trailing base-91 telemetry or `!DAO!`, so a run-on value before one is dropped (`t2147483647!W12!`).
- A finite value too large for the unit it is converted to by a builder (`altitude_m=1e308`, a speed in km/h, a temperature in Celsius) is `value-out-of-range`, not `not-a-number`.
- `Station.message` and `Station.bulletin` take `text` as optional (empty text, which is refused), so the dump tool no longer supplies it. The dump tool marks every refusal it makes itself with `"via": "tool"`, and a recipe with no `station` is from `N0CALL`.
- `RefusalCode.INFORMATION_FIELD_TOO_LONG` is new. Conforms to the 22 build cases that pin each builder default.

### Breaking changes for callers

- An encoder or builder refuses an information field over 256 bytes (`information-field-too-long`); text with a control character is refused (`invalid-character`); a decoder gives `warning:control-character-in-text`, so a strict decoder now rejects such packets; a run-on weather value before a defined field is dropped with `out-of-range-value`.
- An object or positionless weather report built with no timestamp is refused (`missing-field`) instead of being stamped from the clock.
- `timestamp=True` (the time now) is gone, and raises `TypeError` (`timestamp=False` is still no timestamp): pass `datetime.now(timezone.utc)` as `timestamp`. `Station.object` no longer has the time now as its default timestamp.
- A Mic-E report built with no `mic_e_message` is off duty, not in service.
- A position, object, item or Mic-E report built with no symbol (and none on the `Station`) raises `EncodeError` (`invalid-symbol`) instead of `ValueError`.
- A Mic-E altitude given in feet to `Station.mic_e` goes in the Mic-E altitude bytes, rounded to the metre, instead of a `/A=` in the status text; `MicEReport(altitude_feet=...)` given to an encoder goes there too unless only a `/A=` holds it exactly.
- Neutral Mic-E altitudes that are neither whole feet nor whole metres go in the Mic-E bytes, rounded to the metre (they were a rounded `/A=`).

## [1.1.0] - 2026-11-14

Round 3 rulings of the vectors (aprs-vectors `round-3`), shared by all six libraries as 1.1.0.

### Changed

- Third-party packets nest at most four deep: a fifth `}` is not read, and the packet whose information field it starts is `unrecognized` (`malformed`) with `error:invalid-third-party`. A line of thousands of `}` no longer recurses to the interpreter's limit.
- An AX.25 address is upper-case letters and digits, then padding. A lower-case letter is still tolerated (`invalid-ax25-address-characters`); any other character, a space before the last character included, makes the header unusable (`invalid-address`), so no TNC2 line is written from it.
- A `!DAO!` on an ambiguous position in a weather report is met before the weather comment, so a strict decoder rejects it as `dao-with-ambiguity`, not `weather-comment`.
- Refusal order, where a record has several faults: more analog values than a telemetry report (5), base-91 telemetry (1-5) or `EQNS.` (15) holds is `too-long`, fewer is `malformed`; a message with an invalid reply-ack and no message ID is `invalid-message-id`; a directed query's addressee is judged before its type; a weather report's altitude has no place, so it is `field-not-allowed` whatever its value; a status locator with an unknown symbol table is `invalid-symbol`, and a lower-case locator (status, Mic-E or Maidenhead beacon) is `malformed` whatever else is missing; a course, speed or range in the place a weather report's wind or a GGA altitude holds keeps its own checks (`value-out-of-range`, `value-has-no-form`) ahead of `extension-conflict`; compressed wind with only a direction or only a speed still has the one given checked; undecoded inner data of a third-party packet is `not-encodable`, ahead of its header.
- NMEA data is its sentence: a sentence given without the fields it holds is written, a field given that disagrees with it is `invalid-nmea`, and so is a comment given with a sentence that has no checksum (it was `field-not-allowed`).
- A Mic-E report with no speed given is written (its read-back always has speed 0), so a Mic-E position within a rounding step of 90 or 180 degrees, with ambiguity, is written in the box below the edge as the ruling says.
- Text the neutral form leaves out is empty text: no positioned symbol is `invalid-symbol`, no name `invalid-name`, no addressee `invalid-addressee`, and a general or directed query with no type is `invalid-code` (a query with no type was `missing-field`).
- Base-91 telemetry on a weather report has no place: `field-not-allowed`, and its own checks do not run.
- Undecoded data at any depth of third-party nesting is `not-encodable`, ahead of the outer header.

- Third-party data nested more than four deep is refused with `invalid-third-party-header`, ahead of any fault inside it (undecoded data at the end of the chain is still `not-encodable`). The chain is walked in a loop, as `to_neutral` does, so a chain built thousands deep is refused or converted without a recursion error.

### Behaviour changes for 1.x callers

- Lower-case locators (status, Mic-E, Maidenhead beacon) are refused as `malformed`, where the encoder used to write them in upper case. The `Station` builders still write them in upper case.
- AX.25 addresses with punctuation, control characters or a space before the last character are `invalid-address` (an unusable header), not a tolerated defect.
- Telemetry with more values than the field holds is `too-long` (was `malformed`); a comment with an NMEA sentence that has no checksum is `invalid-nmea`; a weather report's altitude and telemetry are `field-not-allowed`.
- Decoding stops at four levels of third-party nesting.

### Fixed

- A NaN or infinity no longer hides an earlier code: a name, timestamp, addressee or header fault is named ahead of `not-a-number`, as the order has it, and a NaN in a field a weather report has no place for (an altitude without GGA bytes, telemetry, a frequency) is not judged.
- `Station` builders refuse non-finite Mic-E course, altitude, ambiguity and telemetry sequence with `not-a-number` instead of raising `OverflowError` or `TypeError`.
- A `Station` method given one quantity in both units (speed, altitude, temperature, rain) is built once with each unit and refuses with the first code in the Refusal reasons order among each result and `value-given-twice` (which sits after `missing-field`), so a value out of range in either unit, or any earlier fault, wins; it is never built from one unit.
- `build_packet` and the `Station` builders check the header first and as APRS-IS has it: a source, destination or path entry that is not 1-9 letters, digits or `-` (`BAD!!`) is `invalid-address`, ahead of any fault in the data. It used to accept any printable text.
- `Station` builders name a quantity given in both units (`value-given-twice`) in the Refusal reasons order, after any earlier code, instead of at once; a Mic-E report is refused for its out-of-range values (a speed of 999.5) before its destination at the poles is judged.
- The vectors runner compares refusal codes (`refusal` and `reencode_refusal`), not only that a refusal happened.
- The dump tool stands in an invalid symbol for one that is not two characters, so such data is refused as `invalid-symbol` instead of being reported unsupported, and names the refusal for an ack or reject given a message ID.

## [1.0.1] - 2026-11-12

### Added

- Refusals carry a reason code. `EncodeError.code` is a new `RefusalCode` (a `str` enum, exported from the package) naming the rule the data broke, one of the 26 shared ids in the vectors' `codes.json`. The message text and every existing signature are unchanged, and `EncodeError("message")` still works (it gives `does-not-read-back`).
- `Station` refusals that were a plain `ValueError` (a quantity in both units, an object with no timestamp, a positionless weather report with a symbol, a latitude without a longitude) now raise `EncodeError`, a subclass of `ValueError`, so existing handlers still catch them.
- The dump tool writes `refusal` on refused encode and build records, `reencode_refusal` on decode records whose re-encode is refused, and `ax25_refusal` in the API view.

## [1.0.0] - 2026-11-10

This is the first stable release. The public API is now frozen under semantic versioning. From 1.0 the major and minor version are shared with aprs-vectors: a ruling round is a minor version for all five implementations, this library's own fixes are patch versions, and an API break is a major version.

The 1.0 API cleanup. Nothing the vectors check changes: every vectors case passes, and the dump tool's encode, build and decode output over the 100,000-line comparison sets is byte for byte what 0.3.0 gave. Removed and renamed things are gone with no shim.

### Breaking changes

Migrating from 0.3.0:

- `Station` builder keywords are the names of the data fields they fill. `course` is `course_degrees`, `speed` is `speed_knots`, `altitude` is `altitude_feet`, `precise` is `dao`, and Mic-E `message` is `mic_e_message`. In `weather`: `wind_direction` is `wind_direction_degrees`, `wind_speed` is `wind_speed_mph`, `gust` is `wind_gust_mph`, `temperature` is `temperature_f`, `rain_1h`, `rain_24h` and `rain_since_midnight` are `rain_1h_in`, `rain_24h_in` and `rain_midnight_in`, `rain_since_midnight_mm` is `rain_midnight_mm`, `humidity` is `humidity_percent`, `pressure` is `pressure_mbar`, `luminosity` is `luminosity_w_m2`, `snow_24h` is `snow_24h_in`. The metric siblings (`speed_kmh`, `altitude_m`, `temperature_c`, `rain_1h_mm`, `rain_24h_mm`) keep their names.
- `Station.message`, `ack` and `reject` take `addressee` instead of `to`; the four `telemetry_*` metadata builders take `addressee=` instead of `station=`; `Station.bulletin` takes `id` instead of `identifier`.
- `Station(callsign, via=...)` is `Station(callsign, path=...)`: one field, given as text or a list and held as a tuple. The derived attribute is gone (`path` is now the field itself).
- The `tone` and `offset_khz` keywords of `position`, `object`, `item` and `mic_e` are gone. `frequency` is a number in MHz (rounded to the field's step) or a `VoiceFrequency`, which carries the tone kind, its whole value and the offset: `frequency=VoiceFrequency(145.5, tone=ToneType.TONE, tone_value=77, offset_khz=-600)`.
- `Station.telemetry` takes the sequence as a whole number only (text sequences remain possible by building a `TelemetryReport` yourself), and refuses one outside 0-999 with `EncodeError` instead of `ValueError`. `EncodeError` is now what every refusal of the data raises; `ValueError` stays for calls that mean nothing (a quantity given in both units, no symbol anywhere, a latitude without a longitude).
- `Bulletin.identifier` is `Bulletin.id`, matching the builder keyword. `Station.bulletin` refuses an `id` that is not one character with `EncodeError`, and `Station.telemetry` raises `TypeError` for a sequence that is not an int (a bool included); out of range stays `EncodeError`.
- `pdn_aprs.decode` is gone; use `decode_tnc2`.
- `pdn_aprs.neutral` is now the private `pdn_aprs._neutral`. The vectors' neutral form is not public API; use the data classes, `Packet.to_tnc2()` and the other accessors.
- `PathEntry.call` is `PathEntry.address` (and the constructor's first argument).
- `Fix` and `NmeaSource` are `CompressionFix` and `CompressionSource`.
- `Phg.gain_dbi` is `Phg.gain_db`.
- `MicEReport.mic_e_message` has no default; give it.
- `NeutralFormError` (now private) subclasses `AprsError`.
- Made private: `pdn_aprs.packet.tnc2_path`, `is_q_construct` and `Q_CONSTRUCTS` (deleted), `pdn_aprs.devices.identify` and `mic_e_suffixes`, `pdn_aprs.builder.KMH_PER_KNOT` and `MM_PER_INCH`, `pdn_aprs.symbols.PRIMARY_TABLE` and `ALTERNATE_TABLE`, `pdn_aprs.options.LENIENT` and `STRICT` (use `ParseOptions.lenient()` and `ParseOptions.strict()`).

### Changed

- `PositionedData.course_degrees`, `Weather.wind_direction_degrees`, `humidity_percent` and `luminosity_w_m2` are `float`, so hand-built data can carry 88.6 degrees. Decoded values are still whole; the encoder rounds once, halves away from zero. The builder keywords for these take `float` too.
- `MicEReport.altitude_in_comment` is set by the decoder when the comment parser lifted a `/A=`, so encoding a copy of decoded data writes the same bytes. It now takes part in equality; it is still left out of the neutral form.
- `DEFAULT_DESTINATION`, `MESSAGE_TEXT_LIMIT` and `DATABASE_VERSION` are exported at the top level.

## [0.3.0] - 2026-11-10

The encoder writes exactly the bytes the vectors' Encoding rule gives, now that `canonical_info` is binding (packet-net/aprs-vectors, exact-bytes rulings, batches 1 and 2), and the builders close the gaps listed under Added. Some bytes the encoder writes differ from 0.2.0 (see Changed: comment order, rounding, newly refused input), so check any stored expected output. The vectors are pinned at 130fc04.

### Added

- `Station.object` takes `phg`, `compressed`, `ambiguity`, `precise`, `telemetry` and `range_miles`; `Station.item` takes `course`, `speed`, `speed_kmh`, `altitude`, `altitude_m`, `phg`, `frequency` (with `tone` and `offset_khz`), `compressed`, `range_miles`, `ambiguity`, `precise` and `telemetry`; `Station.mic_e` takes `frequency` (with `tone` and `offset_khz`), `ambiguity`, `precise` and `telemetry`; `Station.weather` takes a `symbol` (default the weather station symbol, as before); `Station.status` takes a `beam`. They share the position builder's code, so units are converted and rounded once as there.
- `tools/diff_dump.py --build` maps all of these recipe keys instead of reporting them `unsupported`.
- `Footprint.latitude_text` and `Footprint.longitude_text`: a general query's footprint numbers as sent, leading space included, so they are written back byte for byte (`?APRS? 34.0,-117.15,0200`). They are optional when encoding.

- `tools/diff_dump.py` has an encode mode (`--encode`, neutral data from the vectors' `tools/generate.py`) and a build mode (`--build`, builder recipes), and its decode records carry the API view: the header, path and q-construct, the diagnostics accessors, the TNC2 and AX.25 forms, the device, the symbol's description and what the PHG codes stand for.
- `MicEReport.altitude_in_comment` asks the encoder to write the altitude as a `/A=` in feet even where the Mic-E altitude bytes would hold it; `Station.mic_e` sets it for an altitude given in feet. The neutral form leaves it out.
- `Station.position`, `object` and `mic_e` take `speed_kmh` and `altitude_m`, and `Station.weather` takes `temperature_c`, `rain_1h_mm`, `rain_24h_mm` and `rain_since_midnight_mm`, beside the units APRS sends; they are converted.

### Changed

- The comment of a position, object or item is written in the order frequency, braces, altitude, free text, base-91 telemetry, `!DAO!`: the frequency goes first, where radios read it (APRS12c ch. 18), the altitude follows it and its fields straight on, and the free text follows after a space (`j006/058/146.520MHz/A=000889 Dayton Bound`; it used to write `/A=` before the frequency).
- A frequency after a PHGR follows its `/` straight on (`PHG33403/145.225MHz`, where it used to write `//`), in Mic-E status text too; after any other data extension it is written after a `/`, now also when braces or an altitude follow.
- The digits of a `!DAO!` on a compressed position, which a decoder ignores, are those the same DAO gives the position written uncompressed (`!sCp!`), so that a reader that did apply them lands on the position reported; they used to be `!!` or `00`.
- A snowfall under 1 inch is written as `.` and two digits (0.5 as `.50`, where it used to write `0.5`).
- A range sent later in a compressed position's comment (`RNG0025`) is rounded to the nearest step of the cs bytes, with the default type byte, where it used to be refused.
- User-defined data that ends in a line break is refused: the decoder takes a trailing CR or LF as a tolerated defect and drops it, so it would not read back.
- `from_neutral` reads a bulletin or NWS bulletin with its empty text left out, and a third-party packet whose source or destination is left out as empty.
- Every value the encoder rounds goes to the nearest step, halves away from zero; Python's `round` took halves to the even number (a temperature of -2.5 was written `t-02`, now `t-03`).
- A half is judged on the value in binary floating point, measured in steps, and one within 1e-6 of a half is the half, which goes away from zero (vectors ruling F2): 1.275 inches of rain is `p128`, a latitude of 0.9764166666666666 degrees (58.584999999999996 minutes) is `0058.59N`, a pressure of 986.9499999999999 mbar is `b09870`. A voice frequency and a footprint radius are rounded the same way, and a frequency that rounds past its digits is refused.
- Every value is rounded before it is checked: a course or wind direction of 360.4 is `360`, and one of -0.3 is `000` (both used to be refused).
- A course of 0 is refused in Mic-E and compressed reports, where it would read back as no course or as 360; uncompressed it is `000` (F1).
- A snowfall is rounded into its three forms (0.995 as `001`, 9.96 as `010`, 12.5 as `013`), where one the three characters could not hold exactly used to be refused (F3).
- A number given as data with no text (an `EQNS.` coefficient, a telemetry value, a footprint coordinate) is the shortest plain decimal: 1e61 is `1` and 61 zeros, where it used to be `1e+61` (F11).
- A Mic-E locator followed straight by base-91 telemetry or a `!DAO!` is no missing space, since both are lifted from the status text first (F16): the decoder no longer warns and the encoder writes them straight after it.
- `T#MIC` with an empty first channel is refused with a reason of its own (F12).
- `Packet.device` matches a tocall case-sensitively, so `APNl02` is nothing (A1).
- `Station.mic_e`: a course of 0, or one that rounds to 0, is unknown and written as no course (B1); an altitude in metres goes in the Mic-E altitude bytes, rounded to the metre, and one in feet in a `/A=` (B2).
- `Station.telemetry` refuses a sequence over 999 (B6).
- A compressed speed or range rounds to the nearest step of its formula for any whole s, and is refused when that s is outside the byte: a speed of -0.03 knots is written as 0 and -0.3 refused, a range of 1.95 miles is written as 2 and 1.9 refused (G3; ranges under 2 miles used to be refused, negative speeds written as 0).
- The ambiguity cut takes the 1e-6 tolerance at the box edge above (G2).

- A compressed position whose cs bytes carry a range, a course and speed or wind, with no compression type, is written with the default type byte `C` (it used to be refused for anything but a range).
- Strict decoding rejects a Mic-E status text where lifting a `!DAO!` would join the bytes either side of it into a Mic-E altitude, since the altitude is looked for before the DAO is lifted.

### Fixed (decoder)

- Strict decoding rejects Mic-E status text with `mic-e-altitude-not-first` only when there is a later altitude to decline and lifting telemetry or the `!DAO!` would form an altitude across the place it came from; one the bytes already held is kept as text.
- `Packet.to_ax25` refuses an address with a dash and no SSID (`WIDE1-`).
- Storm data fields are digits or dots: a field with a space (`> 90`) means no storm data, and the text is comment.

- `Packet.to_ax25` refuses an address whose SSID has a leading zero (`-00`, `-0`, `-07`), which the frame would bring back as a different SSID.
- A snowfall sent as three spaces (`s   `) is a weather field sent as unknown, not comment text.

- An area object's offsets are digits only (`Tyy/Cxx`), so `7 0/310` after the `\l` symbol is comment text, not an area.

- A Mic-E comment that would join the `/A=` digits before it into a Mic-E altitude (`{5}` after `/A=000101`) is written after a separating space; it used to be refused (E12).
- An ambiguous position is written from the box that holds it, so a decoder reports the centre nearest the value: 3.596 minutes at ambiguity 1 is `03.5 `, where rounding first made it `03.6 `. In Mic-E the longitude digits the ambiguity covers, which a decoder ignores, are written as the centre it reports.
- The `!DAO!` digits on a compressed position are those of the position the compressed bytes report, not of the value given before it was rounded into them.
- A compressed weather report whose altitude the GGA cs bytes cannot hold exactly is written with the nearest cs step, since there is no comment for a `/A=` (F14). It used to be dropped silently.
- `Station.status` sends a grid locator in upper case, as a decoder reports it; a lower-case one used to be refused.

### Fixed

- `Packet.device`: aprs-deviceid's `n` wildcard matches a digit, so `APW290` is WinAPRS and `APD225` aprsd; they were not identified.
- The conformance tests compare the bytes written with a case's `canonical_info` byte for byte, for `equivalent` cases once the data reads back the same, and for the new `rounded` cases, whose data differs by the rounding.

## [0.2.0]

Brought into line with the rulings from seven rounds of differential fuzzing of all five implementations (packet-net/aprs-vectors: 159 new cases, and new rules in its README and interpretations.md). All 6,015 of the vectors' checks pass.

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
- A general query footprint beyond 90 or 180 degrees is `invalid-general-query`, and so is a leading space on a negative value (only a positive one may have it, APRS12c ch. 15), such as `- 17.15` or ` -34.02`. A footprint value is a number as a telemetry value is, so `-.1715` and `.02` are now accepted; the encoder writes the space before a positive latitude or longitude and not before a negative one, and an Agrelo bearing over 360 is `invalid-agrelo-df`. A DF report's `/BRG/NRQ` with a bearing over 360 is `out-of-range-value` and is dropped.
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

[Unreleased]: https://github.com/packet-net/aprs-py/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/packet-net/aprs-py/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/packet-net/aprs-py/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/packet-net/aprs-py/compare/v0.3.0...v1.0.0
[0.3.0]: https://github.com/packet-net/aprs-py/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/packet-net/aprs-py/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/packet-net/aprs-py/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/packet-net/aprs-py/releases/tag/v0.1.0

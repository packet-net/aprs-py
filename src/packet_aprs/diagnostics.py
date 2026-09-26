"""Diagnostics: what a decoder found wrong with a packet, and how serious it is.

The codes are those of the conformance vectors' ``codes.json``. A tolerable code is a defect a
lenient decoder accepts with a warning; a strict decoder rejects the packet instead. The other
codes are errors in both modes, or information only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["Diagnostic", "DiagnosticCode", "Severity"]


class Severity(str, Enum):
    """How serious a diagnostic is."""

    INFO = "info"
    """Information only: nothing is wrong with the packet."""
    WARNING = "warning"
    """A defect that was tolerated."""
    ERROR = "error"
    """A defect that stopped the packet (or its header) being decoded."""

    def __str__(self) -> str:
        return self.value


class DiagnosticCode(str, Enum):
    """Every diagnostic code, named as in the conformance vectors' ``codes.json``."""

    INVALID_HEADER = "invalid-header"
    """The TNC2 header is not SOURCE>DEST[,PATH]:."""
    INVALID_ADDRESS = "invalid-address"
    """An address is empty, too long, or has characters that cannot appear in one."""
    EMPTY_DESTINATION = "empty-destination"
    """The destination address is empty (UAP 5.2)."""
    EMPTY_PATH_ENTRY = "empty-path-entry"
    """The digipeater path has an empty entry (UAP 5.6)."""
    MULTIPLE_USED_MARKERS = "multiple-used-markers"
    """More than one path entry is marked used with *; only the last used one should be (UAP 5.30)."""
    NOT_APRS_FRAME = "not-aprs-frame"
    """The AX.25 frame is not a UI frame with PID 0xF0, or is too short (APRS12c ch. 3)."""
    NUL_PADDED_ADDRESS = "nul-padded-address"
    """An AX.25 address is padded with NUL rather than spaces (UAP 5.29)."""
    INVALID_AX25_ADDRESS_CHARACTERS = "invalid-ax25-address-characters"
    """An AX.25 address has characters other than upper-case letters and digits."""
    TOO_MANY_DIGIPEATERS = "too-many-digipeaters"
    """The AX.25 frame has more than 8 digipeater addresses."""
    TRAILING_LINE_BREAK = "trailing-line-break"
    """The information field ends with CR or LF (APRS12c ch. 5, UAP 5.13)."""
    NON_UTF8_TEXT = "non-utf8-text"
    """Text that is not valid UTF-8 (UAP 5.16)."""
    TRUNCATED = "truncated"
    """The information field is shorter than its format requires."""
    NOT_APRS = "not-aprs"
    """The first byte is not a data type identifier (APRS12c ch. 20)."""
    RESERVED_DATA_TYPE = "reserved-data-type"
    """A reserved data type identifier with no defined format (APRS12c ch. 5)."""
    OBSOLETE_FORMAT = "obsolete-format"
    """A format the spec marks obsolete or not recommended, e.g. raw NMEA or raw weather."""
    OUT_OF_RANGE_VALUE = "out-of-range-value"
    """A value in a well-formed field is out of range and was dropped."""
    INVALID_TIMESTAMP = "invalid-timestamp"
    """A timestamp is malformed or out of range (APRS12c ch. 6, UAP 5.8)."""
    INVALID_POSITION = "invalid-position"
    """The position is missing or starts with something that cannot begin one."""
    INVALID_LATITUDE = "invalid-latitude"
    """The latitude is malformed (APRS12c ch. 6, UAP 5.7)."""
    INVALID_LONGITUDE = "invalid-longitude"
    """The longitude is malformed (APRS12c ch. 6, UAP 5.7)."""
    LOWERCASE_HEMISPHERE = "lowercase-hemisphere"
    """A lower-case hemisphere letter (UAP 5.9)."""
    INVALID_SYMBOL_TABLE = "invalid-symbol-table"
    """The symbol table identifier is not /, \\, 0-9 or A-Z."""
    INVALID_SYMBOL_CODE = "invalid-symbol-code"
    """The symbol code is not printable ASCII."""
    INVALID_COMPRESSED_POSITION = "invalid-compressed-position"
    """A compressed position is malformed (APRS12c ch. 9)."""
    DAO_WITH_AMBIGUITY = "dao-with-ambiguity"
    """A !DAO! adds precision to an ambiguous position, which contradicts it."""
    DATA_EXTENSION_IN_COMMENT = "data-extension-in-comment"
    """A data extension (PHG, RNG, DFS) appears later in the comment (UAP 5.15)."""
    INVALID_OBJECT_NAME = "invalid-object-name"
    """The object name is empty or not printable ASCII."""
    OBJECT_NAME_NOT_PADDED = "object-name-not-padded"
    """The object name is not padded to 9 characters."""
    OBJECT_WITHOUT_TIMESTAMP = "object-without-timestamp"
    """An object report has no timestamp (APRS12c ch. 11)."""
    INVALID_ITEM_NAME = "invalid-item-name"
    """The item name is not 3-9 printable characters followed by ! or _."""
    INCOMPLETE_WEATHER = "incomplete-weather"
    """A weather report lacks a mandatory field (APRS12c ch. 12)."""
    WEATHER_COMMENT = "weather-comment"
    """Text after the weather data; weather reports have no comment (UAP 2.7.1, ch. 5.33)."""
    INVALID_WEATHER = "invalid-weather"
    """Positionless or raw weather data that could not be decoded."""
    INVALID_MIC_E_DESTINATION = "invalid-mic-e-destination"
    """The destination address is not a valid Mic-E encoding (APRS12c ch. 10)."""
    INVALID_MIC_E_INFORMATION = "invalid-mic-e-information"
    """The Mic-E information field is malformed (APRS12c ch. 10)."""
    KENWOOD_FF_PADDING = "kenwood-ff-padding"
    """Kenwood TM-D710 0xFF padding was removed (UAP 5.10)."""
    MIC_E_MISSING_DEVICE_TYPE = "mic-e-missing-device-type"
    """A Mic-E report without a device type prefix (UAP 5.4)."""
    INVALID_MESSAGE = "invalid-message"
    """A message is malformed (APRS12c ch. 14)."""
    UNPADDED_ADDRESSEE = "unpadded-addressee"
    """The addressee is not padded to 9 characters."""
    MESSAGE_ID_ON_ACK = "message-id-on-ack"
    """An ack or rej carries a message ID of its own (UAP 5.32)."""
    INVALID_TELEMETRY_METADATA = "invalid-telemetry-metadata"
    """A telemetry metadata message (PARM/UNIT/EQNS/BITS) is malformed (APRS12c ch. 13)."""
    INVALID_QUERY = "invalid-query"
    """A directed query is malformed (APRS12c ch. 15, UAP 5.18)."""
    INVALID_TELEMETRY = "invalid-telemetry"
    """A telemetry report is malformed (APRS12c ch. 13)."""
    INVALID_STATUS = "invalid-status"
    """A status report is malformed (APRS12c ch. 16)."""
    INVALID_LOCATOR = "invalid-locator"
    """A Maidenhead locator is malformed."""
    INVALID_NMEA = "invalid-nmea"
    """An NMEA sentence is malformed."""
    NMEA_CHECKSUM_MISMATCH = "nmea-checksum-mismatch"
    """An NMEA sentence's checksum does not match, so the sentence is corrupt and is not decoded."""
    INVALID_THIRD_PARTY = "invalid-third-party"
    """A third-party header is malformed (APRS12c ch. 17)."""
    INVALID_GENERAL_QUERY = "invalid-general-query"
    """A general query is malformed (APRS12c ch. 15)."""
    INVALID_CAPABILITIES = "invalid-capabilities"
    """A station capabilities report is malformed (APRS12c ch. 15)."""
    INVALID_USER_DEFINED = "invalid-user-defined"
    """A user-defined packet is shorter than its 3-byte header (APRS12c ch. 19)."""
    INVALID_AGRELO_DF = "invalid-agrelo-df"
    """An Agrelo DF report is malformed."""
    MISSING_SPACE_AFTER_LOCATOR = "missing-space-after-locator"
    """A grid-locator status report lacks the mandatory space before its text (UAP 5.17)."""
    COMPRESSION_TYPE_RESERVED_BITS = "compression-type-reserved-bits"
    """A compressed position's type byte sets its unused high bits (APRS12c ch. 9)."""
    MALFORMED_TIMESTAMP = "malformed-timestamp"
    """A timestamped position report whose timestamp is missing or not timestamp-shaped (UAP 5.8)."""
    POSITION_NOT_AT_START = "position-not-at-start"
    """A ! position found after other text (obsolete TNC beacon rule)."""
    NON_STANDARD_WEATHER_FIELD_WIDTH = "non-standard-weather-field-width"
    """A weather field is one character shorter or longer than its fixed width (UAP 5.31)."""
    WIND_FIELDS_INSTEAD_OF_EXTENSION = "wind-fields-instead-of-extension"
    """Wind sent as c/s fields in a position weather report instead of the DDD/SSS extension, or after a compressed position whose cs bytes carry no wind."""
    WIND_EXTENSION_AFTER_COMPRESSED = "wind-extension-after-compressed"
    """An uncompressed wind extension after a compressed weather position (UAP 5.33)."""
    MIC_E_ALTITUDE_NOT_FIRST = "mic-e-altitude-not-first"
    """A Mic-E altitude after other status text instead of first (APRS12c ch. 10)."""
    BRACE_IN_MESSAGE_TEXT = "brace-in-message-text"
    """Message text contains a { that does not start a valid message ID (APRS12c ch. 14)."""
    INVALID_ADDRESSEE_CHARACTERS = "invalid-addressee-characters"
    """A message addressee contains a space or : (APRS12c ch. 14)."""
    LETTER_GROUP_BULLETIN = "letter-group-bulletin"
    """A bulletin addressee has a group name after a letter, e.g. BLNCNET; group bulletins use a digit (APRS12c ch. 14)."""
    FREE_TEXT_CAPABILITIES = "free-text-capabilities"
    """A < station capabilities packet holds free text rather than TOKEN / TOKEN=VALUE items (APRS12c ch. 15)."""

    def __str__(self) -> str:
        return self.value

    @property
    def tolerable(self) -> bool:
        """Whether a lenient decoder may accept this defect with a warning."""
        return self in _TOLERABLE

    @property
    def meaning(self) -> str:
        """What the code means, in one sentence."""
        return _MEANINGS[self]


_TOLERABLE: frozenset[DiagnosticCode] = frozenset(
    {
        DiagnosticCode.EMPTY_DESTINATION,
        DiagnosticCode.EMPTY_PATH_ENTRY,
        DiagnosticCode.MULTIPLE_USED_MARKERS,
        DiagnosticCode.NUL_PADDED_ADDRESS,
        DiagnosticCode.INVALID_AX25_ADDRESS_CHARACTERS,
        DiagnosticCode.TRAILING_LINE_BREAK,
        DiagnosticCode.NON_UTF8_TEXT,
        DiagnosticCode.OUT_OF_RANGE_VALUE,
        DiagnosticCode.INVALID_TIMESTAMP,
        DiagnosticCode.LOWERCASE_HEMISPHERE,
        DiagnosticCode.DAO_WITH_AMBIGUITY,
        DiagnosticCode.DATA_EXTENSION_IN_COMMENT,
        DiagnosticCode.OBJECT_NAME_NOT_PADDED,
        DiagnosticCode.OBJECT_WITHOUT_TIMESTAMP,
        DiagnosticCode.INCOMPLETE_WEATHER,
        DiagnosticCode.WEATHER_COMMENT,
        DiagnosticCode.KENWOOD_FF_PADDING,
        DiagnosticCode.UNPADDED_ADDRESSEE,
        DiagnosticCode.MESSAGE_ID_ON_ACK,
        DiagnosticCode.INVALID_TELEMETRY,
        DiagnosticCode.MISSING_SPACE_AFTER_LOCATOR,
        DiagnosticCode.COMPRESSION_TYPE_RESERVED_BITS,
        DiagnosticCode.MALFORMED_TIMESTAMP,
        DiagnosticCode.POSITION_NOT_AT_START,
        DiagnosticCode.NON_STANDARD_WEATHER_FIELD_WIDTH,
        DiagnosticCode.WIND_FIELDS_INSTEAD_OF_EXTENSION,
        DiagnosticCode.WIND_EXTENSION_AFTER_COMPRESSED,
        DiagnosticCode.MIC_E_ALTITUDE_NOT_FIRST,
        DiagnosticCode.BRACE_IN_MESSAGE_TEXT,
        DiagnosticCode.INVALID_ADDRESSEE_CHARACTERS,
        DiagnosticCode.LETTER_GROUP_BULLETIN,
        DiagnosticCode.FREE_TEXT_CAPABILITIES,
    }
)

_MEANINGS: dict[DiagnosticCode, str] = {
    DiagnosticCode.INVALID_HEADER: "The TNC2 header is not SOURCE>DEST[,PATH]:.",
    DiagnosticCode.INVALID_ADDRESS: "An address is empty, too long, or has characters that cannot appear in one.",
    DiagnosticCode.EMPTY_DESTINATION: "The destination address is empty (UAP 5.2).",
    DiagnosticCode.EMPTY_PATH_ENTRY: "The digipeater path has an empty entry (UAP 5.6).",
    DiagnosticCode.MULTIPLE_USED_MARKERS: "More than one path entry is marked used with *; only the last used one should be (UAP 5.30).",
    DiagnosticCode.NOT_APRS_FRAME: "The AX.25 frame is not a UI frame with PID 0xF0, or is too short (APRS12c ch. 3).",
    DiagnosticCode.NUL_PADDED_ADDRESS: "An AX.25 address is padded with NUL rather than spaces (UAP 5.29).",
    DiagnosticCode.INVALID_AX25_ADDRESS_CHARACTERS: "An AX.25 address has characters other than upper-case letters and digits.",
    DiagnosticCode.TOO_MANY_DIGIPEATERS: "The AX.25 frame has more than 8 digipeater addresses.",
    DiagnosticCode.TRAILING_LINE_BREAK: "The information field ends with CR or LF (APRS12c ch. 5, UAP 5.13).",
    DiagnosticCode.NON_UTF8_TEXT: "Text that is not valid UTF-8 (UAP 5.16).",
    DiagnosticCode.TRUNCATED: "The information field is shorter than its format requires.",
    DiagnosticCode.NOT_APRS: "The first byte is not a data type identifier (APRS12c ch. 20).",
    DiagnosticCode.RESERVED_DATA_TYPE: "A reserved data type identifier with no defined format (APRS12c ch. 5).",
    DiagnosticCode.OBSOLETE_FORMAT: "A format the spec marks obsolete or not recommended, e.g. raw NMEA or raw weather.",
    DiagnosticCode.OUT_OF_RANGE_VALUE: "A value in a well-formed field is out of range and was dropped.",
    DiagnosticCode.INVALID_TIMESTAMP: "A timestamp is malformed or out of range (APRS12c ch. 6, UAP 5.8).",
    DiagnosticCode.INVALID_POSITION: "The position is missing or starts with something that cannot begin one.",
    DiagnosticCode.INVALID_LATITUDE: "The latitude is malformed (APRS12c ch. 6, UAP 5.7).",
    DiagnosticCode.INVALID_LONGITUDE: "The longitude is malformed (APRS12c ch. 6, UAP 5.7).",
    DiagnosticCode.LOWERCASE_HEMISPHERE: "A lower-case hemisphere letter (UAP 5.9).",
    DiagnosticCode.INVALID_SYMBOL_TABLE: "The symbol table identifier is not /, \\, 0-9 or A-Z.",
    DiagnosticCode.INVALID_SYMBOL_CODE: "The symbol code is not printable ASCII.",
    DiagnosticCode.INVALID_COMPRESSED_POSITION: "A compressed position is malformed (APRS12c ch. 9).",
    DiagnosticCode.DAO_WITH_AMBIGUITY: "A !DAO! adds precision to an ambiguous position, which contradicts it.",
    DiagnosticCode.DATA_EXTENSION_IN_COMMENT: "A data extension (PHG, RNG, DFS) appears later in the comment (UAP 5.15).",
    DiagnosticCode.INVALID_OBJECT_NAME: "The object name is empty or not printable ASCII.",
    DiagnosticCode.OBJECT_NAME_NOT_PADDED: "The object name is not padded to 9 characters.",
    DiagnosticCode.OBJECT_WITHOUT_TIMESTAMP: "An object report has no timestamp (APRS12c ch. 11).",
    DiagnosticCode.INVALID_ITEM_NAME: "The item name is not 3-9 printable characters followed by ! or _.",
    DiagnosticCode.INCOMPLETE_WEATHER: "A weather report lacks a mandatory field (APRS12c ch. 12).",
    DiagnosticCode.WEATHER_COMMENT: "Text after the weather data; weather reports have no comment (UAP 2.7.1, ch. 5.33).",
    DiagnosticCode.INVALID_WEATHER: "Positionless or raw weather data that could not be decoded.",
    DiagnosticCode.INVALID_MIC_E_DESTINATION: "The destination address is not a valid Mic-E encoding (APRS12c ch. 10).",
    DiagnosticCode.INVALID_MIC_E_INFORMATION: "The Mic-E information field is malformed (APRS12c ch. 10).",
    DiagnosticCode.KENWOOD_FF_PADDING: "Kenwood TM-D710 0xFF padding was removed (UAP 5.10).",
    DiagnosticCode.MIC_E_MISSING_DEVICE_TYPE: "A Mic-E report without a device type prefix (UAP 5.4).",
    DiagnosticCode.INVALID_MESSAGE: "A message is malformed (APRS12c ch. 14).",
    DiagnosticCode.UNPADDED_ADDRESSEE: "The addressee is not padded to 9 characters.",
    DiagnosticCode.MESSAGE_ID_ON_ACK: "An ack or rej carries a message ID of its own (UAP 5.32).",
    DiagnosticCode.INVALID_TELEMETRY_METADATA: "A telemetry metadata message (PARM/UNIT/EQNS/BITS) is malformed (APRS12c ch. 13).",
    DiagnosticCode.INVALID_QUERY: "A directed query is malformed (APRS12c ch. 15, UAP 5.18).",
    DiagnosticCode.INVALID_TELEMETRY: "A telemetry report is malformed (APRS12c ch. 13).",
    DiagnosticCode.INVALID_STATUS: "A status report is malformed (APRS12c ch. 16).",
    DiagnosticCode.INVALID_LOCATOR: "A Maidenhead locator is malformed.",
    DiagnosticCode.INVALID_NMEA: "An NMEA sentence is malformed.",
    DiagnosticCode.NMEA_CHECKSUM_MISMATCH: "An NMEA sentence's checksum does not match, so the sentence is corrupt and is not decoded.",
    DiagnosticCode.INVALID_THIRD_PARTY: "A third-party header is malformed (APRS12c ch. 17).",
    DiagnosticCode.INVALID_GENERAL_QUERY: "A general query is malformed (APRS12c ch. 15).",
    DiagnosticCode.INVALID_CAPABILITIES: "A station capabilities report is malformed (APRS12c ch. 15).",
    DiagnosticCode.INVALID_USER_DEFINED: "A user-defined packet is shorter than its 3-byte header (APRS12c ch. 19).",
    DiagnosticCode.INVALID_AGRELO_DF: "An Agrelo DF report is malformed.",
    DiagnosticCode.MISSING_SPACE_AFTER_LOCATOR: "A grid-locator status report lacks the mandatory space before its text (UAP 5.17).",
    DiagnosticCode.COMPRESSION_TYPE_RESERVED_BITS: "A compressed position's type byte sets its unused high bits (APRS12c ch. 9).",
    DiagnosticCode.MALFORMED_TIMESTAMP: "A timestamped position report whose timestamp is missing or not timestamp-shaped (UAP 5.8).",
    DiagnosticCode.POSITION_NOT_AT_START: "A ! position found after other text (obsolete TNC beacon rule).",
    DiagnosticCode.NON_STANDARD_WEATHER_FIELD_WIDTH: "A weather field is one character shorter or longer than its fixed width (UAP 5.31).",
    DiagnosticCode.WIND_FIELDS_INSTEAD_OF_EXTENSION: "Wind sent as c/s fields in a position weather report instead of the DDD/SSS extension, or after a compressed position whose cs bytes carry no wind.",
    DiagnosticCode.WIND_EXTENSION_AFTER_COMPRESSED: "An uncompressed wind extension after a compressed weather position (UAP 5.33).",
    DiagnosticCode.MIC_E_ALTITUDE_NOT_FIRST: "A Mic-E altitude after other status text instead of first (APRS12c ch. 10).",
    DiagnosticCode.BRACE_IN_MESSAGE_TEXT: "Message text contains a { that does not start a valid message ID (APRS12c ch. 14).",
    DiagnosticCode.INVALID_ADDRESSEE_CHARACTERS: "A message addressee contains a space or : (APRS12c ch. 14).",
    DiagnosticCode.LETTER_GROUP_BULLETIN: "A bulletin addressee has a group name after a letter, e.g. BLNCNET; group bulletins use a digit (APRS12c ch. 14).",
    DiagnosticCode.FREE_TEXT_CAPABILITIES: "A < station capabilities packet holds free text rather than TOKEN / TOKEN=VALUE items (APRS12c ch. 15).",
}


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One thing a decoder noticed about a packet: a severity and a code.

    ``str(diagnostic)`` gives the conformance vectors' form, ``severity:code``.
    """

    severity: Severity
    code: DiagnosticCode

    def __str__(self) -> str:
        return f"{self.severity.value}:{self.code.value}"

    @classmethod
    def parse(cls, text: str) -> Diagnostic:
        """Read the ``severity:code`` form, e.g. ``warning:unpadded-addressee``."""
        severity, sep, code = text.partition(":")
        if not sep:
            raise ValueError(f"not severity:code: {text!r}")
        return cls(Severity(severity), DiagnosticCode(code))


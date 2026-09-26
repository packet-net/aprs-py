"""The decoded APRS data: one frozen dataclass per data type, and the values they are made of.

Field names follow the conformance vectors' neutral form: snake_case, with the unit in the name
(``speed_knots``, ``altitude_feet``, ``temperature_f``). Quantities keep the units APRS sends;
nothing is converted. A field that was not sent is ``None`` (or ``""``, ``()`` or ``False``).
"""

from __future__ import annotations

import math
from dataclasses import MISSING, dataclass, field, fields
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

from .symbols import Symbol

if TYPE_CHECKING:
    from .packet import Packet

__all__ = [
    "Ack",
    "AgreloDf",
    "AprsData",
    "AreaColor",
    "AreaObject",
    "AreaShape",
    "Beam",
    "Bulletin",
    "Capabilities",
    "CommentTelemetry",
    "CompressionOrigin",
    "CompressionType",
    "Dao",
    "DaoPrecision",
    "DfBearing",
    "Dfs",
    "DirectedQuery",
    "Fix",
    "Footprint",
    "ItemReport",
    "MaidenheadBeacon",
    "Message",
    "MicEMessage",
    "MicEReport",
    "NmeaFix",
    "NmeaSentence",
    "NmeaSource",
    "NwsBulletin",
    "ObjectReport",
    "Phg",
    "PositionReport",
    "PositionedData",
    "PositionlessWeather",
    "Query",
    "RawWeather",
    "RawWeatherFormat",
    "Reject",
    "StatusReport",
    "Storm",
    "StormType",
    "TelemetryBits",
    "TelemetryCoefficients",
    "TelemetryNames",
    "TelemetryReport",
    "TelemetryUnits",
    "TestData",
    "ThirdParty",
    "Timestamp",
    "TimestampKind",
    "ToneType",
    "Unrecognized",
    "UnrecognizedReason",
    "UserDefined",
    "VoiceFrequency",
    "Weather",
    "WeatherExtra",
]


def _compact_repr(self: object) -> str:
    """The class name and the fields that differ from their defaults."""
    parts = []
    for f in fields(self):  # type: ignore[arg-type]
        if not f.repr:
            continue
        value = getattr(self, f.name)
        if f.default is not MISSING and value == f.default and type(value) is type(f.default):
            continue
        if f.default_factory is not MISSING and value == f.default_factory():
            continue
        parts.append(f"{f.name}={value!r}")
    return f"{type(self).__name__}({', '.join(parts)})"


class _Enum(str, Enum):
    def __str__(self) -> str:
        return str(self.value)


# ---------------------------------------------------------------- enumerations


class Fix(_Enum):
    """Compression type: whether the GPS fix is current."""

    OLD = "old"
    CURRENT = "current"


class NmeaSource(_Enum):
    """Compression type: the NMEA sentence the position came from."""

    OTHER = "other"
    GLL = "gll"
    GGA = "gga"
    RMC = "rmc"


class CompressionOrigin(_Enum):
    """Compression type: what compressed the position."""

    COMPRESSED = "compressed"
    TNC_BEACON_TEXT = "tnc-beacon-text"
    SOFTWARE = "software"
    RESERVED3 = "reserved3"
    KPC3 = "kpc3"
    PICO = "pico"
    OTHER_TRACKER = "other-tracker"
    DIGIPEATER_CONVERSION = "digipeater-conversion"


class AreaShape(_Enum):
    """An area object's shape (codes 0-9)."""

    OPEN_CIRCLE = "open-circle"
    LINE_DOWN_RIGHT = "line-down-right"
    OPEN_ELLIPSE = "open-ellipse"
    OPEN_TRIANGLE = "open-triangle"
    OPEN_BOX = "open-box"
    FILLED_CIRCLE = "filled-circle"
    LINE_DOWN_LEFT = "line-down-left"
    FILLED_ELLIPSE = "filled-ellipse"
    FILLED_TRIANGLE = "filled-triangle"
    FILLED_BOX = "filled-box"

    @property
    def code(self) -> int:
        """The shape's code, 0-9."""
        return list(AreaShape).index(self)


class AreaColor(_Enum):
    """An area object's colour: codes /0-/7 high intensity, /8, /9 and 10-15 low."""

    BLACK = "black"
    BLUE = "blue"
    GREEN = "green"
    CYAN = "cyan"
    RED = "red"
    VIOLET = "violet"
    YELLOW = "yellow"
    GRAY = "gray"
    BLACK_LOW = "black-low"
    BLUE_LOW = "blue-low"
    GREEN_LOW = "green-low"
    CYAN_LOW = "cyan-low"
    RED_LOW = "red-low"
    VIOLET_LOW = "violet-low"
    YELLOW_LOW = "yellow-low"
    GRAY_LOW = "gray-low"

    @property
    def code(self) -> int:
        """The colour's code, 0-15."""
        return list(AreaColor).index(self)


class StormType(_Enum):
    """The kind of storm in storm data."""

    TROPICAL_STORM = "tropical-storm"
    HURRICANE = "hurricane"
    TROPICAL_DEPRESSION = "tropical-depression"


class MicEMessage(_Enum):
    """A Mic-E report's position comment (message) type."""

    OFF_DUTY = "off-duty"
    EN_ROUTE = "en-route"
    IN_SERVICE = "in-service"
    RETURNING = "returning"
    COMMITTED = "committed"
    SPECIAL = "special"
    PRIORITY = "priority"
    CUSTOM0 = "custom0"
    CUSTOM1 = "custom1"
    CUSTOM2 = "custom2"
    CUSTOM3 = "custom3"
    CUSTOM4 = "custom4"
    CUSTOM5 = "custom5"
    CUSTOM6 = "custom6"
    EMERGENCY = "emergency"
    UNKNOWN = "unknown"
    """The message bits mix standard and custom ones, which has no defined meaning."""


class DaoPrecision(_Enum):
    """How much precision a ``!DAO!`` adds."""

    NONE = "none"
    THOUSANDTHS = "thousandths"
    BASE91 = "base91"


class ToneType(_Enum):
    """A voice frequency's tone (APRS12c ch. 18)."""

    OFF = "off"
    TONE = "tone"
    CTCSS = "ctcss"
    DCS = "dcs"
    TONE_BURST = "tone-burst"
    """A 1750 Hz tone burst; there is no ``tone_value``."""


class RawWeatherFormat(_Enum):
    """The weather station format of a raw weather report."""

    PEET_BROS_HASH = "peet-bros-hash"
    PEET_BROS_STAR = "peet-bros-star"
    ULTIMETER_PACKET = "ultimeter-packet"
    ULTIMETER_LOGGING = "ultimeter-logging"


class UnrecognizedReason(_Enum):
    """Why nothing was decoded."""

    EMPTY = "empty"
    NOT_APRS = "not-aprs"
    RESERVED_DATA_TYPE = "reserved-data-type"
    MALFORMED = "malformed"


class NmeaFix(_Enum):
    """Whether an NMEA sentence says the receiver has a fix."""

    VALID = "valid"
    INVALID = "invalid"


class TimestampKind(_Enum):
    """The four timestamp formats (APRS12c ch. 6)."""

    DHM_ZULU = "dhm-zulu"
    """Day, hour and minute, UTC: ``092345z``."""
    DHM_LOCAL = "dhm-local"
    """Day, hour and minute, local time: ``092345/``."""
    HMS = "hms"
    """Hour, minute and second, UTC: ``234517h``."""
    MDHM = "mdhm"
    """Month, day, hour and minute, UTC (positionless weather only): ``10092345``."""


# ---------------------------------------------------------------- values


@dataclass(frozen=True, slots=True)
class Timestamp:
    """A timestamp, kept as it was sent (``092345z``, ``092345/``, ``234517h``, ``10090556``).

    A decoder keeps a timestamp whose values are out of range (with an ``invalid-timestamp``
    warning), so ``is_valid`` can be false.
    """

    text: str

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return f"Timestamp({self.text!r})"

    @classmethod
    def dhm(cls, day: int, hour: int, minute: int, *, zulu: bool = True) -> Timestamp:
        """Day/hour/minute, UTC (``z``) or local (``/``)."""
        return cls(f"{day:02d}{hour:02d}{minute:02d}{'z' if zulu else '/'}")

    @classmethod
    def hms(cls, hour: int, minute: int, second: int) -> Timestamp:
        """Hour/minute/second, UTC."""
        return cls(f"{hour:02d}{minute:02d}{second:02d}h")

    @classmethod
    def mdhm(cls, month: int, day: int, hour: int, minute: int) -> Timestamp:
        """Month/day/hour/minute, UTC, for positionless weather reports."""
        return cls(f"{month:02d}{day:02d}{hour:02d}{minute:02d}")

    @property
    def kind(self) -> TimestampKind | None:
        """The format, or ``None`` if the text is not timestamp-shaped."""
        t = self.text
        if len(t) == 8 and t.isascii() and t.isdigit():
            return TimestampKind.MDHM
        if len(t) == 7 and t[:6].isascii() and t[:6].isdigit():
            return {
                "z": TimestampKind.DHM_ZULU,
                "/": TimestampKind.DHM_LOCAL,
                "h": TimestampKind.HMS,
            }.get(t[6])
        return None

    def _part(self, i: int) -> int:
        return int(self.text[i : i + 2])

    @property
    def month(self) -> int | None:
        return self._part(0) if self.kind is TimestampKind.MDHM else None

    @property
    def day(self) -> int | None:
        k = self.kind
        if k is TimestampKind.MDHM:
            return self._part(2)
        if k in (TimestampKind.DHM_ZULU, TimestampKind.DHM_LOCAL):
            return self._part(0)
        return None

    @property
    def hour(self) -> int | None:
        k = self.kind
        if k is TimestampKind.MDHM:
            return self._part(4)
        if k in (TimestampKind.DHM_ZULU, TimestampKind.DHM_LOCAL):
            return self._part(2)
        if k is TimestampKind.HMS:
            return self._part(0)
        return None

    @property
    def minute(self) -> int | None:
        k = self.kind
        if k is TimestampKind.MDHM:
            return self._part(6)
        if k in (TimestampKind.DHM_ZULU, TimestampKind.DHM_LOCAL):
            return self._part(4)
        if k is TimestampKind.HMS:
            return self._part(2)
        return None

    @property
    def second(self) -> int | None:
        return self._part(4) if self.kind is TimestampKind.HMS else None

    @property
    def is_valid(self) -> bool:
        """True when the text is a timestamp whose values are in range."""
        k = self.kind
        if k is None:
            return False
        hour, minute = self.hour, self.minute
        if hour is None or minute is None or hour > 23 or minute > 59:
            return False
        if k is TimestampKind.HMS:
            second = self.second
            return second is not None and second <= 59
        day = self.day
        if day is None or not 1 <= day <= 31:
            return False
        if k is TimestampKind.MDHM:
            month = self.month
            return month is not None and 1 <= month <= 12
        return True


@dataclass(frozen=True, slots=True)
class CompressionType:
    """A compressed position's type byte: GPS fix, NMEA source and compression origin."""

    fix: Fix = Fix.CURRENT
    source: NmeaSource = NmeaSource.OTHER
    origin: CompressionOrigin = CompressionOrigin.SOFTWARE

    @property
    def value(self) -> int:
        """The type byte's value, 0-63 (before 33 is added)."""
        return (
            (32 if self.fix is Fix.CURRENT else 0)
            | (list(NmeaSource).index(self.source) << 3)
            | list(CompressionOrigin).index(self.origin)
        )

    @classmethod
    def from_value(cls, value: int) -> CompressionType:
        """From the type byte's value; the two unused high bits are ignored."""
        return cls(
            Fix.CURRENT if value & 32 else Fix.OLD,
            list(NmeaSource)[(value >> 3) & 3],
            list(CompressionOrigin)[value & 7],
        )


@dataclass(frozen=True, slots=True)
class Phg:
    """Power, effective antenna height, gain and directivity codes (``PHGphgd``).

    The codes are as sent; the ``*_watts``/``*_feet``/``*_dbi``/``*_degrees`` properties give
    the quantities they stand for. ``height`` runs past 9 (``:`` is 10 and so on).
    ``beacons_per_hour`` is the PHGR rate, when sent.
    """

    power: int
    height: int
    gain: int
    directivity: int
    beacons_per_hour: int | None = None

    @property
    def power_watts(self) -> int:
        return self.power * self.power

    @property
    def height_feet(self) -> int:
        return int(10 * 2**self.height)

    @property
    def gain_dbi(self) -> int:
        return self.gain

    @property
    def directivity_degrees(self) -> int | None:
        """The direction of maximum gain, or ``None`` for omni."""
        return None if self.directivity == 0 else self.directivity * 45

    @property
    def range_miles(self) -> float:
        """The radio range the spec computes from these codes (APRS12c ch. 7)."""
        gain = 10 ** (self.gain / 10)
        return math.sqrt(2 * self.height_feet * math.sqrt((self.power_watts / 10) * (gain / 2)))


@dataclass(frozen=True, slots=True)
class Dfs:
    """Omni-DF signal strength and antenna codes (``DFSshgd``), as sent."""

    strength: int
    height: int
    gain: int
    directivity: int


@dataclass(frozen=True, slots=True)
class AreaObject:
    """An area object's descriptor (``Tyy/Cxx``) and, for lines, the corridor width.

    ``lat_offset`` and ``lon_offset`` are ``yy`` and ``xx`` as sent; the offset in degrees is
    the square divided by 1500 (see ``lat_offset_degrees``).
    """

    shape: AreaShape
    color: AreaColor
    lat_offset: int
    lon_offset: int
    corridor_width_miles: int | None = None

    @property
    def lat_offset_degrees(self) -> float:
        return self.lat_offset**2 / 1500

    @property
    def lon_offset_degrees(self) -> float:
        return self.lon_offset**2 / 1500


@dataclass(frozen=True, slots=True)
class DfBearing:
    """A DF report's bearing and number/range/quality (``/BRG/NRQ``)."""

    bearing_degrees: int
    number: int
    range: int
    quality: int


@dataclass(frozen=True, slots=True, repr=False)
class Storm:
    """Storm data (APRS12c ch. 12)."""

    __repr__ = _compact_repr

    type: StormType
    sustained_wind_knots: int | None = None
    gust_knots: int | None = None
    central_pressure_mbar: int | None = None
    hurricane_radius_nm: int | None = None
    tropical_storm_radius_nm: int | None = None
    whole_gale_radius_nm: int | None = None


@dataclass(frozen=True, slots=True)
class Dao:
    """A ``!DAO!`` precision and datum extension. Its precision is already in the position."""

    datum: str
    precision: DaoPrecision


@dataclass(frozen=True, slots=True)
class CommentTelemetry:
    """Base-91 telemetry from a comment (``|ss11|``): sequence, 1-5 analog values, digital."""

    sequence: int
    analog: tuple[int, ...]
    digital: int | None = None


@dataclass(frozen=True, slots=True, repr=False)
class VoiceFrequency:
    """A voice frequency in a comment (APRS12c ch. 18): ``146.520MHz T100 -060 R25m``.

    ``offset_khz`` is the transmit offset (sent in tens of kHz); ``range`` is in miles, or in
    kilometres when ``range_km``. ``narrow`` is set by a lower-case tone letter.
    ``ten_khz_resolution`` records the ``FFF.FF MHz`` form.
    """

    __repr__ = _compact_repr

    mhz: float
    tone: ToneType | None = None
    tone_value: int | None = None
    offset_khz: int | None = None
    range: int | None = None
    range_km: bool = False
    narrow: bool = False
    ten_khz_resolution: bool = False


@dataclass(frozen=True, slots=True)
class WeatherExtra:
    """A weather field whose letter the spec does not define, kept as sent (``X01``)."""

    letter: str
    value: str


@dataclass(frozen=True, slots=True, repr=False)
class Weather:
    """Weather data, in the units sent. A field left ``None`` was not sent, or sent as unknown."""

    __repr__ = _compact_repr

    wind_direction_degrees: int | None = None
    wind_speed_mph: float | None = None
    wind_gust_mph: float | None = None
    temperature_f: float | None = None
    rain_1h_in: float | None = None
    rain_24h_in: float | None = None
    rain_midnight_in: float | None = None
    rain_raw: int | None = None
    humidity_percent: int | None = None
    pressure_mbar: float | None = None
    luminosity_w_m2: int | None = None
    snow_24h_in: float | None = None
    software: str | None = None
    unit: str | None = None
    extra: tuple[WeatherExtra, ...] = ()


@dataclass(frozen=True, slots=True)
class Beam:
    """A status report's meteor scatter beam heading and ERP codes (``^B7``)."""

    heading_code: str
    power_code: str

    @property
    def heading_degrees(self) -> int | None:
        c = self.heading_code
        if c.isdigit():
            return int(c) * 10
        if "A" <= c <= "Z":
            return (ord(c) - ord("A") + 10) * 10
        return None


@dataclass(frozen=True, slots=True)
class Footprint:
    """A general query's target footprint."""

    latitude: float
    longitude: float
    radius_miles: int


# ---------------------------------------------------------------- data types


@dataclass(frozen=True, slots=True, repr=False)
class AprsData:
    """Base class of every decoded data type. ``kind`` is the neutral form's ``type``."""

    kind: ClassVar[str] = ""

    __repr__ = _compact_repr


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class PositionedData(AprsData):
    """The fields positions, Mic-E reports, objects and items share.

    ``latitude`` and ``longitude`` are degrees, north and east positive, with any ``!DAO!``
    precision applied; an ambiguous position gives the centre of its box, and ``ambiguity``
    says how many digits were blanked (0-4). The data extensions and the elements lifted out
    of the comment (altitude, telemetry, frequency...) each have a field; ``comment`` is the
    free text left over.
    """

    latitude: float
    longitude: float
    symbol: Symbol
    ambiguity: int = 0
    compressed: bool = False
    compression: CompressionType | None = None
    course_degrees: int | None = None
    speed_knots: float | None = None
    altitude_feet: float | None = None
    phg: Phg | None = None
    range_miles: float | None = None
    dfs: Dfs | None = None
    area: AreaObject | None = None
    df_bearing: DfBearing | None = None
    storm: Storm | None = None
    dao: Dao | None = None
    telemetry: CommentTelemetry | None = None
    frequency: VoiceFrequency | None = None
    weather: Weather | None = None
    signpost: str | None = None
    comment: str = ""


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class PositionReport(PositionedData):
    """A position report (``!``, ``=``, ``/``, ``@``). ``messaging``: the station can message."""

    kind: ClassVar[str] = "position"
    timestamp: Timestamp | None = None
    messaging: bool = False


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class MicEReport(PositionedData):
    """A Mic-E report, whose position is split between the destination and the information.

    ``type_code`` is the device type byte after the symbol (`` ` ``, ``'``, ``>``, ``]`` or a
    space) and ``device_suffix`` the device's suffix at the end, both lifted out of the
    comment. ``old_data`` is set by the ``'`` data type. ``destination_ssid`` is the
    destination address's SSID, which an encoder writes back.
    """

    kind: ClassVar[str] = "mic-e"
    mic_e_message: MicEMessage = MicEMessage.OFF_DUTY
    old_data: bool = False
    type_code: str | None = None
    device_suffix: str | None = None
    locator: str | None = None
    legacy_telemetry: tuple[int, ...] = ()
    destination_ssid: int = 0


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class ObjectReport(PositionedData):
    """An object report (``;``). ``killed``: the object has been removed."""

    kind: ClassVar[str] = "object"
    name: str
    killed: bool = False
    timestamp: Timestamp | None = None


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class ItemReport(PositionedData):
    """An item report (``)``). ``killed``: the item has been removed."""

    kind: ClassVar[str] = "item"
    name: str
    killed: bool = False


@dataclass(frozen=True, slots=True, repr=False)
class Message(AprsData):
    """A message to one station. ``message_id`` asks for an ack; ``reply_ack`` is the
    reply-ack for the other station's message (``""``: reply-ack capable, nothing to ack)."""

    kind: ClassVar[str] = "message"
    addressee: str
    text: str
    message_id: str | None = None
    reply_ack: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class Ack(AprsData):
    """An acknowledgement of message ``acked_id``."""

    kind: ClassVar[str] = "ack"
    addressee: str
    acked_id: str
    reply_ack: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class Reject(AprsData):
    """A rejection of message ``rejected_id``."""

    kind: ClassVar[str] = "reject"
    addressee: str
    rejected_id: str
    reply_ack: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class Bulletin(AprsData):
    """A bulletin, announcement or group bulletin (addressee ``BLN...``)."""

    kind: ClassVar[str] = "bulletin"
    addressee: str
    text: str
    message_id: str | None = None

    @property
    def identifier(self) -> str:
        """The bulletin or announcement identifier: the character after ``BLN``."""
        return self.addressee[3:4]

    @property
    def group(self) -> str:
        """A group bulletin's group name, or ``""``."""
        return self.addressee[4:]

    @property
    def is_announcement(self) -> bool:
        return self.identifier.isalpha() and not self.group


@dataclass(frozen=True, slots=True, repr=False)
class NwsBulletin(AprsData):
    """A National Weather Service bulletin (addressee ``NWS-...``)."""

    kind: ClassVar[str] = "nws-bulletin"
    addressee: str
    text: str
    message_id: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class TelemetryNames(AprsData):
    """Telemetry parameter names (``PARM.``), sent as a message to the telemetry station."""

    kind: ClassVar[str] = "telemetry-names"
    addressee: str
    names: tuple[str, ...]
    message_id: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class TelemetryUnits(AprsData):
    """Telemetry units and labels (``UNIT.``)."""

    kind: ClassVar[str] = "telemetry-units"
    addressee: str
    units: tuple[str, ...]
    message_id: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class TelemetryCoefficients(AprsData):
    """Telemetry equation coefficients (``EQNS.``): a, b, c for each analog channel in turn.

    ``coefficients_text`` keeps the numbers as sent (``.53``), so they can be written back
    byte for byte; it is optional when encoding.
    """

    kind: ClassVar[str] = "telemetry-coefficients"
    addressee: str
    coefficients: tuple[float, ...]
    message_id: str | None = None
    coefficients_text: tuple[str, ...] = field(default=(), compare=False, repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class TelemetryBits(AprsData):
    """Telemetry bit sense and project title (``BITS.``)."""

    kind: ClassVar[str] = "telemetry-bits"
    addressee: str
    bits: str
    project: str = ""
    message_id: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class DirectedQuery(AprsData):
    """A query sent as a message to one station (``?APRSP``, ``?APRSHN0QBF``...)."""

    kind: ClassVar[str] = "directed-query"
    addressee: str
    query_type: str
    target: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class StatusReport(AprsData):
    """A status report (``>``), optionally with a timestamp, or a grid locator and symbol."""

    kind: ClassVar[str] = "status"
    text: str = ""
    timestamp: Timestamp | None = None
    locator: str | None = None
    symbol: Symbol | None = None
    beam: Beam | None = None


@dataclass(frozen=True, slots=True, repr=False)
class TelemetryReport(AprsData):
    """A telemetry report (``T#``). ``analog`` values are ``None`` for an empty channel.

    ``sequence`` is kept as sent, and ``analog_text`` keeps the values as sent (``073``), so
    they can be written back byte for byte; it is optional when encoding.
    """

    kind: ClassVar[str] = "telemetry"
    sequence: str
    analog: tuple[float | None, ...]
    bits: str | None = None
    comment: str = ""
    analog_text: tuple[str, ...] = field(default=(), compare=False, repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class PositionlessWeather(AprsData):
    """A positionless weather report (``_``), with its month/day/hour/minute timestamp."""

    kind: ClassVar[str] = "weather"
    timestamp: Timestamp
    weather: Weather
    comment: str = ""


@dataclass(frozen=True, slots=True, repr=False)
class RawWeather(AprsData):
    """Raw weather station data, kept as text (obsolete formats)."""

    kind: ClassVar[str] = "raw-weather"
    format: RawWeatherFormat
    data: str = ""


@dataclass(frozen=True, slots=True, repr=False)
class NmeaSentence(AprsData):
    """A raw NMEA sentence (``$``), without the ``$``, and what could be read from it."""

    kind: ClassVar[str] = "nmea"
    sentence: str
    has_checksum: bool = False
    latitude: float | None = None
    longitude: float | None = None
    fix: NmeaFix | None = None
    course_degrees: float | None = None
    speed_knots: float | None = None
    altitude_m: float | None = None
    time: str | None = None
    waypoint: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class MaidenheadBeacon(AprsData):
    """A Maidenhead locator beacon (``[IO91SX]``, obsolete)."""

    kind: ClassVar[str] = "maidenhead-beacon"
    locator: str
    comment: str = ""


@dataclass(frozen=True, slots=True, repr=False)
class Query(AprsData):
    """A general query (``?APRS?``), optionally limited to a footprint."""

    kind: ClassVar[str] = "query"
    query_type: str
    footprint: Footprint | None = None


@dataclass(frozen=True, slots=True, repr=False)
class Capabilities(AprsData):
    """Station capabilities (``<``): ``(token,)`` or ``(token, value)`` pairs, in order."""

    kind: ClassVar[str] = "capabilities"
    capabilities: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True, repr=False)
class ThirdParty(AprsData):
    """A third-party packet (``}``): another packet, carried inside this one."""

    kind: ClassVar[str] = "third-party"
    packet: Packet


@dataclass(frozen=True, slots=True, repr=False)
class UserDefined(AprsData):
    """User-defined data (``{``). ``data`` holds one code point (U+0000-U+00FF) per byte."""

    kind: ClassVar[str] = "user-defined"
    user_id: str
    packet_type: str
    data: str = ""


@dataclass(frozen=True, slots=True, repr=False)
class TestData(AprsData):
    """Invalid or test data (``,``)."""

    kind: ClassVar[str] = "test"
    __test__: ClassVar[bool] = False  # not a pytest test class
    data: str = ""


@dataclass(frozen=True, slots=True, repr=False)
class AgreloDf(AprsData):
    """An Agrelo DFJr / MicroFinder bearing (``%nnn/q``)."""

    kind: ClassVar[str] = "agrelo-df"
    bearing_degrees: int
    quality: int


@dataclass(frozen=True, slots=True, repr=False)
class Unrecognized(AprsData):
    """Nothing could be decoded; ``reason`` says why and the diagnostics say what."""

    kind: ClassVar[str] = "unrecognized"
    reason: UnrecognizedReason

"""Building the packets an application typically sends.

A :class:`Station` holds what stays the same from packet to packet (the callsign, the
digipeater path, the destination, whether the station can message, its usual symbol), and
has one method per kind of packet. Each returns a :class:`~pdn_aprs.Packet`, already
encoded; ``str(packet)`` is its TNC2 line, ``packet.to_kiss()`` its KISS frame.

>>> from pdn_aprs import Station, Symbol
>>> m0lte = Station("M0LTE-9", path="WIDE1-1", symbol=Symbol.CAR)
>>> print(m0lte.position(51.45, -0.98, course_degrees=88, speed_knots=36, comment="Mobile"))
M0LTE-9>APZ001,WIDE1-1:!5127.00N/00058.80W>088/036Mobile
>>> print(m0lte.message("G4ABC", "Hello there", message_id="1"))
M0LTE-9>APZ001,WIDE1-1::G4ABC    :Hello there{1

Quantities are in the units APRS sends: degrees, knots, feet, miles, and for weather mph,
degrees Fahrenheit, inches and millibars; each keyword has the name of the data field it fills.
Speed, altitude, temperature and rain can be given in metric units instead (``speed_kmh``,
``altitude_m``, ``temperature_c``, ``rain_1h_mm``...), and are converted.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypedDict

from ._util import FEET_PER_METRE, KMH_PER_KNOT, MM_PER_INCH, round_half_away
from .encode import DEFAULT_DESTINATION, build_packet
from .errors import EncodeError, RefusalCode
from .model import (
    Ack,
    AprsData,
    Beam,
    Bulletin,
    CommentTelemetry,
    CompressionType,
    Dao,
    DaoPrecision,
    ItemReport,
    Message,
    MicEMessage,
    MicEReport,
    ObjectReport,
    Phg,
    PositionlessWeather,
    PositionReport,
    Reject,
    StatusReport,
    TelemetryBits,
    TelemetryCoefficients,
    TelemetryNames,
    TelemetryReport,
    TelemetryUnits,
    Timestamp,
    VoiceFrequency,
    Weather,
)
from .packet import Packet
from .symbols import Symbol

__all__ = ["Station"]

TimestampLike = Timestamp | datetime | bool | None


def _timestamp(value: TimestampLike, *, hms: bool = False) -> Timestamp | None:
    """``True`` means now; a datetime is taken as UTC when naive."""
    if value is None or value is False:
        return None
    if isinstance(value, Timestamp):
        return value
    moment = datetime.now(timezone.utc) if value is True else value
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    if hms:
        return Timestamp.hms(moment.hour, moment.minute, moment.second)
    return Timestamp.dhm(moment.day, moment.hour, moment.minute)


def _either(value: float | None, metric: float | None, per_unit: float, what: str) -> float | None:
    """A quantity given in APRS's unit or in a metric one, which is divided by ``per_unit``."""
    if metric is None:
        return value
    if value is not None:
        raise EncodeError(f"give the {what} once, not in both units", RefusalCode.VALUE_GIVEN_TWICE)
    return metric / per_unit


def _frequency(value: float | VoiceFrequency | None) -> VoiceFrequency | None:
    """A frequency in MHz, or a whole :class:`VoiceFrequency` (a tone, an offset...)."""
    if value is None or isinstance(value, VoiceFrequency):
        return value
    return VoiceFrequency(float(value))


class _Extras(TypedDict):
    course_degrees: float | None
    speed_knots: float | None
    altitude_feet: float | None
    compressed: bool
    compression: CompressionType | None
    ambiguity: int
    phg: Phg | None
    range_miles: float | None
    frequency: VoiceFrequency | None
    telemetry: CommentTelemetry | None
    dao: Dao | None


def _extras(
    *,
    course_degrees: float | None,
    speed_knots: float | None,
    altitude_feet: float | None,
    speed_kmh: float | None,
    altitude_m: float | None,
    compressed: bool,
    ambiguity: int,
    phg: Phg | None,
    range_miles: float | None,
    frequency: float | VoiceFrequency | None,
    telemetry: CommentTelemetry | None,
    dao: bool,
) -> _Extras:
    """The fields a position, object or item report share, from the builder's arguments."""
    speed = _either(speed_knots, speed_kmh, KMH_PER_KNOT, "speed")
    return {
        "course_degrees": course_degrees,
        "speed_knots": speed,
        "altitude_feet": _either(altitude_feet, altitude_m, 1 / FEET_PER_METRE, "altitude"),
        "compressed": compressed,
        "compression": CompressionType() if compressed and (course_degrees is not None or speed is not None) else None,
        "ambiguity": ambiguity,
        "phg": phg,
        "range_miles": range_miles,
        "frequency": _frequency(frequency),
        "telemetry": telemetry,
        "dao": Dao("W", DaoPrecision.BASE91) if dao else None,
    }


@dataclass(frozen=True, init=False)
class Station:
    """A sending station: its callsign, path and habits, and a method for each packet it sends.

    ``path`` is the digipeater path (``"WIDE1-1,WIDE2-1"`` or a list), held as a tuple.
    ``destination`` is the tocall: use the one allocated to your application (the default,
    ``APZ001``, is experimental). ``messaging`` says whether the station can receive messages,
    which position reports and Mic-E reports announce. ``symbol`` is used when a report does not
    give one.

    Every keyword is the name of the field it fills in the data model (``course_degrees``,
    ``wind_gust_mph``...); a metric alternative changes only the unit (``speed_kmh``,
    ``altitude_m``, ``temperature_c``, ``rain_1h_mm``).

    A request the data cannot be sent as (a telemetry sequence over 999, a name too long, a
    value out of range) raises :class:`~pdn_aprs.EncodeError`. A call that cannot mean anything
    (a quantity given in both units, no symbol anywhere, a latitude without a longitude) raises
    ``ValueError``.
    """

    callsign: str
    path: tuple[str, ...]
    destination: str
    messaging: bool
    symbol: Symbol | None

    def __init__(
        self,
        callsign: str,
        path: str | Iterable[str] = (),
        destination: str = DEFAULT_DESTINATION,
        messaging: bool = False,
        symbol: Symbol | None = None,
    ) -> None:
        entries = path.split(",") if isinstance(path, str) else list(path)
        object.__setattr__(self, "callsign", callsign)
        object.__setattr__(self, "path", tuple(v.strip() for v in entries if v.strip()))
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "messaging", messaging)
        object.__setattr__(self, "symbol", symbol)

    def send(self, data: AprsData) -> Packet:
        """Any data as a packet from this station."""
        return build_packet(self.callsign, data, destination=self.destination, path=self.path)

    def _symbol(self, symbol: Symbol | None) -> Symbol:
        chosen = symbol or self.symbol
        if chosen is None:
            raise ValueError("give a symbol, here or on the Station")
        return chosen

    # ------------------------------------------------------------ positions

    def position(
        self,
        latitude: float,
        longitude: float,
        symbol: Symbol | None = None,
        *,
        comment: str = "",
        course_degrees: float | None = None,
        speed_knots: float | None = None,
        altitude_feet: float | None = None,
        speed_kmh: float | None = None,
        altitude_m: float | None = None,
        timestamp: TimestampLike = None,
        compressed: bool = False,
        ambiguity: int = 0,
        phg: Phg | None = None,
        range_miles: float | None = None,
        frequency: float | VoiceFrequency | None = None,
        telemetry: CommentTelemetry | None = None,
        dao: bool = False,
    ) -> Packet:
        """A position report. ``course_degrees`` in degrees, ``speed_knots`` in knots (or
        ``speed_kmh``), ``altitude_feet`` in feet (or ``altitude_m``).

        ``timestamp=True`` stamps it with the time now. ``dao`` adds a ``!DAO!`` for about
        a foot of precision. ``frequency`` is the voice frequency the station listens on: MHz,
        or a :class:`~pdn_aprs.VoiceFrequency` to give a tone or an offset as well.
        """
        data = PositionReport(
            latitude=latitude,
            longitude=longitude,
            symbol=self._symbol(symbol),
            timestamp=_timestamp(timestamp),
            messaging=self.messaging,
            comment=comment,
            **_extras(
                course_degrees=course_degrees,
                speed_knots=speed_knots,
                altitude_feet=altitude_feet,
                speed_kmh=speed_kmh,
                altitude_m=altitude_m,
                compressed=compressed,
                ambiguity=ambiguity,
                phg=phg,
                range_miles=range_miles,
                frequency=frequency,
                telemetry=telemetry,
                dao=dao,
            ),
        )
        return self.send(data)

    def object(
        self,
        name: str,
        latitude: float,
        longitude: float,
        symbol: Symbol | None = None,
        *,
        comment: str = "",
        killed: bool = False,
        timestamp: TimestampLike = True,
        course_degrees: float | None = None,
        speed_knots: float | None = None,
        altitude_feet: float | None = None,
        speed_kmh: float | None = None,
        altitude_m: float | None = None,
        compressed: bool = False,
        ambiguity: int = 0,
        phg: Phg | None = None,
        range_miles: float | None = None,
        frequency: float | VoiceFrequency | None = None,
        telemetry: CommentTelemetry | None = None,
        dao: bool = False,
    ) -> Packet:
        """An object report: something else's position, under a name of up to 9 characters.

        An object always has a timestamp; the default is the time now. ``killed=True``
        removes the object from other stations' maps.
        """
        stamp = _timestamp(timestamp)
        if stamp is None:
            raise EncodeError("an object always has a timestamp", RefusalCode.MISSING_FIELD)
        data = ObjectReport(
            name=name,
            killed=killed,
            timestamp=stamp,
            latitude=latitude,
            longitude=longitude,
            symbol=self._symbol(symbol),
            comment=comment,
            **_extras(
                course_degrees=course_degrees,
                speed_knots=speed_knots,
                altitude_feet=altitude_feet,
                speed_kmh=speed_kmh,
                altitude_m=altitude_m,
                compressed=compressed,
                ambiguity=ambiguity,
                phg=phg,
                range_miles=range_miles,
                frequency=frequency,
                telemetry=telemetry,
                dao=dao,
            ),
        )
        return self.send(data)

    def item(
        self,
        name: str,
        latitude: float,
        longitude: float,
        symbol: Symbol | None = None,
        *,
        comment: str = "",
        killed: bool = False,
        course_degrees: float | None = None,
        speed_knots: float | None = None,
        altitude_feet: float | None = None,
        speed_kmh: float | None = None,
        altitude_m: float | None = None,
        compressed: bool = False,
        ambiguity: int = 0,
        phg: Phg | None = None,
        range_miles: float | None = None,
        frequency: float | VoiceFrequency | None = None,
        telemetry: CommentTelemetry | None = None,
        dao: bool = False,
    ) -> Packet:
        """An item report: a named thing's position (3-9 characters), without a timestamp."""
        data = ItemReport(
            name=name,
            killed=killed,
            latitude=latitude,
            longitude=longitude,
            symbol=self._symbol(symbol),
            comment=comment,
            **_extras(
                course_degrees=course_degrees,
                speed_knots=speed_knots,
                altitude_feet=altitude_feet,
                speed_kmh=speed_kmh,
                altitude_m=altitude_m,
                compressed=compressed,
                ambiguity=ambiguity,
                phg=phg,
                range_miles=range_miles,
                frequency=frequency,
                telemetry=telemetry,
                dao=dao,
            ),
        )
        return self.send(data)

    def mic_e(
        self,
        latitude: float,
        longitude: float,
        symbol: Symbol | None = None,
        *,
        mic_e_message: MicEMessage = MicEMessage.IN_SERVICE,
        course_degrees: float | None = None,
        speed_knots: float | None = None,
        altitude_feet: float | None = None,
        speed_kmh: float | None = None,
        altitude_m: float | None = None,
        comment: str = "",
        ambiguity: int = 0,
        frequency: float | VoiceFrequency | None = None,
        telemetry: CommentTelemetry | None = None,
        dao: bool = False,
    ) -> Packet:
        """A Mic-E report: the compact position format of trackers and radios. The destination
        address carries half the position and is computed; the type code says whether this
        station can message.

        A course of 0 (or one that rounds to 0) is unknown and north is 360, as APRS has them.
        An altitude in metres goes in the Mic-E altitude bytes, whose unit is the metre, rounded
        to the metre; one in feet goes in a ``/A=``."""
        if course_degrees is not None and round_half_away(course_degrees) == 0:
            course_degrees = None
        if altitude_m is not None:
            if altitude_feet is not None:
                raise EncodeError("give the altitude once, not in both units", RefusalCode.VALUE_GIVEN_TWICE)
            feet: float | None = round_half_away(altitude_m) * FEET_PER_METRE
        else:
            feet = altitude_feet
        data = MicEReport(
            latitude=latitude,
            longitude=longitude,
            symbol=self._symbol(symbol),
            mic_e_message=mic_e_message,
            course_degrees=course_degrees,
            speed_knots=_either(speed_knots, speed_kmh, KMH_PER_KNOT, "speed") or 0,
            altitude_feet=feet,
            altitude_in_comment=altitude_feet is not None,
            comment=comment,
            ambiguity=ambiguity,
            frequency=_frequency(frequency),
            telemetry=telemetry,
            dao=Dao("W", DaoPrecision.BASE91) if dao else None,
            type_code="`" if self.messaging else "'",
        )
        return self.send(data)

    # ------------------------------------------------------------ weather

    def weather(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
        *,
        wind_direction_degrees: float | None = None,
        wind_speed_mph: float | None = None,
        wind_gust_mph: float | None = None,
        temperature_f: float | None = None,
        rain_1h_in: float | None = None,
        rain_24h_in: float | None = None,
        rain_midnight_in: float | None = None,
        humidity_percent: float | None = None,
        pressure_mbar: float | None = None,
        luminosity_w_m2: float | None = None,
        snow_24h_in: float | None = None,
        timestamp: TimestampLike = None,
        symbol: Symbol = Symbol.WEATHER_STATION,
        software: str | None = None,
        unit: str | None = None,
        temperature_c: float | None = None,
        rain_1h_mm: float | None = None,
        rain_24h_mm: float | None = None,
        rain_midnight_mm: float | None = None,
    ) -> Packet:
        """A weather report: with a position, a complete weather report (the ``_`` symbol, or the
        ``symbol`` given, an overlay say); without one, a positionless report (always timestamped,
        now by default).

        Wind in degrees and mph, temperature in degrees Fahrenheit (or ``temperature_c``), rain
        in inches (or ``rain_1h_mm`` and so on), humidity in percent, pressure in millibars,
        luminosity in W/m2, snow in inches. Each keyword is the name of the field it fills in
        :class:`~pdn_aprs.Weather`.
        """
        if temperature_c is not None:
            if temperature_f is not None:
                raise EncodeError("give the temperature once, not in both units", RefusalCode.VALUE_GIVEN_TWICE)
            temperature_f = temperature_c * 9 / 5 + 32
        if symbol != Symbol.WEATHER_STATION and (latitude is None or longitude is None):
            raise EncodeError("a positionless weather report has no symbol", RefusalCode.SYMBOL_MISMATCH)
        weather = Weather(
            wind_direction_degrees=wind_direction_degrees,
            wind_speed_mph=wind_speed_mph,
            wind_gust_mph=wind_gust_mph,
            temperature_f=temperature_f,
            rain_1h_in=_either(rain_1h_in, rain_1h_mm, MM_PER_INCH, "rain in the last hour"),
            rain_24h_in=_either(rain_24h_in, rain_24h_mm, MM_PER_INCH, "rain in the last 24 hours"),
            rain_midnight_in=_either(rain_midnight_in, rain_midnight_mm, MM_PER_INCH, "rain since midnight"),
            humidity_percent=humidity_percent,
            pressure_mbar=pressure_mbar,
            luminosity_w_m2=luminosity_w_m2,
            snow_24h_in=snow_24h_in,
            software=software,
            unit=unit,
        )
        if latitude is None or longitude is None:
            if latitude is not None or longitude is not None:
                raise EncodeError("give both latitude and longitude, or neither", RefusalCode.MISSING_FIELD)
            moment = timestamp if isinstance(timestamp, datetime) else datetime.now(timezone.utc)
            if moment.tzinfo is not None:
                moment = moment.astimezone(timezone.utc)
            stamp = (
                timestamp
                if isinstance(timestamp, Timestamp)
                else Timestamp.mdhm(moment.month, moment.day, moment.hour, moment.minute)
            )
            return self.send(PositionlessWeather(stamp, weather))
        data = PositionReport(
            latitude=latitude,
            longitude=longitude,
            symbol=symbol,
            timestamp=_timestamp(timestamp),
            messaging=self.messaging,
            weather=weather,
        )
        return self.send(data)

    # ------------------------------------------------------------ messages

    def message(
        self, addressee: str, text: str, *, message_id: str | None = None, reply_ack: str | None = None
    ) -> Packet:
        """A message to one station. Give a ``message_id`` to ask for an acknowledgement."""
        return self.send(Message(addressee, text, message_id, reply_ack))

    def ack(self, addressee: str, message_id: str) -> Packet:
        """Acknowledge message ``message_id`` from ``addressee``."""
        return self.send(Ack(addressee, message_id))

    def reject(self, addressee: str, message_id: str) -> Packet:
        """Reject message ``message_id`` from ``addressee``."""
        return self.send(Reject(addressee, message_id))

    def bulletin(self, id: str, text: str, *, group: str = "") -> Packet:
        """A bulletin (``id`` a digit), announcement (a letter) or group bulletin."""
        if len(id) != 1:
            raise EncodeError(f"a bulletin id is exactly one character, not {id!r}", RefusalCode.INVALID_ADDRESSEE)
        return self.send(Bulletin(f"BLN{id}{group}", text))

    def status(
        self,
        text: str = "",
        *,
        timestamp: TimestampLike = None,
        locator: str | None = None,
        symbol: Symbol | None = None,
        beam: Beam | None = None,
    ) -> Packet:
        """A status report, optionally timestamped, or with a grid locator and symbol, or a
        meteor scatter ``beam`` heading and power. The locator is sent in upper case, as a decoder
        reports it."""
        if locator is not None:
            locator = locator.upper()
        return self.send(StatusReport(text, _timestamp(timestamp), locator, symbol, beam))

    # ------------------------------------------------------------ telemetry

    def telemetry(
        self,
        sequence: int,
        analog: Iterable[float | None],
        bits: str = "00000000",
        *,
        comment: str = "",
    ) -> Packet:
        """A telemetry report: a sequence number (0-999, written in three digits; a larger one is
        refused, not wrapped), five analog values and eight bits."""
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise TypeError(f"telemetry sequence must be an int, not {type(sequence).__name__}")
        if not 0 <= sequence <= 999:
            raise EncodeError(f"telemetry sequence {sequence} is not 0-999", RefusalCode.VALUE_OUT_OF_RANGE)
        return self.send(TelemetryReport(f"{sequence:03d}", tuple(analog), bits, comment))

    def telemetry_names(self, names: Iterable[str], *, addressee: str | None = None) -> Packet:
        """Names for the telemetry channels (``PARM.``), for ``addressee`` (this station by default)."""
        return self.send(TelemetryNames(addressee or self.callsign, tuple(names)))

    def telemetry_units(self, units: Iterable[str], *, addressee: str | None = None) -> Packet:
        """Units and labels for the telemetry channels (``UNIT.``)."""
        return self.send(TelemetryUnits(addressee or self.callsign, tuple(units)))

    def telemetry_coefficients(self, coefficients: Iterable[float], *, addressee: str | None = None) -> Packet:
        """Equation coefficients a, b, c for each analog channel (``EQNS.``)."""
        return self.send(TelemetryCoefficients(addressee or self.callsign, tuple(coefficients)))

    def telemetry_bits(self, bits: str, project: str = "", *, addressee: str | None = None) -> Packet:
        """The bits' sense and the project title (``BITS.``)."""
        return self.send(TelemetryBits(addressee or self.callsign, bits, project))

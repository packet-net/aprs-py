"""Building the packets an application typically sends.

A :class:`Station` holds what stays the same from packet to packet (the callsign, the
digipeater path, the destination, whether the station can message, its usual symbol), and
has one method per kind of packet. Each returns a :class:`~pdn_aprs.Packet`, already
encoded; ``str(packet)`` is its TNC2 line, ``packet.to_kiss()`` its KISS frame.

>>> from pdn_aprs import Station, Symbol
>>> m0lte = Station("M0LTE-9", via="WIDE1-1", symbol=Symbol.CAR)
>>> print(m0lte.position(51.45, -0.98, course=88, speed=36, comment="Mobile"))
M0LTE-9>APZ001,WIDE1-1:!5127.00N/00058.80W>088/036Mobile
>>> print(m0lte.message("G4ABC", "Hello there", message_id="1"))
M0LTE-9>APZ001,WIDE1-1::G4ABC    :Hello there{1

Quantities are in the units APRS sends: degrees, knots, feet, miles, and for weather mph,
degrees Fahrenheit, inches and millibars. Speed, altitude, temperature and rain can be given in
metric units instead (``speed_kmh``, ``altitude_m``, ``temperature_c``, ``rain_1h_mm``...), and
are converted.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TypedDict

from ._util import FEET_PER_METRE, round_half_away
from .encode import DEFAULT_DESTINATION, build_packet
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
    ToneType,
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


KMH_PER_KNOT = 1.852
"""Kilometres per hour in a knot: a nautical mile is exactly 1852 m."""

MM_PER_INCH = 25.4


def _either(value: float | None, metric: float | None, per_unit: float, what: str) -> float | None:
    """A quantity given in APRS's unit or in a metric one, which is divided by ``per_unit``."""
    if metric is None:
        return value
    if value is not None:
        raise ValueError(f"give the {what} once, not in both units")
    return metric / per_unit


def _frequency(
    value: float | VoiceFrequency | None, tone: float | None, offset_khz: int | None
) -> VoiceFrequency | None:
    if value is None:
        if tone is not None or offset_khz is not None:
            raise ValueError("a tone or offset goes with a frequency")
        return None
    if isinstance(value, VoiceFrequency):
        return value
    return VoiceFrequency(
        float(value),
        tone=None if tone is None else ToneType.TONE,
        tone_value=None if tone is None else int(tone),
        offset_khz=offset_khz,
    )


class _Extras(TypedDict):
    course_degrees: int | None
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
    course: int | None,
    speed: float | None,
    altitude: float | None,
    speed_kmh: float | None,
    altitude_m: float | None,
    compressed: bool,
    ambiguity: int,
    phg: Phg | None,
    range_miles: float | None,
    frequency: float | VoiceFrequency | None,
    tone: float | None,
    offset_khz: int | None,
    telemetry: CommentTelemetry | None,
    precise: bool,
) -> _Extras:
    """The fields a position, object or item report share, from the builder's arguments."""
    speed = _either(speed, speed_kmh, KMH_PER_KNOT, "speed")
    return {
        "course_degrees": course,
        "speed_knots": speed,
        "altitude_feet": _either(altitude, altitude_m, 1 / FEET_PER_METRE, "altitude"),
        "compressed": compressed,
        "compression": CompressionType() if compressed and (course is not None or speed is not None) else None,
        "ambiguity": ambiguity,
        "phg": phg,
        "range_miles": range_miles,
        "frequency": _frequency(frequency, tone, offset_khz),
        "telemetry": telemetry,
        "dao": Dao("W", DaoPrecision.BASE91) if precise else None,
    }


@dataclass(frozen=True)
class Station:
    """A sending station: its callsign, path and habits, and a method for each packet it sends.

    ``via`` is the digipeater path (``"WIDE1-1,WIDE2-1"`` or a list). ``destination`` is the
    tocall: use the one allocated to your application (the default, ``APZ001``, is
    experimental). ``messaging`` says whether the station can receive messages, which position
    reports and Mic-E reports announce. ``symbol`` is used when a report does not give one.
    """

    callsign: str
    via: str | Sequence[str] = ()
    destination: str = DEFAULT_DESTINATION
    messaging: bool = False
    symbol: Symbol | None = None
    path: tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        via = self.via.split(",") if isinstance(self.via, str) else list(self.via)
        object.__setattr__(self, "path", tuple(v.strip() for v in via if v.strip()))

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
        course: int | None = None,
        speed: float | None = None,
        altitude: float | None = None,
        speed_kmh: float | None = None,
        altitude_m: float | None = None,
        timestamp: TimestampLike = None,
        compressed: bool = False,
        ambiguity: int = 0,
        phg: Phg | None = None,
        range_miles: float | None = None,
        frequency: float | VoiceFrequency | None = None,
        tone: float | None = None,
        offset_khz: int | None = None,
        telemetry: CommentTelemetry | None = None,
        precise: bool = False,
    ) -> Packet:
        """A position report. ``course`` in degrees, ``speed`` in knots (or ``speed_kmh``),
        ``altitude`` in feet (or ``altitude_m``).

        ``timestamp=True`` stamps it with the time now. ``precise`` adds a ``!DAO!`` for about
        a foot of precision. ``frequency`` (MHz, with ``tone`` in Hz and ``offset_khz``) is the
        voice frequency the station listens on.
        """
        data = PositionReport(
            latitude=latitude,
            longitude=longitude,
            symbol=self._symbol(symbol),
            timestamp=_timestamp(timestamp),
            messaging=self.messaging,
            comment=comment,
            **_extras(
                course=course,
                speed=speed,
                altitude=altitude,
                speed_kmh=speed_kmh,
                altitude_m=altitude_m,
                compressed=compressed,
                ambiguity=ambiguity,
                phg=phg,
                range_miles=range_miles,
                frequency=frequency,
                tone=tone,
                offset_khz=offset_khz,
                telemetry=telemetry,
                precise=precise,
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
        course: int | None = None,
        speed: float | None = None,
        altitude: float | None = None,
        speed_kmh: float | None = None,
        altitude_m: float | None = None,
        compressed: bool = False,
        ambiguity: int = 0,
        phg: Phg | None = None,
        range_miles: float | None = None,
        frequency: float | VoiceFrequency | None = None,
        tone: float | None = None,
        offset_khz: int | None = None,
        telemetry: CommentTelemetry | None = None,
        precise: bool = False,
    ) -> Packet:
        """An object report: something else's position, under a name of up to 9 characters.

        An object always has a timestamp; the default is the time now. ``killed=True``
        removes the object from other stations' maps.
        """
        stamp = _timestamp(timestamp)
        if stamp is None:
            raise ValueError("an object always has a timestamp")
        data = ObjectReport(
            name=name,
            killed=killed,
            timestamp=stamp,
            latitude=latitude,
            longitude=longitude,
            symbol=self._symbol(symbol),
            comment=comment,
            **_extras(
                course=course,
                speed=speed,
                altitude=altitude,
                speed_kmh=speed_kmh,
                altitude_m=altitude_m,
                compressed=compressed,
                ambiguity=ambiguity,
                phg=phg,
                range_miles=range_miles,
                frequency=frequency,
                tone=tone,
                offset_khz=offset_khz,
                telemetry=telemetry,
                precise=precise,
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
        course: int | None = None,
        speed: float | None = None,
        altitude: float | None = None,
        speed_kmh: float | None = None,
        altitude_m: float | None = None,
        compressed: bool = False,
        ambiguity: int = 0,
        phg: Phg | None = None,
        range_miles: float | None = None,
        frequency: float | VoiceFrequency | None = None,
        tone: float | None = None,
        offset_khz: int | None = None,
        telemetry: CommentTelemetry | None = None,
        precise: bool = False,
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
                course=course,
                speed=speed,
                altitude=altitude,
                speed_kmh=speed_kmh,
                altitude_m=altitude_m,
                compressed=compressed,
                ambiguity=ambiguity,
                phg=phg,
                range_miles=range_miles,
                frequency=frequency,
                tone=tone,
                offset_khz=offset_khz,
                telemetry=telemetry,
                precise=precise,
            ),
        )
        return self.send(data)

    def mic_e(
        self,
        latitude: float,
        longitude: float,
        symbol: Symbol | None = None,
        *,
        message: MicEMessage = MicEMessage.IN_SERVICE,
        course: int | None = None,
        speed: float | None = None,
        altitude: float | None = None,
        speed_kmh: float | None = None,
        altitude_m: float | None = None,
        comment: str = "",
        ambiguity: int = 0,
        frequency: float | VoiceFrequency | None = None,
        tone: float | None = None,
        offset_khz: int | None = None,
        telemetry: CommentTelemetry | None = None,
        precise: bool = False,
    ) -> Packet:
        """A Mic-E report: the compact position format of trackers and radios. The destination
        address carries half the position and is computed; the type code says whether this
        station can message.

        A course of 0 (or one that rounds to 0) is unknown and north is 360, as APRS has them.
        An altitude in metres goes in the Mic-E altitude bytes, whose unit is the metre, rounded
        to the metre; one in feet goes in a ``/A=``."""
        if course is not None and round_half_away(course) == 0:
            course = None
        if altitude_m is not None:
            if altitude is not None:
                raise ValueError("give the altitude once, not in both units")
            feet: float | None = round_half_away(altitude_m) * FEET_PER_METRE
        else:
            feet = altitude
        data = MicEReport(
            latitude=latitude,
            longitude=longitude,
            symbol=self._symbol(symbol),
            mic_e_message=message,
            course_degrees=course,
            speed_knots=_either(speed, speed_kmh, KMH_PER_KNOT, "speed") or 0,
            altitude_feet=feet,
            altitude_in_comment=altitude is not None,
            comment=comment,
            ambiguity=ambiguity,
            frequency=_frequency(frequency, tone, offset_khz),
            telemetry=telemetry,
            dao=Dao("W", DaoPrecision.BASE91) if precise else None,
            type_code="`" if self.messaging else "'",
        )
        return self.send(data)

    # ------------------------------------------------------------ weather

    def weather(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
        *,
        wind_direction: int | None = None,
        wind_speed: float | None = None,
        gust: float | None = None,
        temperature: float | None = None,
        rain_1h: float | None = None,
        rain_24h: float | None = None,
        rain_since_midnight: float | None = None,
        humidity: int | None = None,
        pressure: float | None = None,
        luminosity: int | None = None,
        snow_24h: float | None = None,
        timestamp: TimestampLike = None,
        symbol: Symbol = Symbol.WEATHER_STATION,
        software: str | None = None,
        unit: str | None = None,
        temperature_c: float | None = None,
        rain_1h_mm: float | None = None,
        rain_24h_mm: float | None = None,
        rain_since_midnight_mm: float | None = None,
    ) -> Packet:
        """A weather report: with a position, a complete weather report (the ``_`` symbol, or the
        ``symbol`` given, an overlay say); without one, a positionless report (always timestamped,
        now by default).

        Wind in degrees and mph, temperature in degrees Fahrenheit (or ``temperature_c``), rain
        in inches (or ``rain_1h_mm`` and so on), humidity in percent, pressure in millibars,
        luminosity in W/m2, snow in inches.
        """
        if temperature_c is not None:
            if temperature is not None:
                raise ValueError("give the temperature once, not in both units")
            temperature = temperature_c * 9 / 5 + 32
        if symbol != Symbol.WEATHER_STATION and (latitude is None or longitude is None):
            raise ValueError("a positionless weather report has no symbol")
        weather = Weather(
            wind_direction_degrees=wind_direction,
            wind_speed_mph=wind_speed,
            wind_gust_mph=gust,
            temperature_f=temperature,
            rain_1h_in=_either(rain_1h, rain_1h_mm, MM_PER_INCH, "rain in the last hour"),
            rain_24h_in=_either(rain_24h, rain_24h_mm, MM_PER_INCH, "rain in the last 24 hours"),
            rain_midnight_in=_either(rain_since_midnight, rain_since_midnight_mm, MM_PER_INCH, "rain since midnight"),
            humidity_percent=humidity,
            pressure_mbar=pressure,
            luminosity_w_m2=luminosity,
            snow_24h_in=snow_24h,
            software=software,
            unit=unit,
        )
        if latitude is None or longitude is None:
            if latitude is not None or longitude is not None:
                raise ValueError("give both latitude and longitude, or neither")
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

    def message(self, to: str, text: str, *, message_id: str | None = None, reply_ack: str | None = None) -> Packet:
        """A message to one station. Give a ``message_id`` to ask for an acknowledgement."""
        return self.send(Message(to, text, message_id, reply_ack))

    def ack(self, to: str, message_id: str) -> Packet:
        """Acknowledge message ``message_id`` from ``to``."""
        return self.send(Ack(to, message_id))

    def reject(self, to: str, message_id: str) -> Packet:
        """Reject message ``message_id`` from ``to``."""
        return self.send(Reject(to, message_id))

    def bulletin(self, identifier: str, text: str, *, group: str = "") -> Packet:
        """A bulletin (``identifier`` a digit), announcement (a letter) or group bulletin."""
        return self.send(Bulletin(f"BLN{identifier}{group}", text))

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
        sequence: int | str,
        analog: Iterable[float | None],
        bits: str = "00000000",
        *,
        comment: str = "",
    ) -> Packet:
        """A telemetry report: a sequence number (0-999, written in three digits; a larger one is
        refused, not wrapped), five analog values and eight bits."""
        if isinstance(sequence, int) and not 0 <= sequence <= 999:
            raise ValueError(f"telemetry sequence {sequence} is not 0-999")
        seq = f"{sequence:03d}" if isinstance(sequence, int) else sequence
        return self.send(TelemetryReport(seq, tuple(analog), bits, comment))

    def telemetry_names(self, names: Iterable[str], *, station: str | None = None) -> Packet:
        """Names for the telemetry channels (``PARM.``), for ``station`` (this one by default)."""
        return self.send(TelemetryNames(station or self.callsign, tuple(names)))

    def telemetry_units(self, units: Iterable[str], *, station: str | None = None) -> Packet:
        """Units and labels for the telemetry channels (``UNIT.``)."""
        return self.send(TelemetryUnits(station or self.callsign, tuple(units)))

    def telemetry_coefficients(self, coefficients: Iterable[float], *, station: str | None = None) -> Packet:
        """Equation coefficients a, b, c for each analog channel (``EQNS.``)."""
        return self.send(TelemetryCoefficients(station or self.callsign, tuple(coefficients)))

    def telemetry_bits(self, bits: str, project: str = "", *, station: str | None = None) -> Packet:
        """The bits' sense and the project title (``BITS.``)."""
        return self.send(TelemetryBits(station or self.callsign, bits, project))

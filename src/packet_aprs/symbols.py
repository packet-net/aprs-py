"""APRS symbols: a table (or overlay) character and a symbol code, and every defined symbol by name.

>>> from packet_aprs import Symbol
>>> Symbol.CAR
Symbol('/>')
>>> str(Symbol.CAR), Symbol.CAR.description
('/>', 'Car')
>>> Symbol.OVERLAY_VEHICLE.with_overlay("3")
Symbol('3>')
>>> Symbol.parse("3>").base
Symbol('\\\\>')

The names and descriptions follow the symbol tables of APRS12c ch. 21 and APRS-Symbols, and
match Packet.Aprs's ``AprsSymbol`` names (``Car``, ``OverlayVehicle``...) in upper snake case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

__all__ = ["Symbol"]

PRIMARY_TABLE = "/"
ALTERNATE_TABLE = "\\"


def _is_overlay(ch: str) -> bool:
    return len(ch) == 1 and ("0" <= ch <= "9" or "A" <= ch <= "Z")


@dataclass(frozen=True, slots=True)
class Symbol:
    """A symbol: ``table`` is ``/`` (primary), ``\\`` (alternate) or an overlay character
    (``0``-``9``, ``A``-``Z``) on an alternate-table symbol, and ``code`` is the symbol code.

    Every symbol the tables define is a class attribute (``Symbol.CAR``, ``Symbol.HOUSE``...).
    """

    table: str
    code: str

    POLICE_SHERIFF: ClassVar[Symbol]
    DIGIPEATER: ClassVar[Symbol]
    PHONE: ClassVar[Symbol]
    DX_CLUSTER: ClassVar[Symbol]
    HF_GATEWAY: ClassVar[Symbol]
    SMALL_AIRCRAFT: ClassVar[Symbol]
    MOBILE_SATELLITE_GROUND_STATION: ClassVar[Symbol]
    WHEELCHAIR: ClassVar[Symbol]
    SNOWMOBILE: ClassVar[Symbol]
    RED_CROSS: ClassVar[Symbol]
    BOY_SCOUTS: ClassVar[Symbol]
    HOUSE: ClassVar[Symbol]
    X_MARK: ClassVar[Symbol]
    RED_DOT: ClassVar[Symbol]
    CIRCLE_0: ClassVar[Symbol]
    CIRCLE_1: ClassVar[Symbol]
    CIRCLE_2: ClassVar[Symbol]
    CIRCLE_3: ClassVar[Symbol]
    CIRCLE_4: ClassVar[Symbol]
    CIRCLE_5: ClassVar[Symbol]
    CIRCLE_6: ClassVar[Symbol]
    CIRCLE_7: ClassVar[Symbol]
    CIRCLE_8: ClassVar[Symbol]
    CIRCLE_9: ClassVar[Symbol]
    FIRE: ClassVar[Symbol]
    CAMPGROUND: ClassVar[Symbol]
    MOTORCYCLE: ClassVar[Symbol]
    RAILROAD_ENGINE: ClassVar[Symbol]
    CAR: ClassVar[Symbol]
    FILE_SERVER: ClassVar[Symbol]
    HURRICANE_FUTURE_PREDICTION: ClassVar[Symbol]
    AID_STATION: ClassVar[Symbol]
    BBS: ClassVar[Symbol]
    CANOE: ClassVar[Symbol]
    EYEBALL: ClassVar[Symbol]
    FARM_VEHICLE: ClassVar[Symbol]
    GRID_SQUARE: ClassVar[Symbol]
    HOTEL: ClassVar[Symbol]
    TCP_IP_NETWORK_STATION: ClassVar[Symbol]
    SCHOOL: ClassVar[Symbol]
    PC_USER: ClassVar[Symbol]
    MAC_APRS: ClassVar[Symbol]
    NTS_STATION: ClassVar[Symbol]
    BALLOON: ClassVar[Symbol]
    POLICE: ClassVar[Symbol]
    RECREATIONAL_VEHICLE: ClassVar[Symbol]
    SPACE_SHUTTLE: ClassVar[Symbol]
    SSTV: ClassVar[Symbol]
    BUS: ClassVar[Symbol]
    AMATEUR_TV: ClassVar[Symbol]
    NATIONAL_WEATHER_SERVICE_SITE: ClassVar[Symbol]
    HELICOPTER: ClassVar[Symbol]
    YACHT: ClassVar[Symbol]
    WIN_APRS: ClassVar[Symbol]
    JOGGER: ClassVar[Symbol]
    DIRECTION_FINDING: ClassVar[Symbol]
    POST_OFFICE: ClassVar[Symbol]
    LARGE_AIRCRAFT: ClassVar[Symbol]
    WEATHER_STATION: ClassVar[Symbol]
    DISH_ANTENNA: ClassVar[Symbol]
    AMBULANCE: ClassVar[Symbol]
    BICYCLE: ClassVar[Symbol]
    INCIDENT_COMMAND_POST: ClassVar[Symbol]
    FIRE_DEPARTMENT: ClassVar[Symbol]
    HORSE: ClassVar[Symbol]
    FIRE_TRUCK: ClassVar[Symbol]
    GLIDER: ClassVar[Symbol]
    HOSPITAL: ClassVar[Symbol]
    IOTA: ClassVar[Symbol]
    JEEP: ClassVar[Symbol]
    TRUCK: ClassVar[Symbol]
    LAPTOP: ClassVar[Symbol]
    MIC_E_REPEATER: ClassVar[Symbol]
    NODE: ClassVar[Symbol]
    EMERGENCY_OPERATIONS_CENTER: ClassVar[Symbol]
    ROVER: ClassVar[Symbol]
    GRID_SQUARE_ABOVE_128M: ClassVar[Symbol]
    REPEATER: ClassVar[Symbol]
    SHIP: ClassVar[Symbol]
    TRUCK_STOP: ClassVar[Symbol]
    EIGHTEEN_WHEELER: ClassVar[Symbol]
    VAN: ClassVar[Symbol]
    WATER_STATION: ClassVar[Symbol]
    X_APRS: ClassVar[Symbol]
    YAGI_AT_QTH: ClassVar[Symbol]
    EMERGENCY: ClassVar[Symbol]
    OVERLAY_DIGIPEATER: ClassVar[Symbol]
    BANK: ClassVar[Symbol]
    POWER_PLANT: ClassVar[Symbol]
    GATEWAY: ClassVar[Symbol]
    CRASH: ClassVar[Symbol]
    CLOUDY: ClassVar[Symbol]
    FIRENET: ClassVar[Symbol]
    SNOW: ClassVar[Symbol]
    CHURCH: ClassVar[Symbol]
    GIRL_SCOUTS: ClassVar[Symbol]
    OVERLAY_HOUSE: ClassVar[Symbol]
    AMBIGUOUS: ClassVar[Symbol]
    WAYPOINT: ClassVar[Symbol]
    OVERLAY_CIRCLE: ClassVar[Symbol]
    NETWORK_NODE: ClassVar[Symbol]
    GAS_STATION: ClassVar[Symbol]
    HAIL: ClassVar[Symbol]
    PARK: ClassVar[Symbol]
    ADVISORY: ClassVar[Symbol]
    APRSTT: ClassVar[Symbol]
    OVERLAY_VEHICLE: ClassVar[Symbol]
    INFORMATION_KIOSK: ClassVar[Symbol]
    HURRICANE_TROPICAL_STORM: ClassVar[Symbol]
    OVERLAY_BOX: ClassVar[Symbol]
    BLOWING_SNOW: ClassVar[Symbol]
    COAST_GUARD: ClassVar[Symbol]
    DRIZZLE: ClassVar[Symbol]
    SMOKE: ClassVar[Symbol]
    FREEZING_RAIN: ClassVar[Symbol]
    SNOW_SHOWER: ClassVar[Symbol]
    HAZE: ClassVar[Symbol]
    RAIN_SHOWER: ClassVar[Symbol]
    LIGHTNING: ClassVar[Symbol]
    KENWOOD_HT: ClassVar[Symbol]
    LIGHTHOUSE: ClassVar[Symbol]
    MARS: ClassVar[Symbol]
    NAVIGATION_BUOY: ClassVar[Symbol]
    ROCKET: ClassVar[Symbol]
    PARKING: ClassVar[Symbol]
    EARTHQUAKE: ClassVar[Symbol]
    RESTAURANT: ClassVar[Symbol]
    SATELLITE: ClassVar[Symbol]
    THUNDERSTORM: ClassVar[Symbol]
    SUNNY: ClassVar[Symbol]
    VORTAC: ClassVar[Symbol]
    OVERLAY_NWS_SITE: ClassVar[Symbol]
    PHARMACY: ClassVar[Symbol]
    OVERLAY_RADIO: ClassVar[Symbol]
    WALL_CLOUD: ClassVar[Symbol]
    AIRCRAFT_WITH_HEADING: ClassVar[Symbol]
    WEATHER_STATION_WITH_DIGIPEATER: ClassVar[Symbol]
    RAIN: ClassVar[Symbol]
    OVERLAY_DIAMOND: ClassVar[Symbol]
    BLOWING_DUST: ClassVar[Symbol]
    OVERLAY_CIVIL_DEFENSE: ClassVar[Symbol]
    DX_SPOT: ClassVar[Symbol]
    SLEET: ClassVar[Symbol]
    FUNNEL_CLOUD: ClassVar[Symbol]
    GALE_FLAGS: ClassVar[Symbol]
    STORE: ClassVar[Symbol]
    POINT_OF_INTEREST: ClassVar[Symbol]
    WORK_ZONE: ClassVar[Symbol]
    SPECIAL_VEHICLE: ClassVar[Symbol]
    AREA: ClassVar[Symbol]
    VALUE_SIGN: ClassVar[Symbol]
    TRIANGLE: ClassVar[Symbol]
    SMALL_CIRCLE: ClassVar[Symbol]
    PARTLY_CLOUDY: ClassVar[Symbol]
    RESTROOMS: ClassVar[Symbol]
    OVERLAY_SHIP: ClassVar[Symbol]
    TORNADO: ClassVar[Symbol]
    OVERLAY_TRUCK: ClassVar[Symbol]
    OVERLAY_VAN: ClassVar[Symbol]
    FLOODING: ClassVar[Symbol]
    WRECK: ClassVar[Symbol]
    SKYWARN: ClassVar[Symbol]
    SHELTER: ClassVar[Symbol]
    FOG: ClassVar[Symbol]

    def __post_init__(self) -> None:
        if len(self.table) != 1 or len(self.code) != 1:
            raise ValueError("a symbol is a table character and a code character")

    def __str__(self) -> str:
        return self.table + self.code

    def __repr__(self) -> str:
        return f"Symbol({str(self)!r})"

    @classmethod
    def parse(cls, text: str) -> Symbol:
        """From the two characters as sent: ``"/>"``, ``"\\\\>"`` or ``"3>"``."""
        if len(text) != 2:
            raise ValueError(f"a symbol is two characters: {text!r}")
        return cls(text[0], text[1])

    @classmethod
    def from_name(cls, name: str) -> Symbol:
        """A defined symbol by its name, e.g. ``"CAR"`` (case and ``-``/space insensitive)."""
        key = name.strip().upper().replace("-", "_").replace(" ", "_")
        try:
            return _BY_NAME[key]
        except KeyError:
            raise ValueError(f"no symbol named {name!r}") from None

    @property
    def is_primary(self) -> bool:
        return self.table == PRIMARY_TABLE

    @property
    def is_alternate(self) -> bool:
        """True for the alternate table, with or without an overlay."""
        return self.table == ALTERNATE_TABLE or _is_overlay(self.table)

    @property
    def overlay(self) -> str | None:
        """The overlay character, or ``None``."""
        return self.table if _is_overlay(self.table) else None

    @property
    def base(self) -> Symbol:
        """This symbol without its overlay."""
        return Symbol(ALTERNATE_TABLE, self.code) if self.overlay else self

    def with_overlay(self, overlay: str | int) -> Symbol:
        """This alternate-table symbol with an overlay character (``0``-``9`` or ``A``-``Z``)."""
        ch = str(overlay)
        if not self.is_alternate:
            raise ValueError("only alternate-table symbols take an overlay")
        if not _is_overlay(ch):
            raise ValueError(f"an overlay is 0-9 or A-Z: {overlay!r}")
        return Symbol(ch, self.code)

    @property
    def name(self) -> str | None:
        """The defined symbol's name (``"CAR"``), ignoring any overlay, or ``None``."""
        return _NAME.get(self.base)

    @property
    def description(self) -> str | None:
        """What the symbol stands for, from the symbol tables, or ``None``."""
        return _DESCRIPTION.get(self.base)

    @property
    def is_valid(self) -> bool:
        """True when the table is ``/``, ``\\`` or an overlay and the code is printable ASCII."""
        return (self.table in (PRIMARY_TABLE, ALTERNATE_TABLE) or _is_overlay(self.table)) and (
            "!" <= self.code <= "~"
        )


_DEFINED: tuple[tuple[str, str, str, str], ...] = (
    ('POLICE_SHERIFF', '/', '!', 'Police, Sheriff'),
    ('DIGIPEATER', '/', '#', 'Digi (green star with white center)'),
    ('PHONE', '/', '$', 'Phone'),
    ('DX_CLUSTER', '/', '%', 'DX Cluster'),
    ('HF_GATEWAY', '/', '&', 'HF Gateway'),
    ('SMALL_AIRCRAFT', '/', "'", 'Small Aircraft'),
    ('MOBILE_SATELLITE_GROUND_STATION', '/', '(', 'Mobile Satellite Ground Station'),
    ('WHEELCHAIR', '/', ')', 'Wheelchair (handicapped)'),
    ('SNOWMOBILE', '/', '*', 'Snowmobile'),
    ('RED_CROSS', '/', '+', 'Red Cross'),
    ('BOY_SCOUTS', '/', ',', 'Boy Scouts'),
    ('HOUSE', '/', '-', 'House QTH (VHF)'),
    ('X_MARK', '/', '.', 'X'),
    ('RED_DOT', '/', '/', 'Red Dot'),
    ('CIRCLE_0', '/', '0', '0 Circle'),
    ('CIRCLE_1', '/', '1', '1 Circle'),
    ('CIRCLE_2', '/', '2', '2 Circle'),
    ('CIRCLE_3', '/', '3', '3 Circle'),
    ('CIRCLE_4', '/', '4', '4 Circle'),
    ('CIRCLE_5', '/', '5', '5 Circle'),
    ('CIRCLE_6', '/', '6', '6 Circle'),
    ('CIRCLE_7', '/', '7', '7 Circle'),
    ('CIRCLE_8', '/', '8', '8 Circle'),
    ('CIRCLE_9', '/', '9', '9 Circle'),
    ('FIRE', '/', ':', 'Fire'),
    ('CAMPGROUND', '/', ';', 'Campground (Portable ops)'),
    ('MOTORCYCLE', '/', '<', 'Motorcycle'),
    ('RAILROAD_ENGINE', '/', '=', 'Railroad Engine'),
    ('CAR', '/', '>', 'Car'),
    ('FILE_SERVER', '/', '?', 'File Server'),
    ('HURRICANE_FUTURE_PREDICTION', '/', '@', 'Hurricane Future Prediction'),
    ('AID_STATION', '/', 'A', 'Aid Station'),
    ('BBS', '/', 'B', 'BBS or PBBS'),
    ('CANOE', '/', 'C', 'Canoe'),
    ('EYEBALL', '/', 'E', 'Eyeball (events, etc.)'),
    ('FARM_VEHICLE', '/', 'F', 'Farm Vehicle (Tractor)'),
    ('GRID_SQUARE', '/', 'G', 'Grid Square (6-character)'),
    ('HOTEL', '/', 'H', 'Hotel (blue bed icon)'),
    ('TCP_IP_NETWORK_STATION', '/', 'I', 'TCP/IP on air network station'),
    ('SCHOOL', '/', 'K', 'School'),
    ('PC_USER', '/', 'L', 'PC user'),
    ('MAC_APRS', '/', 'M', 'MacAPRS'),
    ('NTS_STATION', '/', 'N', 'NTS Station'),
    ('BALLOON', '/', 'O', 'Balloon'),
    ('POLICE', '/', 'P', 'Police'),
    ('RECREATIONAL_VEHICLE', '/', 'R', 'Recreational Vehicle'),
    ('SPACE_SHUTTLE', '/', 'S', 'Space Shuttle'),
    ('SSTV', '/', 'T', 'SSTV'),
    ('BUS', '/', 'U', 'Bus'),
    ('AMATEUR_TV', '/', 'V', 'Amateur TV'),
    ('NATIONAL_WEATHER_SERVICE_SITE', '/', 'W', 'National Weather Service Site'),
    ('HELICOPTER', '/', 'X', 'Helicopter'),
    ('YACHT', '/', 'Y', 'Yacht (sail boat)'),
    ('WIN_APRS', '/', 'Z', 'WinAPRS'),
    ('JOGGER', '/', '[', 'Jogger, Human/person'),
    ('DIRECTION_FINDING', '/', '\\', 'Triangle (DF)'),
    ('POST_OFFICE', '/', ']', 'Mail/Post Office'),
    ('LARGE_AIRCRAFT', '/', '^', 'Large Aircraft'),
    ('WEATHER_STATION', '/', '_', 'Weather Station (blue)'),
    ('DISH_ANTENNA', '/', '`', 'Dish Antenna'),
    ('AMBULANCE', '/', 'a', 'Ambulance'),
    ('BICYCLE', '/', 'b', 'Bicycle'),
    ('INCIDENT_COMMAND_POST', '/', 'c', 'Incident Command Post'),
    ('FIRE_DEPARTMENT', '/', 'd', 'Fire Department'),
    ('HORSE', '/', 'e', 'Horse (equestrian)'),
    ('FIRE_TRUCK', '/', 'f', 'Fire Truck'),
    ('GLIDER', '/', 'g', 'Glider'),
    ('HOSPITAL', '/', 'h', 'Hospital'),
    ('IOTA', '/', 'i', 'IOTA (Islands on the Air)'),
    ('JEEP', '/', 'j', 'Jeep'),
    ('TRUCK', '/', 'k', 'Truck'),
    ('LAPTOP', '/', 'l', 'Laptop'),
    ('MIC_E_REPEATER', '/', 'm', 'Mic-E Repeater'),
    ('NODE', '/', 'n', 'Node (black bulls-eye)'),
    ('EMERGENCY_OPERATIONS_CENTER', '/', 'o', 'Emergency Operations Center'),
    ('ROVER', '/', 'p', 'Rover (puppy dog)'),
    ('GRID_SQUARE_ABOVE_128M', '/', 'q', 'Grid Square shown above 128m'),
    ('REPEATER', '/', 'r', 'Repeater'),
    ('SHIP', '/', 's', 'Ship (power boat)'),
    ('TRUCK_STOP', '/', 't', 'Truck Stop'),
    ('EIGHTEEN_WHEELER', '/', 'u', 'Truck (18-wheeler)'),
    ('VAN', '/', 'v', 'Van'),
    ('WATER_STATION', '/', 'w', 'Water Station'),
    ('X_APRS', '/', 'x', 'X-APRS (Unix)'),
    ('YAGI_AT_QTH', '/', 'y', 'Yagi at QTH'),
    ('EMERGENCY', '\\', '!', 'Emergency'),
    ('OVERLAY_DIGIPEATER', '\\', '#', 'Digi (green star)'),
    ('BANK', '\\', '$', 'Bank or ATM (green box)'),
    ('POWER_PLANT', '\\', '%', 'Power Plant'),
    ('GATEWAY', '\\', '&', 'I=IGate R=RX T=1hopTX 2=2hopTX'),
    ('CRASH', '\\', "'", 'Crash (& incident sites)'),
    ('CLOUDY', '\\', '(', 'Cloudy'),
    ('FIRENET', '\\', ')', 'Firenet MEO, MODIS Earth Obs.'),
    ('SNOW', '\\', '*', 'Snow'),
    ('CHURCH', '\\', '+', 'Church'),
    ('GIRL_SCOUTS', '\\', ',', 'Girl Scouts'),
    ('OVERLAY_HOUSE', '\\', '-', 'House (H=HF) (O = Op Present)'),
    ('AMBIGUOUS', '\\', '.', 'Ambiguous (Big Question Mark)'),
    ('WAYPOINT', '\\', '/', 'Waypoint Destination (Note 1)'),
    ('OVERLAY_CIRCLE', '\\', '0', 'Circle (E/I/W= IRLP/EchoLink/WIRES)'),
    ('NETWORK_NODE', '\\', '8', '802.11 or other network node'),
    ('GAS_STATION', '\\', '9', 'Gas Station (blue pump)'),
    ('HAIL', '\\', ':', 'Hail'),
    ('PARK', '\\', ';', 'Park/Picnic Area'),
    ('ADVISORY', '\\', '<', 'Advisory (one WX flag)'),
    ('APRSTT', '\\', '=', 'APRStt Touchtone (DTMF Users)'),
    ('OVERLAY_VEHICLE', '\\', '>', 'Cars & Vehicles'),
    ('INFORMATION_KIOSK', '\\', '?', 'Information Kiosk (blue box with ?)'),
    ('HURRICANE_TROPICAL_STORM', '\\', '@', 'Hurricane/Tropical Storm'),
    ('OVERLAY_BOX', '\\', 'A', 'Box: DTMF, RFID, XO'),
    ('BLOWING_SNOW', '\\', 'B', 'Blowing Snow'),
    ('COAST_GUARD', '\\', 'C', 'Coast Guard'),
    ('DRIZZLE', '\\', 'D', 'Drizzle'),
    ('SMOKE', '\\', 'E', 'Smoke (& other vis codes)'),
    ('FREEZING_RAIN', '\\', 'F', 'Freezing Rain'),
    ('SNOW_SHOWER', '\\', 'G', 'Snow Shower'),
    ('HAZE', '\\', 'H', 'Haze'),
    ('RAIN_SHOWER', '\\', 'I', 'Rain Shower'),
    ('LIGHTNING', '\\', 'J', 'Lightning'),
    ('KENWOOD_HT', '\\', 'K', 'Kenwood HT (w)'),
    ('LIGHTHOUSE', '\\', 'L', 'Lighthouse'),
    ('MARS', '\\', 'M', 'MARS (A=Army, N=Navy, F=AF)'),
    ('NAVIGATION_BUOY', '\\', 'N', 'Navigation Buoy'),
    ('ROCKET', '\\', 'O', 'Rocket'),
    ('PARKING', '\\', 'P', 'Parking'),
    ('EARTHQUAKE', '\\', 'Q', 'Earthquake'),
    ('RESTAURANT', '\\', 'R', 'Restaurant'),
    ('SATELLITE', '\\', 'S', 'Satellite'),
    ('THUNDERSTORM', '\\', 'T', 'Thunderstorm'),
    ('SUNNY', '\\', 'U', 'Sunny'),
    ('VORTAC', '\\', 'V', 'VORTAC Nav Aid'),
    ('OVERLAY_NWS_SITE', '\\', 'W', 'NWS Site'),
    ('PHARMACY', '\\', 'X', 'Pharmacy Rx'),
    ('OVERLAY_RADIO', '\\', 'Y', 'Radios and devices'),
    ('WALL_CLOUD', '\\', '[', 'Wall Cloud'),
    ('AIRCRAFT_WITH_HEADING', '\\', '^', 'Aircraft (Shows Heading)'),
    ('WEATHER_STATION_WITH_DIGIPEATER', '\\', '_', 'WX Station with Digi (green)'),
    ('RAIN', '\\', '`', 'Rain'),
    ('OVERLAY_DIAMOND', '\\', 'a', 'ARRL, ARES, WinLINK, Dstar, LoRa, etc'),
    ('BLOWING_DUST', '\\', 'b', 'Blowing Dust/Sand'),
    ('OVERLAY_CIVIL_DEFENSE', '\\', 'c', 'CD triangle RACES/SATERN/etc'),
    ('DX_SPOT', '\\', 'd', 'DX Spot (from callsign prefix)'),
    ('SLEET', '\\', 'e', 'Sleet'),
    ('FUNNEL_CLOUD', '\\', 'f', 'Funnel Cloud'),
    ('GALE_FLAGS', '\\', 'g', 'Gale Flags'),
    ('STORE', '\\', 'h', 'Store or Hamfest'),
    ('POINT_OF_INTEREST', '\\', 'i', 'BOX or points of Interest'),
    ('WORK_ZONE', '\\', 'j', 'Work Zone (steam shovel)'),
    ('SPECIAL_VEHICLE', '\\', 'k', 'Special Vehicle SUV, ATV, 4x4'),
    ('AREA', '\\', 'l', 'Area Symbols (box, circle, etc)'),
    ('VALUE_SIGN', '\\', 'm', 'Value Sign (3 digit display)'),
    ('TRIANGLE', '\\', 'n', 'Triangle'),
    ('SMALL_CIRCLE', '\\', 'o', 'Small Circle'),
    ('PARTLY_CLOUDY', '\\', 'p', 'Partly Cloudy'),
    ('RESTROOMS', '\\', 'r', 'Restrooms'),
    ('OVERLAY_SHIP', '\\', 's', 'Ship/Boat (top view)'),
    ('TORNADO', '\\', 't', 'Tornado'),
    ('OVERLAY_TRUCK', '\\', 'u', 'Truck'),
    ('OVERLAY_VAN', '\\', 'v', 'Van'),
    ('FLOODING', '\\', 'w', 'Flooding (Avalanches/Slides)'),
    ('WRECK', '\\', 'x', 'Wreck or Obstruction'),
    ('SKYWARN', '\\', 'y', 'Skywarn'),
    ('SHELTER', '\\', 'z', 'Overlayed Shelter'),
    ('FOG', '\\', '{', 'Fog'),
)

_BY_NAME: dict[str, Symbol] = {}
_NAME: dict[Symbol, str] = {}
_DESCRIPTION: dict[Symbol, str] = {}
for _name, _table, _code, _description in _DEFINED:
    _symbol = Symbol(_table, _code)
    setattr(Symbol, _name, _symbol)
    _BY_NAME[_name] = _symbol
    _NAME[_symbol] = _name
    _DESCRIPTION[_symbol] = _description
del _name, _table, _code, _description, _symbol


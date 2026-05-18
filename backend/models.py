from dataclasses import dataclass
from typing import List


@dataclass
class FlightStrip:
    commercial_flight: str
    atc_flight: str
    dep_iata: str
    dep_icao: str
    dep_name: str
    dest_iata: str
    dest_icao: str
    dest_name: str
    alt_iata: str
    alt_icao: str
    alt_name: str
    date_of_flight: str
    std_utc: str
    std_local: str
    sta_utc: str
    sta_local: str
    flight_time: str
    ofp_version: str
    reg: str
    engine_type: str
    dep_rwy: str
    arr_rwy: str
    fl_min: str
    fl_max: str
    cost_index: str
    ramp_fuel: str
    ezfw: str
    etow: str
    elwt: str
    max_shear_rate: str = ""
    highest_mora: str = ""


@dataclass
class AirportWeather:
    icao: str
    iata: str
    name: str
    window_label: str
    metar: str
    taf: List[str]

@dataclass
class NotamEntry:
    notam_id: str
    category: str
    validity: str
    raw_text: str
    source_airport_icao: str
    source_airport_iata: str
    source_airport_name: str
    importance: str = "unknown"
    importance_score: int = 0
    importance_reasons: List[str] | None = None


@dataclass
class AirportNotamSection:
    airport_icao: str
    airport_iata: str
    airport_name: str
    section_title: str
    entries: List[NotamEntry]


@dataclass
class Briefing:
    strip: FlightStrip
    dep_weather: AirportWeather
    dest_weather: AirportWeather
    alt_weather: AirportWeather
    dep_notams: List[NotamEntry]
    dest_notams: List[NotamEntry]
    alt_notams: List[NotamEntry]
    dispatch_notes: List[str] = None
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple


class AirportInfo(NamedTuple):
    name: str
    iata: str
    tz_name: str
    offset_hours: float
    dst: str  # 'E', 'A', 'S', 'O', 'Z', 'N', 'U'


def load_icao_timezones_from_openflights(dat_path: str) -> dict[str, AirportInfo]:
    mapping: dict[str, AirportInfo] = {}
    path = Path(dat_path)
    if not path.exists():
        return mapping

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) < 12:
                continue

            name = parts[1]
            iata = parts[4] if parts[4] != r"\N" else ""
            icao = parts[5].upper()
            offset_str = parts[9].strip()
            dst_flag = parts[10].strip()
            tz_name = parts[11].strip()

            if not icao:
                continue

            try:
                offset = float(offset_str)
            except ValueError:
                offset = 0.0

            mapping[icao] = AirportInfo(
                name=name,
                iata=iata,
                tz_name=tz_name,
                offset_hours=offset,
                dst=dst_flag or "U",
            )
    return mapping


ICAO_TIMEZONES = load_icao_timezones_from_openflights("airports.dat")


def format_airport_from_icao(icao: str) -> tuple[str, str, str]:
    info = ICAO_TIMEZONES.get(icao)
    if not info:
        return icao, icao, ""
    return info.name or icao, icao, info.iata or ""
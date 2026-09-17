"""
data_fetch/pvgis_fetch.py -- Downloading PVGIS TMY (Typical Meteorological Year) data

PVGIS (Photovoltaic Geographical Information System, EU Joint Research
Centre) provides free, validated hourly solar irradiance and temperature
data for any geographic coordinate. The "TMY" assembles a typical
(representative) year from multiple years of real measurements -- so it
is suitable for long-term (one-year) simulation, rather than reflecting
the weather of one specific year.

We use this module to download and save to CSV the weather data series
for all three locations in the project (Sevilla, Morocco, Scotland).

Usage:
    python data_fetch/pvgis_fetch.py                  # Sevilla only (per step 1)
    python data_fetch/pvgis_fetch.py --location morocco
    python data_fetch/pvgis_fetch.py --all             # all three locations
"""

import argparse
import sys
from pathlib import Path

import pvlib

# Add the project root to the module search path, so that config.py can be
# imported even when this file is run directly from the data_fetch/ folder
# (e.g. "python data_fetch/pvgis_fetch.py").
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import LOCATIONS  # noqa: E402  (import needed after the sys.path change)


def fetch_and_save(location_key: str) -> None:
    """
    Downloads the PVGIS TMY data series for a given location, and saves it to CSV.

    The CSV column names match PVGIS's original naming
    (e.g. "G(h)" = global horizontal irradiance [W/m2], "T2m" = air
    temperature measured at 2 meters [C]) -- pv_model.py will use these.
    """
    if location_key not in LOCATIONS:
        raise ValueError(
            f"Unknown location: '{location_key}'. "
            f"Valid values: {list(LOCATIONS.keys())}"
        )

    loc = LOCATIONS[location_key]
    print(f"Downloading: {loc['name']} (lat={loc['latitude']}, lon={loc['longitude']})...")

    # The PVGIS TMY endpoint, with map_variables=False, returns the
    # original PVGIS column names (G(h), Gb(n), Gd(h), T2m, WS10m, RH, SP)
    # instead of pvlib's own naming (ghi, dni, temp_air, etc.).
    data, meta = pvlib.iotools.get_pvgis_tmy(
        latitude=loc["latitude"],
        longitude=loc["longitude"],
        map_variables=False,
    )

    loc["weather_csv"].parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(loc["weather_csv"])

    print(f"  -> {len(data)} hourly rows saved to: {loc['weather_csv']}")
    print(f"  -> columns: {list(data.columns)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download PVGIS TMY weather data")
    parser.add_argument(
        "--location",
        choices=list(LOCATIONS.keys()),
        default="sevilla",
        help="Which location's data to download (default: sevilla)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Download data for all three locations in sequence",
    )
    args = parser.parse_args()

    if args.all:
        for key in LOCATIONS:
            fetch_and_save(key)
    else:
        fetch_and_save(args.location)


if __name__ == "__main__":
    main()

"""
GridSense AI — simulated next-day electricity price forecasting engines.

Each supplier (A and B) has its own grid characteristics. GridSense:
  1. builds 28 days of synthetic "historical" hourly grid data for that supplier,
  2. forecasts tomorrow's load and solar output from that history,
  3. converts forecasted net load and grid stress into a 24-hour price profile.

So prices come from forecasted load, renewables, net load, capacity and grid
stress — NOT from fixed peak/off-peak hours.

Later you can replace `forecast_prices()` with a real ML model (e.g. XGBoost or
an LSTM trained on real supplier data) without changing the rest of the app.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

HOURS = list(range(24))


@dataclass(frozen=True)
class SupplierProfile:
    name: str
    base_load_mw: float      # average demand of the supplier's customers
    solar_capacity_mw: float  # installed solar in its generation portfolio
    wind_mw: float            # average wind generation (roughly flat)
    grid_capacity_mw: float   # firm capacity available to the supplier
    base_tariff: float        # $/kWh energy + network charge
    stress_price: float       # extra $/kWh added at 100% grid stress
    min_price: float          # price floor in $/kWh


# Supplier A: solar-heavy, tight evening capacity -> cheap middays, pricey evenings
SUPPLIER_A = SupplierProfile(
    name="Supplier A",
    base_load_mw=820,
    solar_capacity_mw=520,
    wind_mw=60,
    grid_capacity_mw=1050,
    base_tariff=0.085,
    stress_price=0.22,
    min_price=0.06,
)

# Supplier B: wind + more firm capacity -> flatter prices, cheaper evenings
SUPPLIER_B = SupplierProfile(
    name="Supplier B",
    base_load_mw=800,
    solar_capacity_mw=180,
    wind_mw=230,
    grid_capacity_mw=1150,
    base_tariff=0.105,
    stress_price=0.15,
    min_price=0.08,
)

SUPPLIERS = {"A": SUPPLIER_A, "B": SUPPLIER_B}


def _load_shape(hour: int) -> float:
    """Typical residential/commercial demand shape (1.0 = average)."""
    morning = 0.25 * math.exp(-((hour - 8) ** 2) / 6)
    evening = 0.45 * math.exp(-((hour - 19.5) ** 2) / 5)
    night_dip = -0.25 * math.exp(-((hour - 3.5) ** 2) / 6)
    return 0.92 + morning + evening + night_dip


def _solar_shape(hour: int) -> float:
    """Clear-sky solar output fraction (0 at night, 1 at noon)."""
    if hour < 6 or hour > 18:
        return 0.0
    return max(0.0, math.sin(math.pi * (hour - 6) / 12))


def _history(profile: SupplierProfile, target: date, days: int = 28):
    """Synthetic historical hourly load and solar data before the target day."""
    rows = []
    for d in range(days, 0, -1):
        day = target - timedelta(days=d)
        rng = random.Random(f"{profile.name}-{day.isoformat()}")
        weekend = 0.93 if day.weekday() >= 5 else 1.0
        cloudiness = rng.uniform(0.55, 1.0)  # 1.0 = clear sky
        for h in HOURS:
            load = profile.base_load_mw * _load_shape(h) * weekend * rng.uniform(0.96, 1.04)
            solar = profile.solar_capacity_mw * _solar_shape(h) * cloudiness
            rows.append({"day": day, "hour": h, "load": load, "solar": solar})
    return rows


def forecast_prices(supplier_key: str, target: date) -> list[dict]:
    """
    Forecast tomorrow's 24 hourly prices for one supplier.

    Forecast method (simple and explainable):
      load forecast  = weighted average of the same hour over the last 7 days
                       (recent days count more), adjusted for weekend.
      solar forecast = average of the same hour over the last 7 days.
    """
    profile = SUPPLIERS[supplier_key.upper()]
    hist = _history(profile, target)
    last7 = sorted({r["day"] for r in hist})[-7:]
    weights = {d: i + 1 for i, d in enumerate(last7)}  # 1..7
    weekend_adj = 0.93 if target.weekday() >= 5 else 1.0

    results = []
    for h in HOURS:
        rows = [r for r in hist if r["hour"] == h and r["day"] in weights]
        wsum = sum(weights[r["day"]] for r in rows)
        load = sum(r["load"] / (0.93 if r["day"].weekday() >= 5 else 1.0) * weights[r["day"]] for r in rows) / wsum
        load *= weekend_adj
        solar = sum(r["solar"] for r in rows) / len(rows)

        net_load = max(0.0, load - solar - profile.wind_mw)
        stress = net_load / profile.grid_capacity_mw  # 0..~1
        price = profile.base_tariff + profile.stress_price * stress**2
        price = max(profile.min_price, price)

        results.append(
            {
                "hour": h,
                "load_mw": round(load, 1),
                "solar_mw": round(solar, 1),
                "net_load_mw": round(net_load, 1),
                "grid_stress": round(stress, 3),
                "price_per_kwh": round(price, 4),
            }
        )
    return results

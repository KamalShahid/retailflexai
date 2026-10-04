"""
Deterministic appliance scheduling optimizer.

Goal: minimize next-day electricity cost while respecting each appliance's
power, required running time and allowed operating window.

We use exact search (no LLM guessing):
  - continuous appliances  -> try every possible start time, keep the cheapest
  - interruptible ones      -> pick the cheapest allowed hours
  - non-flexible appliances -> run from the earliest allowed hour

Because appliances are independent (no shared power limit), optimizing each
one separately gives the true minimum total cost.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field, field_validator, model_validator


class Appliance(BaseModel):
    name: str = Field(..., description="Appliance name, e.g. 'Washing Machine'")
    power_kw: float = Field(..., gt=0, le=50, description="Rated power in kW")
    hours: float = Field(..., gt=0, le=24, description="Required operating time in hours")
    earliest_hour: int = Field(0, ge=0, le=23, description="Earliest start hour (0-23)")
    latest_hour: int = Field(24, ge=1, le=24, description="Must finish by this hour (1-24)")
    continuous: bool = Field(True, description="True if it must run without interruption")
    flexible: bool = Field(True, description="False for fixed loads that cannot be shifted")

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        # "ev charger" -> "EV Charger", "ac" -> "AC", "Washing Machine" stays as-is
        words = v.strip().split()
        return " ".join(w.upper() if len(w) <= 2 else w[0].upper() + w[1:] for w in words)

    @model_validator(mode="after")
    def check_window(self):
        if len(self.allowed_hours()) < math.ceil(self.hours):
            raise ValueError(
                f"{self.name}: needs {self.hours} h but the window "
                f"{self.earliest_hour:02d}:00-{self.latest_hour:02d}:00 is too short."
            )
        return self

    def allowed_hours(self) -> list[int]:
        """Hours in the allowed window, in time order (supports windows past midnight)."""
        if self.latest_hour > self.earliest_hour:
            return list(range(self.earliest_hour, self.latest_hour))
        return list(range(self.earliest_hour, 24)) + list(range(0, self.latest_hour))


def _slot_energy(appliance: Appliance, n_slots: int) -> list[float]:
    """kWh used in each hourly slot (the last slot may be partial, e.g. 1.5 h)."""
    energy = [appliance.power_kw] * n_slots
    partial = appliance.hours - (n_slots - 1)
    energy[-1] = appliance.power_kw * partial
    return energy


def schedule_appliance(appliance: Appliance, prices: list[float]) -> dict:
    allowed = appliance.allowed_hours()
    n = math.ceil(appliance.hours)

    if not appliance.flexible:
        chosen = allowed[:n]
        energy = _slot_energy(appliance, n)
    elif appliance.continuous:
        best_cost, chosen, energy = math.inf, [], []
        base = _slot_energy(appliance, n)
        for start in range(len(allowed) - n + 1):
            block = allowed[start : start + n]
            cost = sum(prices[h] * e for h, e in zip(block, base))
            if cost < best_cost:
                best_cost, chosen, energy = cost, block, base
    else:
        # Interruptible: cheapest n hours. Put the partial hour on the priciest chosen slot.
        cheapest = sorted(allowed, key=lambda h: prices[h])[:n]
        by_price = sorted(cheapest, key=lambda h: prices[h])
        e = _slot_energy(appliance, n)
        energy_map = dict(zip(by_price, e))
        chosen = sorted(cheapest)
        energy = [energy_map[h] for h in chosen]

    cost = sum(prices[h] * e for h, e in zip(chosen, energy))
    return {
        "appliance": appliance.name,
        "power_kw": appliance.power_kw,
        "hours": appliance.hours,
        "hours_used": chosen,
        "time_slots": _format_slots(chosen),
        "energy_kwh": round(sum(energy), 3),
        "cost": round(cost, 4),
    }


def _format_slots(hours: list[int]) -> str:
    """[13, 14, 20] -> '13:00–15:00, 20:00–21:00'"""
    if not hours:
        return "-"
    blocks, start, prev = [], hours[0], hours[0]
    for h in hours[1:]:
        if h == prev + 1:
            prev = h
            continue
        blocks.append((start, prev + 1))
        start = prev = h
    blocks.append((start, prev + 1))
    return ", ".join(f"{a:02d}:00–{b:02d}:00" for a, b in blocks)


def optimize(appliances: list[Appliance], prices: list[float]) -> dict:
    """Optimize all appliances for one supplier's 24-hour price profile."""
    schedules = [schedule_appliance(a, prices) for a in appliances]
    return {
        "schedules": schedules,
        "total_energy_kwh": round(sum(s["energy_kwh"] for s in schedules), 3),
        "total_cost": round(sum(s["cost"] for s in schedules), 4),
    }

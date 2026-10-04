"""
CrewAI tools used by the RetailFlex AI agent.

1. RetailFlexOptimizerTool — calls GridSense-A and GridSense-B, optimizes the
   appliance schedule for each supplier and compares the costs.
2. DuckDuckGoSearchTool  — free web search (no API key) used to look up typical
   appliance power ratings when the consumer does not mention them.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Type

from ddgs import DDGS
from pydantic import BaseModel, Field, PrivateAttr, ValidationError
from crewai.tools import BaseTool

from .gridsense import SUPPLIERS, forecast_prices
from .optimizer import Appliance, optimize


# --------------------------------------------------------------------------- #
# 1. GridSense + optimizer tool
# --------------------------------------------------------------------------- #
class OptimizerInput(BaseModel):
    appliances_json: str = Field(
        ...,
        description=(
            "A JSON list of appliances. Each item has: name (str), power_kw (float), "
            "hours (float), earliest_hour (int 0-23), latest_hour (int 1-24, finish-by hour), "
            "continuous (bool), flexible (bool). Example: "
            '[{"name": "Washing Machine", "power_kw": 1.5, "hours": 2, '
            '"earliest_hour": 9, "latest_hour": 18, "continuous": true, "flexible": true}]'
        ),
    )


class RetailFlexOptimizerTool(BaseTool):
    name: str = "gridsense_schedule_optimizer"
    description: str = (
        "Gets next-day 24-hour electricity price forecasts from GridSense-A (Supplier A) "
        "and GridSense-B (Supplier B), finds the cheapest appliance schedule for each "
        "supplier, and returns both schedules, the daily costs and the recommended supplier. "
        "Always use this tool for scheduling and cost numbers — never guess them."
    )
    args_schema: Type[BaseModel] = OptimizerInput

    target_date: date = Field(default_factory=date.today)
    # Full result is kept here so the Streamlit app can draw charts and tables.
    _last_result: dict | None = PrivateAttr(default=None)

    @property
    def last_result(self) -> dict | None:
        return self._last_result

    def _run(self, appliances_json: Any) -> str:
        # 1) Parse and validate the appliance list
        try:
            data = json.loads(appliances_json) if isinstance(appliances_json, str) else appliances_json
            if isinstance(data, dict):
                data = data.get("appliances", [data])
            appliances = [Appliance(**item) for item in data]
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            return f"ERROR: invalid appliance data. Fix it and call the tool again. Details: {e}"
        if not appliances:
            return "ERROR: the appliance list is empty."

        # 2) GridSense forecasts for both suppliers
        forecasts = {k: forecast_prices(k, self.target_date) for k in SUPPLIERS}

        # 3) Optimize separately for each supplier
        results = {}
        for key, fc in forecasts.items():
            prices = [row["price_per_kwh"] for row in fc]
            plan = optimize(appliances, prices)
            # Baseline: every appliance starts at its earliest allowed hour
            baseline = optimize([a.model_copy(update={"flexible": False}) for a in appliances], prices)
            plan["baseline_cost"] = baseline["total_cost"]
            results[key] = plan

        cost_a, cost_b = results["A"]["total_cost"], results["B"]["total_cost"]
        best = "A" if cost_a <= cost_b else "B"
        saving = abs(cost_a - cost_b)

        self._last_result = {
            "target_date": self.target_date.isoformat(),
            "appliances": [a.model_dump() for a in appliances],
            "forecasts": forecasts,
            "results": results,
            "recommended": best,
            "daily_saving": round(saving, 4),
        }

        # 4) Compact summary for the LLM (it does not need every forecast detail)
        def cheap_hours(key: str) -> list[int]:
            fc = forecasts[key]
            return [r["hour"] for r in sorted(fc, key=lambda r: r["price_per_kwh"])[:6]]

        summary = {
            "date": self.target_date.isoformat(),
            "supplier_A": {
                "daily_cost_usd": round(cost_a, 2),
                "cost_if_not_optimized_usd": round(results["A"]["baseline_cost"], 2),
                "cheapest_hours": sorted(cheap_hours("A")),
                "schedule": [{k: s[k] for k in ("appliance", "time_slots", "energy_kwh", "cost")} for s in results["A"]["schedules"]],
            },
            "supplier_B": {
                "daily_cost_usd": round(cost_b, 2),
                "cost_if_not_optimized_usd": round(results["B"]["baseline_cost"], 2),
                "cheapest_hours": sorted(cheap_hours("B")),
                "schedule": [{k: s[k] for k in ("appliance", "time_slots", "energy_kwh", "cost")} for s in results["B"]["schedules"]],
            },
            "recommended_supplier": f"Supplier {best}",
            "daily_saving_usd": round(saving, 2),
            "monthly_saving_estimate_usd (30-day extrapolation, not guaranteed)": round(saving * 30, 2),
        }
        return json.dumps(summary, indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# 2. Free DuckDuckGo web search tool
# --------------------------------------------------------------------------- #
class SearchInput(BaseModel):
    query: str = Field(..., description="What to search for, e.g. 'typical dishwasher power rating kW'")


class DuckDuckGoSearchTool(BaseTool):
    name: str = "duckduckgo_search"
    description: str = (
        "Free web search. Use it ONLY to look up typical power ratings (kW) of appliances "
        "that the consumer did not specify. Returns titles, snippets and links."
    )
    args_schema: Type[BaseModel] = SearchInput

    def _run(self, query: str) -> str:
        try:
            hits = DDGS().text(query, max_results=5)
        except Exception as e:  # network errors, rate limits, etc.
            return f"Search failed ({e}). Use a typical value from your own knowledge instead."
        if not hits:
            return "No results. Use a typical value from your own knowledge instead."
        return "\n\n".join(
            f"{i}. {h.get('title', '')}\n{h.get('body', '')}\n{h.get('href', '')}"
            for i, h in enumerate(hits, 1)
        )

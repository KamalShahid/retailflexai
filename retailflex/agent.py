"""
The single RetailFlex AI agent (CrewAI) and the function that runs it.

The agent:
  1. reads the consumer's email and extracts appliance requirements (LLM),
  2. looks up missing power ratings with DuckDuckGo (tool),
  3. calls GridSense-A/B + the optimizer (tool) for exact schedules and costs,
  4. writes a friendly reply email explaining the result (Generative AI).
"""

from __future__ import annotations

from datetime import date

from crewai import LLM, Agent, Crew, Process, Task

from .tools import DuckDuckGoSearchTool, RetailFlexOptimizerTool

GROQ_MODEL = "groq/openai/gpt-oss-120b"  # "groq/" tells CrewAI to use Groq


class GroqLLM(LLM):
    """
    CrewAI marks some messages with a 'cache_breakpoint' flag (used for Anthropic
    prompt caching). Groq rejects unknown message fields, so we remove the flag
    before each request is sent.
    """

    def _format_messages_for_provider(self, messages):
        formatted = super()._format_messages_for_provider(messages)
        return [
            {k: v for k, v in m.items() if k != "cache_breakpoint"} if isinstance(m, dict) else m
            for m in formatted
        ]


def build_llm(api_key: str) -> LLM:
    return GroqLLM(model=GROQ_MODEL, api_key=api_key, temperature=0.2, max_tokens=4000)


def run_retailflex(email_text: str, target_date: date, groq_api_key: str) -> dict:
    """Run the agent. Returns the reply email plus the optimizer's full numbers."""
    optimizer_tool = RetailFlexOptimizerTool(target_date=target_date)
    search_tool = DuckDuckGoSearchTool()

    agent = Agent(
        role="RetailFlex AI Energy Scheduling Agent",
        goal=(
            "Read a consumer's email, extract their appliance needs, find the cheapest "
            "appliance schedule under two competing electricity suppliers, and reply with "
            "a clear, friendly email."
        ),
        backstory=(
            "You are RetailFlex AI, an energy assistant for a competitive retail electricity "
            "market. You understand everyday language, you never invent prices or costs, and "
            "you always rely on the GridSense optimizer tool for every number you report."
        ),
        tools=[optimizer_tool, search_tool],
        llm=build_llm(groq_api_key),
        max_iter=10,
        allow_delegation=False,
        verbose=False,
    )

    task = Task(
        description=f"""
A consumer sent this email to RetailFlex AI:

---
{email_text}
---

The schedule is for: {target_date.strftime('%A, %d %B %Y')}.

Follow these steps:
1. Extract every appliance mentioned: name, power in kW, required hours, allowed window.
   - Convert times to 24-hour integers (9 AM -> 9, 6 PM -> 18, midnight -> 24).
   - "after 6 PM" means earliest_hour=18, latest_hour=24.
   - No window given -> earliest_hour=0, latest_hour=24.
   - Washing machines, dishwashers, dryers and EV chargers are continuous=true.
   - Water pumps, water heaters and air conditioners can be continuous=false (interruptible).
   - Refrigerators/freezers are fixed: flexible=false, hours=24.
2. If a power rating is missing, use duckduckgo_search ONCE per appliance to find a
   typical value. If search fails, use a sensible typical value. Note any assumed values.
3. Call gridsense_schedule_optimizer with the full appliance list as a JSON string.
   If it returns an ERROR, fix the data and call it again.
4. Write the reply email to the consumer using ONLY the numbers returned by the tool.
""",
        expected_output="""
A complete reply email in Markdown, containing:
- A subject line (first line, starting with "Subject:") and a polite greeting.
- A short summary: recommended supplier, both estimated daily costs and the daily saving.
- A Markdown table with columns: Appliance | Supplier A schedule | Supplier B schedule.
- A 2-3 sentence plain-language explanation of WHY the recommended supplier is cheaper
  (mention its cheapest price hours).
- The monthly saving clearly labelled as an estimate (30-day extrapolation, not guaranteed).
- A list of any assumed power ratings.
- Sign-off: "RetailFlex AI".
""",
        agent=agent,
    )

    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
    result = crew.kickoff()

    return {"email": str(result.raw).strip(), "data": optimizer_tool.last_result}

"""What each agent run cost, in calendar.db. Imports nothing from Pydantic AI, so the
app can serve these numbers without loading the agent."""

from typing import TYPE_CHECKING, Any

import aiosqlite

if TYPE_CHECKING:
    from pydantic_ai import RunUsage


async def record(db: aiosqlite.Connection, *, conversation_id: str, surface: str, model: str,
                 usage: "RunUsage") -> None:
    await db.execute(
        """INSERT INTO agent_usage (conversation_id, surface, model, requests, tool_calls,
                                    input_tokens, cache_read_tokens, output_tokens, cost_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (conversation_id, surface, model, usage.requests, usage.tool_calls, usage.input_tokens,
         usage.cache_read_tokens, usage.output_tokens, float(usage.cost) if usage.cost is not None else None),
    )
    await db.commit()


# Speech in and out has rows of its own (surface "voice"): it counts in the cost, not as turns
_TOTALS = """
    COALESCE(SUM(surface != 'voice'), 0) AS runs,
    COUNT(DISTINCT CASE WHEN surface != 'voice' THEN conversation_id END) AS conversations,
    COALESCE(SUM(requests), 0) AS requests,
    COALESCE(SUM(tool_calls), 0) AS tool_calls,
    COALESCE(SUM(input_tokens), 0) AS input_tokens,
    COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
    COALESCE(SUM(output_tokens), 0) AS output_tokens,
    COALESCE(SUM(cost_usd), 0) AS cost_usd,
    COUNT(*) - COUNT(cost_usd) AS unpriced_runs
"""


async def spent_since(db: aiosqlite.Connection, day: str) -> float:
    """What the agent cost from `day` (local) on."""
    row = await (await db.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM agent_usage WHERE date(created_at, 'localtime') >= ?", (day,),
    )).fetchone()
    return float(row[0])


async def summary(db: aiosqlite.Connection, days: int) -> dict[str, Any]:
    """Totals all time and this month, cost per day over the last `days`, and per model."""
    async def rows(query: str, params: tuple = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in await (await db.execute(query, params)).fetchall()]

    all_time = (await rows(f"SELECT {_TOTALS} FROM agent_usage"))[0]
    this_month = (await rows(
        f"SELECT {_TOTALS} FROM agent_usage WHERE date(created_at, 'localtime') >= date('now', 'localtime', 'start of month')",
    ))[0]
    per_day = await rows(
        """SELECT date(created_at, 'localtime') AS date, SUM(surface != 'voice') AS runs,
                  SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
                  COALESCE(SUM(cost_usd), 0) AS cost_usd
           FROM agent_usage
           WHERE date(created_at, 'localtime') >= date('now', 'localtime', ?)
           GROUP BY 1 ORDER BY 1""",
        (f"-{days - 1} days",),
    )
    per_model = await rows(
        """SELECT model, SUM(surface != 'voice') AS runs, SUM(input_tokens) AS input_tokens,
                  SUM(output_tokens) AS output_tokens, COALESCE(SUM(cost_usd), 0) AS cost_usd
           FROM agent_usage GROUP BY model ORDER BY cost_usd DESC""",
    )
    return {"all_time": all_time, "this_month": this_month, "days": per_day, "models": per_model}

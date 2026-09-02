import json
from typing import Any

import asyncpg  # type: ignore[import-untyped]


class Ledger:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=8)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def ping(self) -> bool:
        await self.connect()
        assert self._pool is not None
        value = await self._pool.fetchval("SELECT 1")
        return bool(value == 1)

    async def create_run(self, run_id: str, objective: str, mode: str) -> None:
        await self.connect()
        assert self._pool is not None
        await self._pool.execute(
            "INSERT INTO runs(run_id, objective, mode, status) VALUES($1,$2,$3,'RUNNING') "
            "ON CONFLICT (run_id) DO NOTHING",
            run_id,
            objective,
            mode,
        )

    async def record_agent_result(self, run_id: str, result: dict[str, Any]) -> None:
        await self.connect()
        assert self._pool is not None
        await self._pool.execute(
            """
            INSERT INTO agent_results(
                run_id, agent, model, prompt_version, provider_request_id,
                latency_ms, input_tokens, output_tokens, total_tokens, result_json
            ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)
            """,
            run_id,
            str(result.get("agent", "unknown")),
            str(result.get("model", "unknown")),
            str(result.get("prompt_version", "unknown")),
            _str_or_none(result.get("provider_request_id")),
            _int_or_none(result.get("latency_ms")),
            _int_or_none(result.get("input_tokens")),
            _int_or_none(result.get("output_tokens")),
            _int_or_none(result.get("total_tokens")),
            json.dumps(result),
        )

    async def record_evidence(self, run_id: str, items: list[dict[str, Any]]) -> None:
        """Persist immutable evidence IDs while allowing the latest run association to refresh."""
        if not items:
            return
        await self.connect()
        assert self._pool is not None
        async with self._pool.acquire() as connection, connection.transaction():
            for item in items:
                await connection.execute(
                    """
                    INSERT INTO evidence(
                        evidence_id, run_id, source, site_id, kind, observed_at,
                        period_start, period_end, source_property, payload_hash,
                        summary, payload
                    ) VALUES(
                        $1,$2,$3,$4,$5,$6::timestamptz,$7::date,$8::date,$9,$10,$11,$12::jsonb
                    )
                    ON CONFLICT (evidence_id) DO UPDATE SET
                        run_id = EXCLUDED.run_id,
                        observed_at = EXCLUDED.observed_at,
                        summary = EXCLUDED.summary,
                        payload = EXCLUDED.payload
                    """,
                    str(item["evidence_id"]),
                    run_id,
                    str(item["source"]),
                    str(item["site_id"]),
                    str(item["kind"]),
                    str(item["observed_at"]),
                    _str_or_none(item.get("period_start")),
                    _str_or_none(item.get("period_end")),
                    str(item["source_property"]),
                    str(item["payload_hash"]),
                    str(item["summary"]),
                    json.dumps(item.get("payload", {})),
                )

    async def complete_run(self, run_id: str, status: str, result: dict[str, Any]) -> None:
        await self.connect()
        assert self._pool is not None
        await self._pool.execute(
            "UPDATE runs SET status=$2, result_json=$3::jsonb, completed_at=now() WHERE run_id=$1",
            run_id,
            status,
            json.dumps(result),
        )

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        await self.connect()
        assert self._pool is not None
        row = await self._pool.fetchrow(
            "SELECT run_id, objective, mode, status, result_json, created_at, completed_at "
            "FROM runs WHERE run_id=$1",
            run_id,
        )
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "objective": row["objective"],
            "mode": row["mode"],
            "status": row["status"],
            "result": row["result_json"],
            "created_at": row["created_at"].isoformat(),
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        }

    async def find_run_by_prefix(self, prefix: str) -> str | None:
        """Resolve a shortened run reference (e.g. the idempotency digest) to a full run_id."""
        if not prefix:
            return None
        await self.connect()
        assert self._pool is not None
        row = await self._pool.fetchrow(
            "SELECT run_id FROM runs WHERE run_id LIKE $1 || '%' ORDER BY created_at DESC LIMIT 1",
            prefix,
        )
        return row["run_id"] if row else None

    async def recent_runs(self, limit: int) -> list[dict[str, Any]]:
        """Recent completed runs for context injection. Only objective + chosen
        interventions are surfaced — findings stay out of history to keep payloads small."""
        await self.connect()
        assert self._pool is not None
        rows = await self._pool.fetch(
            """
            SELECT run_id, objective, result_json
            FROM runs
            WHERE status = 'DONE' AND result_json IS NOT NULL
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            result = row["result_json"]
            result = result if isinstance(result, dict) else json.loads(result) if result else {}
            titles = [
                str(item.get("title", ""))
                for item in (result.get("interventions") or [])
                if isinstance(item, dict)
            ]
            out.append(
                {
                    "run_id": row["run_id"],
                    "objective": row["objective"],
                    "intervention_titles": titles,
                }
            )
        return out

    async def recent_feedback(self, limit: int) -> list[dict[str, Any]]:
        """Operator verdicts on past interventions — the feedback loop's memory."""
        await self.connect()
        assert self._pool is not None
        rows = await self._pool.fetch(
            """
            SELECT run_id, intervention_rank, verdict, outcome_note, metrics_delta
            FROM intervention_feedback
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def record_feedback(
        self, run_id: str, intervention_rank: int, verdict: str, outcome_note: str | None
    ) -> None:
        await self.connect()
        assert self._pool is not None
        await self._pool.execute(
            """
            INSERT INTO intervention_feedback(
                run_id, intervention_rank, verdict, outcome_note
            ) VALUES($1,$2,$3,$4)
            """,
            run_id,
            intervention_rank,
            verdict,
            outcome_note,
        )


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None

import json
from typing import Any

import asyncpg


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
        return value == 1

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


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None

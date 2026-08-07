from __future__ import annotations

import asyncio
import threading
import unittest
from typing import Any

from backend.app.config import Settings
from backend.app.integrations.snowflake.client import (
    SnowflakeAdapter,
    SnowflakeConnectionPool,
    SnowflakeErrorCode,
    SnowflakeProviderError,
)


class _Cursor:
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection
        self.description: list[tuple[str, ...]] | None = None
        self.rowcount = 1
        self.sfqid = "query-1"

    def execute(self, sql: str, parameters: Any = None) -> None:
        self._connection.statements.append((sql, parameters))
        if self._connection.failure is not None:
            raise self._connection.failure
        self.description = [(name,) for name in self._connection.columns]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return [tuple(self._connection.row[name] for name in self._connection.columns)]

    def close(self) -> None:
        return None


class _Connection:
    def __init__(self, columns: tuple[str, ...], row: dict[str, Any]) -> None:
        self.columns = columns
        self.row = row
        self.statements: list[tuple[str, Any]] = []
        self.failure: Exception | None = None
        self.closed = False

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        return None

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class SnowflakeConnectionPoolTests(unittest.TestCase):
    def test_a_returned_connection_is_reused_instead_of_reauthenticated(self) -> None:
        opened: list[object] = []

        def factory() -> _Connection:
            connection = _Connection(("value",), {"value": 1})
            opened.append(connection)
            return connection

        pool = SnowflakeConnectionPool(factory, max_size=2)

        first = pool.acquire()
        pool.release(first, reusable=True)
        second = pool.acquire()
        pool.release(second, reusable=True)

        self.assertIs(first, second)
        self.assertEqual(len(opened), 1)
        self.assertEqual(pool.stats.opened, 1)
        self.assertEqual(pool.stats.reused, 1)

    def test_an_unusable_connection_is_discarded_rather_than_pooled(self) -> None:
        pool = SnowflakeConnectionPool(lambda: _Connection(("value",), {"value": 1}), max_size=2)

        first = pool.acquire()
        pool.release(first, reusable=False)
        second = pool.acquire()

        self.assertIsNot(first, second)
        self.assertTrue(first.closed)
        self.assertEqual(pool.stats.discarded, 1)
        pool.release(second, reusable=True)

    def test_an_idle_connection_past_its_lifetime_is_replaced(self) -> None:
        pool = SnowflakeConnectionPool(
            lambda: _Connection(("value",), {"value": 1}),
            max_size=2,
            max_idle_seconds=0.01,
        )

        first = pool.acquire()
        pool.release(first, reusable=True)
        _sleep(0.05)
        second = pool.acquire()

        self.assertIsNot(first, second)
        self.assertTrue(first.closed)
        pool.release(second, reusable=True)

    def test_the_pool_never_exceeds_its_configured_size(self) -> None:
        pool = SnowflakeConnectionPool(
            lambda: _Connection(("value",), {"value": 1}),
            max_size=1,
            acquire_timeout_seconds=0.05,
        )
        leased = pool.acquire()

        with self.assertRaises(SnowflakeProviderError) as caught:
            pool.acquire()

        self.assertEqual(caught.exception.code, SnowflakeErrorCode.TIMEOUT)
        pool.release(leased, reusable=True)

    def test_a_waiting_caller_is_handed_the_next_released_connection(self) -> None:
        pool = SnowflakeConnectionPool(
            lambda: _Connection(("value",), {"value": 1}),
            max_size=1,
            acquire_timeout_seconds=2.0,
        )
        leased = pool.acquire()
        handed: list[object] = []

        def waiter() -> None:
            handed.append(pool.acquire())

        thread = threading.Thread(target=waiter)
        thread.start()
        _sleep(0.05)
        pool.release(leased, reusable=True)
        thread.join(timeout=2)

        self.assertEqual(handed, [leased])

    def test_a_failed_factory_releases_the_reserved_slot(self) -> None:
        attempts: list[int] = []

        def factory() -> _Connection:
            attempts.append(1)
            raise RuntimeError("login refused")

        pool = SnowflakeConnectionPool(factory, max_size=1, acquire_timeout_seconds=0.2)

        for _ in range(2):
            with self.assertRaises(RuntimeError):
                pool.acquire()

        self.assertEqual(len(attempts), 2)

    def test_close_releases_pooled_connections(self) -> None:
        pool = SnowflakeConnectionPool(lambda: _Connection(("value",), {"value": 1}), max_size=2)
        connection = pool.acquire()
        pool.release(connection, reusable=True)

        pool.close()

        self.assertTrue(connection.closed)
        with self.assertRaises(SnowflakeProviderError):
            pool.acquire()


class SnowflakeAdapterPoolingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            snowflake_account="acct",
            snowflake_user="svc",
            snowflake_password="secret",
            snowflake_role="role",
            snowflake_warehouse="wh",
            snowflake_database="db",
            snowflake_schema="schema",
        )
        self.adapter = SnowflakeAdapter(self.settings)
        self.connections: list[_Connection] = []

        def factory() -> _Connection:
            connection = _Connection(
                ("input_tokens", "completion"),
                {"input_tokens": 128, "completion": '{"structured_output":{}}'},
            )
            self.connections.append(connection)
            return connection

        self.adapter._pool = SnowflakeConnectionPool(factory, max_size=2)  # noqa: SLF001

    def test_sequential_queries_share_one_authenticated_connection(self) -> None:
        async def scenario() -> None:
            await self.adapter.scalar("SELECT 1")
            await self.adapter.scalar("SELECT 2")

        asyncio.run(scenario())

        self.assertEqual(len(self.connections), 1)
        self.assertEqual(self.adapter.pool_stats.opened, 1)
        self.assertEqual(self.adapter.pool_stats.reused, 1)

    def test_token_count_and_completion_use_one_round_trip(self) -> None:
        async def scenario() -> tuple[Any, Any]:
            return await self.adapter.count_and_complete(
                "claude-haiku-4-5",
                "prompt",
                model_parameters={"temperature": 0.0},
                response_format={"type": "json"},
            )

        estimate, completion = asyncio.run(scenario())

        self.assertEqual(len(self.connections), 1)
        self.assertEqual(len(self.connections[0].statements), 1)
        statement = self.connections[0].statements[0][0]
        self.assertIn("AI_COUNT_TOKENS", statement)
        self.assertIn("AI_COMPLETE", statement)
        self.assertEqual(estimate.value, 128)
        self.assertEqual(completion.value, '{"structured_output":{}}')

    def test_a_transport_failure_does_not_return_the_connection_to_the_pool(self) -> None:
        async def scenario() -> None:
            await self.adapter.scalar("SELECT 1")
            self.connections[0].failure = TimeoutError("network stalled")
            with self.assertRaises(SnowflakeProviderError):
                await self.adapter.scalar("SELECT 2")
            self.connections[-1].failure = None
            await self.adapter.scalar("SELECT 3")

        asyncio.run(scenario())

        self.assertEqual(len(self.connections), 2)
        self.assertTrue(self.connections[0].closed)

    def test_pooled_connections_keep_their_session_alive(self) -> None:
        parameters = self.adapter._connection_parameters()  # noqa: SLF001

        self.assertTrue(parameters["client_session_keep_alive"])


def _sleep(seconds: float) -> None:
    event = threading.Event()
    event.wait(seconds)


if __name__ == "__main__":
    unittest.main()

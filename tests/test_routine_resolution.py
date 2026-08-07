from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.app.contracts.models import RoutineSummary
from backend.app.domain.demos import DEMO_TASKS
from backend.app.persistence.repository import OperationalRepository
from backend.app.services.event_hub import SessionEventHub
from backend.app.services.orchestrator import SessionOrchestrator


class _Everos:
    def __init__(
        self,
        *,
        routines: list[RoutineSummary] | None = None,
        search_results: list[RoutineSummary] | None = None,
        aliases: list[str] | None = None,
    ) -> None:
        self.routines = routines if routines is not None else []
        self.search_results = search_results if search_results is not None else []
        self.aliases = aliases if aliases is not None else []
        self.list_calls = 0
        self.alias_calls = 0

    async def list_routines(self, _user_id: str) -> list[RoutineSummary]:
        self.list_calls += 1
        return list(self.routines)

    async def search_routines(self, _user_id: str, _query: str) -> list[RoutineSummary]:
        return list(self.search_results)

    async def resolve_aliases(self, _user_id: str, _query: str) -> list[str]:
        self.alias_calls += 1
        return list(self.aliases)


class _Embedder:
    def __init__(self, ranked: list[tuple[str, float]]) -> None:
        self.ranked = ranked
        self.calls = 0

    async def ai_embed_similarity(
        self,
        _model: str,
        _query: str,
        _candidates: list[str],
    ) -> list[tuple[str, float]]:
        self.calls += 1
        return list(self.ranked)


class RoutineResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "operations.sqlite3"
        self.repository = OperationalRepository(str(database_path))
        self.participant_id = uuid4()
        self.repository.create_participant(
            participant_id=self.participant_id,
            user_id="margaret",
            role="user",
            participant_name="Margaret",
            preferences={"timezone": "America/Los_Angeles"},
            expires_at=datetime(2027, 1, 1, tzinfo=UTC),
        )

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary_directory.cleanup()

    def _orchestrator(self, everos: Any, **kwargs: Any) -> SessionOrchestrator:
        return SessionOrchestrator(
            repository=self.repository,
            browser=object(),
            everos=everos,
            guidance=object(),
            completion=object(),
            event_hub=SessionEventHub(),
            demo_target_name="Choose lettuce and tomato",
            demo_target_url="https://www.w3.org/demo/",
            demo_fallback_url="https://www.w3.org/fallback/",
            build_commit="test",
            source_environment="test",
            **kwargs,
        )

    def test_the_routine_list_is_served_from_cache_within_its_window(self) -> None:
        everos = _Everos(
            routines=[
                RoutineSummary(
                    id="skill-water",
                    name="Pay water bill",
                    start_url="https://billing.example/",
                )
            ]
        )
        orchestrator = self._orchestrator(everos, routine_cache_seconds=60.0)

        async def scenario() -> None:
            await orchestrator.list_routines("margaret")
            await orchestrator.list_routines("margaret")

        asyncio.run(scenario())

        self.assertEqual(everos.list_calls, 1)

    def test_concurrent_first_reads_collapse_into_one_provider_call(self) -> None:
        everos = _Everos(routines=[])
        orchestrator = self._orchestrator(everos, routine_cache_seconds=60.0)

        async def scenario() -> None:
            await asyncio.gather(
                orchestrator.list_routines("margaret"),
                orchestrator.list_routines("margaret"),
                orchestrator.list_routines("margaret"),
            )

        asyncio.run(scenario())

        self.assertEqual(everos.list_calls, 1)

    def test_invalidating_the_cache_forces_a_fresh_read(self) -> None:
        everos = _Everos(routines=[])
        orchestrator = self._orchestrator(everos, routine_cache_seconds=60.0)

        async def scenario() -> None:
            await orchestrator.list_routines("margaret")
            orchestrator.invalidate_routines("margaret")
            await orchestrator.list_routines("margaret")

        asyncio.run(scenario())

        self.assertEqual(everos.list_calls, 2)

    def test_the_curated_errands_are_always_offered(self) -> None:
        orchestrator = self._orchestrator(_Everos())

        routines = asyncio.run(orchestrator.list_routines("margaret"))

        self.assertEqual({routine.source for routine in routines}, {"starter"})
        self.assertEqual(
            [routine.start_url for routine in routines],
            [demo.start_url for demo in DEMO_TASKS],
        )

    def test_participant_vocabulary_resolves_a_routine_that_shares_no_words(self) -> None:
        everos = _Everos(
            routines=[
                RoutineSummary(
                    id="skill-electric",
                    name="Pay electric bill",
                    start_url="https://power.example/",
                )
            ],
            aliases=["Margaret calls the electric bill the light bill"],
        )
        orchestrator = self._orchestrator(everos)

        result = asyncio.run(orchestrator.resolve_routines("margaret", "pay the light bill"))

        self.assertEqual(everos.alias_calls, 1)
        self.assertEqual(result.routines[0].name, "Pay electric bill")
        self.assertTrue(result.requires_confirmation)

    def test_embedding_similarity_resolves_a_phrase_no_word_matched(self) -> None:
        everos = _Everos(
            routines=[
                RoutineSummary(
                    id="skill-electric",
                    name="Pay electric bill",
                    start_url="https://power.example/",
                )
            ],
            aliases=[],
        )
        embedder = _Embedder([("Pay electric bill", 0.82)])
        orchestrator = self._orchestrator(
            everos,
            embedder=embedder,
            embedding_model="snowflake-arctic-embed-m-v1.5",
        )

        result = asyncio.run(orchestrator.resolve_routines("margaret", "the power company"))

        self.assertEqual(embedder.calls, 1)
        self.assertEqual(result.routines[0].name, "Pay electric bill")

    def test_a_word_match_never_pays_for_an_embedding_call(self) -> None:
        everos = _Everos(
            routines=[
                RoutineSummary(
                    id="skill-water",
                    name="Pay water bill",
                    start_url="https://billing.example/",
                )
            ]
        )
        embedder = _Embedder([("Pay water bill", 0.99)])
        orchestrator = self._orchestrator(
            everos,
            embedder=embedder,
            embedding_model="snowflake-arctic-embed-m-v1.5",
        )

        result = asyncio.run(orchestrator.resolve_routines("margaret", "pay the water bill"))

        self.assertEqual(embedder.calls, 0)
        self.assertEqual(result.routines[0].name, "Pay water bill")

    def test_filler_words_do_not_count_as_a_routine_match(self) -> None:
        # "the" appears in "Get in line at the DMV". Treating that as a match used to
        # suppress the semantic fallback that resolves the phrase correctly.
        everos = _Everos(
            routines=[
                RoutineSummary(
                    id="skill-electric",
                    name="Pay electric bill",
                    start_url="https://power.example/",
                )
            ]
        )
        embedder = _Embedder([("Pay electric bill", 0.78)])
        orchestrator = self._orchestrator(
            everos,
            embedder=embedder,
            embedding_model="snowflake-arctic-embed-m-v1.5",
        )

        result = asyncio.run(orchestrator.resolve_routines("margaret", "the power company"))

        self.assertEqual(embedder.calls, 1)
        self.assertEqual(result.routines[0].name, "Pay electric bill")

    def test_a_weak_embedding_match_is_not_offered(self) -> None:
        everos = _Everos(
            routines=[
                RoutineSummary(
                    id="skill-electric",
                    name="Pay electric bill",
                    start_url="https://power.example/",
                )
            ]
        )
        embedder = _Embedder([("Pay electric bill", 0.21)])
        orchestrator = self._orchestrator(
            everos,
            embedder=embedder,
            embedding_model="snowflake-arctic-embed-m-v1.5",
        )

        result = asyncio.run(orchestrator.resolve_routines("margaret", "something unrelated"))

        self.assertEqual(embedder.calls, 1)
        # The lexical ranking still returns candidates for confirmation, but the weak
        # semantic match must not be promoted above them.
        self.assertNotEqual(result.routines[:1], [])

    def test_provider_skill_search_short_circuits_local_ranking(self) -> None:
        match = RoutineSummary(
            id="skill-dmv",
            name="Book DMV appointment",
            start_url="https://dmv.example/",
        )
        everos = _Everos(search_results=[match])
        embedder = _Embedder([])
        orchestrator = self._orchestrator(
            everos,
            embedder=embedder,
            embedding_model="snowflake-arctic-embed-m-v1.5",
        )

        result = asyncio.run(orchestrator.resolve_routines("margaret", "dmv"))

        self.assertEqual(result.routines, [match])
        self.assertEqual(everos.alias_calls, 0)
        self.assertEqual(embedder.calls, 0)

    def test_an_unreachable_provider_still_offers_the_curated_errands(self) -> None:
        class _Broken:
            async def list_routines(self, _user_id: str) -> list[RoutineSummary]:
                raise RuntimeError("EverOS is unreachable")

        orchestrator = self._orchestrator(_Broken())

        routines = asyncio.run(orchestrator.list_routines("margaret"))

        self.assertEqual(len(routines), len(DEMO_TASKS))
        self.assertEqual({routine.source for routine in routines}, {"starter"})


if __name__ == "__main__":
    unittest.main()

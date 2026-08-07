from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from backend.app.contracts.models import (
    AgentActionKind,
    AgentPlan,
    AgentRunState,
    AgentStepStatus,
    BoundingRect,
    ElementCandidate,
    SafetyClassification,
    SensitivityFlag,
)
from backend.app.domain.demos import DEMO_TASKS, DEMO_TASKS_BY_ID, is_allowlisted, origin_of
from backend.app.services.autopilot import AutopilotService
from backend.app.services.event_hub import SessionEventHub


@dataclass(frozen=True)
class _Outcome:
    performed: bool
    failure: str | None = None
    attempted_at: datetime = datetime.now(UTC)


@dataclass(frozen=True)
class _PageState:
    origin: str = "https://www.greatclips.com"
    redacted_path: str = "/salons"
    title: str | None = "Great Clips Online Check-In"


def _candidate(
    candidate_id: str,
    *,
    flags: list[SensitivityFlag] | None = None,
    name: str = "Continue",
) -> ElementCandidate:
    return ElementCandidate(
        candidate_id=candidate_id,
        role="button",
        accessible_name=name,
        tag_name="button",
        visible=True,
        enabled=True,
        focusable=True,
        bounding_rect=BoundingRect(x=0, y=0, width=100, height=40),
        sensitivity_flags=flags or [],
    )


class _Browser:
    def __init__(
        self,
        candidates: list[ElementCandidate],
        outcomes: list[_Outcome] | None = None,
    ) -> None:
        self.candidates = candidates
        self.outcomes = outcomes or []
        self.actions: list[dict[str, Any]] = []

    async def snapshot(self, _session_id: Any) -> list[ElementCandidate]:
        return list(self.candidates)

    async def page_state(self, _session_id: Any) -> _PageState:
        return _PageState()

    async def act(self, _session_id: Any, **kwargs: Any) -> _Outcome:
        self.actions.append(kwargs)
        if self.outcomes:
            return self.outcomes.pop(0)
        return _Outcome(True)


class _Planner:
    def __init__(self, plans: list[AgentPlan]) -> None:
        self.plans = plans
        self.calls = 0
        self.last_history: list[str] = []

    async def plan(self, **kwargs: Any) -> AgentPlan | None:
        self.calls += 1
        self.last_history = list(kwargs.get("history") or [])
        if not self.plans:
            return None
        return self.plans.pop(0)


class _Repository:
    pass


class AutopilotTests(unittest.TestCase):
    def _service(self, browser: Any, planner: Any, **kwargs: Any) -> AutopilotService:
        return AutopilotService(
            browser=browser,
            planner=planner,
            event_hub=SessionEventHub(),
            repository=_Repository(),
            **kwargs,
        )

    def _run(self, service: AutopilotService, session_id: Any) -> Any:
        async def scenario() -> Any:
            await service.start(
                session_id=session_id,
                user_id="margaret",
                task_name="Book a haircut",
                prompt="Book a haircut at the closest salon",
                start_url="https://www.greatclips.com/salons/online-check-in",
            )
            run = service.get(session_id)
            assert run is not None and run.task is not None
            await run.task
            return service.view(session_id)

        return asyncio.run(scenario())

    def test_the_agent_performs_actions_itself_and_narrates_each_one(self) -> None:
        browser = _Browser([_candidate("c1"), _candidate("c2", name="10:30 AM")])
        planner = _Planner(
            [
                AgentPlan(
                    action=AgentActionKind.CLICK,
                    candidate_id="c1",
                    narration="Opening the salon finder",
                    confidence=0.9,
                ),
                AgentPlan(
                    action=AgentActionKind.CLICK,
                    candidate_id="c2",
                    narration="Choosing the earliest time",
                    confidence=0.9,
                ),
                AgentPlan(
                    action=AgentActionKind.DONE,
                    narration="Your haircut is booked for 10:30 AM",
                    task_complete=True,
                    confidence=0.95,
                ),
            ]
        )
        service = self._service(browser, planner)

        view = self._run(service, uuid4())

        self.assertEqual(view.state, AgentRunState.COMPLETED)
        self.assertEqual(len(browser.actions), 2)
        self.assertEqual([action["candidate_id"] for action in browser.actions], ["c1", "c2"])
        self.assertEqual(
            [step.narration for step in view.steps],
            [
                "Opening the salon finder",
                "Choosing the earliest time",
                "Your haircut is booked for 10:30 AM",
            ],
        )
        self.assertTrue(all(step.status is AgentStepStatus.DONE for step in view.steps))

    def test_narration_never_leaks_selectors_to_the_participant(self) -> None:
        browser = _Browser([_candidate("c1")])
        planner = _Planner(
            [
                AgentPlan(
                    action=AgentActionKind.FILL,
                    candidate_id="c1",
                    value="95014",
                    narration="Typing your zip code",
                    confidence=0.9,
                ),
                AgentPlan(action=AgentActionKind.DONE, narration="All set", task_complete=True),
            ]
        )
        service = self._service(browser, planner)

        view = self._run(service, uuid4())

        for step in view.steps:
            self.assertNotIn("c1", step.narration)
            self.assertNotIn("candidate", step.narration.lower())

    def test_a_payment_step_stops_the_run_for_a_decision(self) -> None:
        browser = _Browser([_candidate("pay", name="Place your order")])
        planner = _Planner(
            [
                AgentPlan(
                    action=AgentActionKind.CLICK,
                    candidate_id="pay",
                    narration="Placing the order",
                    safety_classification=SafetyClassification.MONEY,
                    confidence=0.9,
                )
            ]
        )
        service = self._service(browser, planner)

        view = self._run(service, uuid4())

        self.assertEqual(view.state, AgentRunState.NEEDS_CONFIRMATION)
        self.assertEqual(browser.actions, [])
        assert view.pending_confirmation is not None
        self.assertIn("spend money", view.pending_confirmation.message)
        self.assertEqual(view.steps[-1].status, AgentStepStatus.BLOCKED)

    def test_a_password_field_is_never_typed_into(self) -> None:
        browser = _Browser([_candidate("pw", flags=[SensitivityFlag.PASSWORD], name="Password")])
        planner = _Planner(
            [
                AgentPlan(
                    action=AgentActionKind.FILL,
                    candidate_id="pw",
                    value="hunter2",
                    narration="Signing in",
                    confidence=0.9,
                )
            ]
        )
        service = self._service(browser, planner)

        view = self._run(service, uuid4())

        self.assertEqual(view.state, AgentRunState.NEEDS_CONFIRMATION)
        self.assertEqual(browser.actions, [])
        assert view.pending_confirmation is not None
        self.assertIn("never type one", view.pending_confirmation.message)

    def test_adding_to_a_cart_is_reversible_and_proceeds(self) -> None:
        browser = _Browser([_candidate("cart", name="Add to cart")])
        planner = _Planner(
            [
                AgentPlan(
                    action=AgentActionKind.CLICK,
                    candidate_id="cart",
                    narration="Adding milk to your cart",
                    safety_classification=SafetyClassification.SAFE,
                    confidence=0.9,
                ),
                AgentPlan(
                    action=AgentActionKind.DONE,
                    narration="Your cart is ready to review",
                    task_complete=True,
                ),
            ]
        )
        service = self._service(browser, planner)

        view = self._run(service, uuid4())

        self.assertEqual(view.state, AgentRunState.COMPLETED)
        self.assertEqual(len(browser.actions), 1)

    def test_leaving_the_starting_site_stops_for_a_decision(self) -> None:
        browser = _Browser([_candidate("link")])
        planner = _Planner(
            [
                AgentPlan(
                    action=AgentActionKind.NAVIGATE,
                    url="https://unknown-prize-site.example/claim",
                    narration="Following that link",
                    confidence=0.9,
                )
            ]
        )
        service = self._service(browser, planner)

        view = self._run(service, uuid4())

        self.assertEqual(view.state, AgentRunState.NEEDS_CONFIRMATION)
        self.assertEqual(browser.actions, [])
        assert view.pending_confirmation is not None
        self.assertIn("leaves the site we started on", view.pending_confirmation.message)

    def test_navigating_inside_the_starting_site_proceeds(self) -> None:
        browser = _Browser([_candidate("link")])
        planner = _Planner(
            [
                AgentPlan(
                    action=AgentActionKind.NAVIGATE,
                    url="https://www.greatclips.com/salons/ca",
                    narration="Opening the salon list",
                    confidence=0.9,
                ),
                AgentPlan(action=AgentActionKind.DONE, narration="Found it", task_complete=True),
            ]
        )
        service = self._service(browser, planner)

        view = self._run(service, uuid4())

        self.assertEqual(view.state, AgentRunState.COMPLETED)
        self.assertEqual(len(browser.actions), 1)

    def test_a_failed_action_is_reported_without_ending_the_run(self) -> None:
        browser = _Browser(
            [_candidate("c1")],
            outcomes=[_Outcome(False, "that target was not ready to use"), _Outcome(True)],
        )
        planner = _Planner(
            [
                AgentPlan(
                    action=AgentActionKind.CLICK, candidate_id="c1", narration="Trying the button"
                ),
                AgentPlan(
                    action=AgentActionKind.CLICK, candidate_id="c1", narration="Trying again"
                ),
                AgentPlan(action=AgentActionKind.DONE, narration="Done", task_complete=True),
            ]
        )
        service = self._service(browser, planner)

        view = self._run(service, uuid4())

        self.assertEqual(view.state, AgentRunState.COMPLETED)
        self.assertEqual(view.steps[0].status, AgentStepStatus.FAILED)
        self.assertEqual(view.steps[0].detail, "that target was not ready to use")

    def test_the_planner_sees_what_it_already_did(self) -> None:
        browser = _Browser([_candidate("c1")])
        planner = _Planner(
            [
                AgentPlan(action=AgentActionKind.CLICK, candidate_id="c1", narration="First step"),
                AgentPlan(action=AgentActionKind.DONE, narration="Done", task_complete=True),
            ]
        )
        service = self._service(browser, planner)

        self._run(service, uuid4())

        self.assertEqual(planner.last_history, ["1. First step"])

    def test_a_run_that_never_finishes_stops_at_the_step_ceiling(self) -> None:
        browser = _Browser([_candidate("c1")])

        class _Loop:
            async def plan(self, **_kwargs: Any) -> AgentPlan:
                return AgentPlan(
                    action=AgentActionKind.CLICK,
                    candidate_id="c1",
                    narration="Going around again",
                )

        service = self._service(browser, _Loop(), max_steps=4)

        view = self._run(service, uuid4())

        self.assertEqual(view.state, AgentRunState.FAILED)
        self.assertEqual(len(view.steps), 4)
        self.assertIn("without finishing", view.summary or "")

    def test_an_unavailable_planner_fails_the_run_calmly(self) -> None:
        service = self._service(_Browser([_candidate("c1")]), _Planner([]))

        view = self._run(service, uuid4())

        self.assertEqual(view.state, AgentRunState.FAILED)
        self.assertIn("could not work out the next step", view.summary or "")

    def test_refusing_a_confirmation_ends_the_run_without_acting(self) -> None:
        browser = _Browser([_candidate("pay")])
        planner = _Planner(
            [
                AgentPlan(
                    action=AgentActionKind.CLICK,
                    candidate_id="pay",
                    narration="Paying now",
                    safety_classification=SafetyClassification.MONEY,
                )
            ]
        )
        service = self._service(browser, planner)
        session_id = uuid4()

        async def scenario() -> Any:
            await service.start(
                session_id=session_id,
                user_id="margaret",
                task_name="Pay",
                prompt="pay it",
                start_url="https://www.greatclips.com/",
            )
            run = service.get(session_id)
            assert run is not None and run.task is not None
            await run.task
            return await service.confirm(session_id, approved=False)

        view = asyncio.run(scenario())

        self.assertEqual(view.state, AgentRunState.STOPPED)
        self.assertEqual(browser.actions, [])
        self.assertIn("did not go ahead", view.summary or "")

    def test_stopping_a_run_reports_that_nothing_further_changed(self) -> None:
        browser = _Browser([_candidate("c1")])

        class _Slow:
            async def plan(self, **_kwargs: Any) -> AgentPlan:
                await asyncio.sleep(5)
                return AgentPlan(action=AgentActionKind.DONE, narration="never", task_complete=True)

        service = self._service(browser, _Slow())
        session_id = uuid4()

        async def scenario() -> Any:
            await service.start(
                session_id=session_id,
                user_id="margaret",
                task_name="Book a haircut",
                prompt="book it",
                start_url="https://www.greatclips.com/",
            )
            await asyncio.sleep(0)
            return await service.stop(session_id)

        view = asyncio.run(scenario())

        self.assertEqual(view.state, AgentRunState.STOPPED)
        self.assertIn("Nothing further was changed", view.summary or "")


class DemoCatalogueTests(unittest.TestCase):
    def test_the_three_offered_demos_are_the_promised_errands(self) -> None:
        self.assertEqual(
            [task.id for task in DEMO_TASKS],
            ["dmv-get-in-line", "whole-foods-groceries", "haircut-appointment"],
        )
        self.assertEqual(
            {task.category for task in DEMO_TASKS},
            {"government", "shopping", "appointment"},
        )

    def test_every_demo_starts_on_a_real_allowlisted_site(self) -> None:
        for task in DEMO_TASKS:
            with self.subTest(task=task.id):
                self.assertTrue(task.start_url.startswith("https://"))
                self.assertTrue(is_allowlisted(task.start_url))
                self.assertNotIn("w3.org", task.start_url)

    def test_every_demo_carries_a_prompt_the_agent_can_act_on(self) -> None:
        for task in DEMO_TASKS:
            with self.subTest(task=task.id):
                self.assertGreater(len(task.prompt), 20)
                self.assertEqual(DEMO_TASKS_BY_ID[task.id], task)

    def test_the_www_and_bare_forms_of_an_origin_both_pass(self) -> None:
        self.assertTrue(is_allowlisted("https://www.amazon.com/cart"))
        self.assertTrue(is_allowlisted("https://amazon.com/cart"))
        self.assertFalse(is_allowlisted("https://amazon.com.evil.example/cart"))

    def test_an_unrelated_origin_is_not_allowlisted(self) -> None:
        self.assertFalse(is_allowlisted("https://unknown-prize-site.example/claim"))
        self.assertEqual(origin_of("https://Example.COM/path?x=1"), "https://example.com")


if __name__ == "__main__":
    unittest.main()

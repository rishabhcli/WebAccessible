from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from backend.app.browser.controller import is_provider_block
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
from backend.app.domain.demos import DEMO_TASKS, DEMO_TASKS_BY_ID, origin_of
from backend.app.services.autopilot import AutopilotService, LocalActionPlanner
from backend.app.services.event_hub import SessionEventHub


@dataclass(frozen=True)
class _Outcome:
    performed: bool
    failure: str | None = None
    attempted_at: datetime = datetime.now(UTC)


@dataclass(frozen=True)
class _PageState:
    origin: str = "https://booksy.com"
    redacted_path: str = "/en-us/s"
    title: str | None = "Find services, compare prices & reviews"
    blocked: bool = False


def _candidate(
    candidate_id: str,
    *,
    flags: list[SensitivityFlag] | None = None,
    name: str = "Continue",
    href_origin: str | None = None,
    tag_name: str = "button",
    role: str = "button",
    input_type: str | None = None,
) -> ElementCandidate:
    return ElementCandidate(
        candidate_id=candidate_id,
        role=role,
        accessible_name=name,
        tag_name=tag_name,
        input_type=input_type,
        visible=True,
        enabled=True,
        focusable=True,
        bounding_rect=BoundingRect(x=0, y=0, width=100, height=40),
        sensitivity_flags=flags or [],
        href_origin=href_origin,
    )


def _field(candidate_id: str, name: str, input_type: str = "text") -> ElementCandidate:
    return _candidate(
        candidate_id,
        name=name,
        tag_name="input",
        role="textbox",
        input_type=input_type,
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


class _CompletingBrowser(_Browser):
    """Reports the page as finished once the form has actually been submitted."""

    def __init__(self, candidates: list[ElementCandidate]) -> None:
        super().__init__(candidates)
        self.submitted = False

    async def act(self, session_id: Any, **kwargs: Any) -> _Outcome:
        if kwargs.get("action") is AgentActionKind.CLICK:
            self.submitted = True
        return await super().act(session_id, **kwargs)

    async def page_state(self, _session_id: Any) -> _PageState:
        return _PageState(title="Task complete") if self.submitted else _PageState()


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

    def _run(
        self,
        service: AutopilotService,
        session_id: Any,
        prompt: str = "Book a haircut at the closest salon",
    ) -> Any:
        async def scenario() -> Any:
            await service.start(
                session_id=session_id,
                user_id="margaret",
                task_name="Book a haircut",
                prompt=prompt,
                start_url="https://booksy.com/en-us/s/haircut",
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

    def test_navigating_inside_the_starting_site_proceeds(self) -> None:
        browser = _Browser([_candidate("link")])
        planner = _Planner(
            [
                AgentPlan(
                    action=AgentActionKind.NAVIGATE,
                    url="https://booksy.com/en-us/s/haircut/queens",
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

    def test_scrolling_one_page_cannot_swallow_the_whole_run(self) -> None:
        # A live run on the California DMV queue spent 23 consecutive steps scrolling for a
        # San Francisco office it never recognised. A scroll carries no candidate and no
        # url, so nothing was recorded against the page, and the viewport moving does not
        # change the page key either -- so the repeat guard never engaged.
        browser = _Browser(
            [
                _candidate(
                    "row",
                    name="BISHOP 1115 West Line Street, BISHOP",
                    role="listitem",
                    tag_name="div",
                )
            ]
        )

        class _Scroller:
            def __init__(self) -> None:
                self.prompts: list[str] = []

            async def plan(self, **kwargs: Any) -> AgentPlan:
                self.prompts.append(str(kwargs.get("prompt")))
                return AgentPlan(
                    action=AgentActionKind.SCROLL,
                    narration="Scrolling down to find the San Francisco DMV office.",
                )

        planner = _Scroller()
        service = self._service(browser, planner)

        view = self._run(service, uuid4(), prompt=DEMO_TASKS_BY_ID["dmv-get-in-line"].prompt)

        scrolls = [
            action for action in browser.actions if action["action"] is AgentActionKind.SCROLL
        ]
        self.assertLessEqual(len(scrolls), 4, "one page may not be scrolled indefinitely")
        self.assertEqual(view.state, AgentRunState.FAILED)
        self.assertLess(len(view.steps), 24, "the step budget must not be spent on scrolling")
        self.assertTrue(
            any("do not scroll" in prompt for prompt in planner.prompts),
            "the planner has to be told it already scrolled this page",
        )

    def test_a_couple_of_scrolls_down_a_long_list_are_still_allowed(self) -> None:
        # Bounding the loop must not ban scrolling: looking down a long list of offices is
        # exactly what a scroll is for.
        browser = _Browser([_candidate("c1")])
        planner = _Planner(
            [
                AgentPlan(action=AgentActionKind.SCROLL, narration="Looking further down."),
                AgentPlan(action=AgentActionKind.SCROLL, narration="Looking further down."),
                AgentPlan(
                    action=AgentActionKind.CLICK, candidate_id="c1", narration="Choosing Continue."
                ),
                AgentPlan(action=AgentActionKind.DONE, narration="Done.", task_complete=True),
            ]
        )
        service = self._service(browser, planner)

        view = self._run(service, uuid4())

        self.assertEqual(view.state, AgentRunState.COMPLETED)
        self.assertEqual(
            [action["action"] for action in browser.actions],
            [AgentActionKind.SCROLL, AgentActionKind.SCROLL, AgentActionKind.CLICK],
        )

    def test_the_office_the_task_named_is_chosen_over_a_different_one(self) -> None:
        # A live DMV run joined the queue at BISHOP, then at CHULA VISTA, for a task that
        # named a different office. One row of a list of field offices reads like any
        # other to a planner, so the run has to check the pick against the place the task
        # named.
        browser = _Browser(
            [
                _candidate(
                    "bishop",
                    name="BISHOP 1115 West Line Street, BISHOP",
                    role="link",
                    tag_name="a",
                ),
                _candidate(
                    "chula",
                    name="CHULA VISTA 30 N. Glover Avenue, CHULA VISTA",
                    role="link",
                    tag_name="a",
                ),
                _candidate(
                    "chico",
                    name="CHICO 2382 Notre Dame Boulevard, CHICO",
                    role="link",
                    tag_name="a",
                ),
            ]
        )
        planner = _Planner(
            [
                AgentPlan(
                    action=AgentActionKind.CLICK,
                    candidate_id="bishop",
                    narration="Choosing BISHOP 1115 West Line Street, BISHOP.",
                ),
                AgentPlan(action=AgentActionKind.DONE, narration="Done.", task_complete=True),
            ]
        )
        service = self._service(browser, planner)

        view = self._run(service, uuid4(), prompt=DEMO_TASKS_BY_ID["dmv-get-in-line"].prompt)

        self.assertEqual([action["candidate_id"] for action in browser.actions], ["chico"])
        self.assertIn("CHICO", view.steps[0].narration)
        self.assertNotIn("BISHOP", view.steps[0].narration)

    def test_the_control_that_moves_the_page_forward_is_not_second_guessed(self) -> None:
        # The place check exists to stop the run taking a different row of the same list.
        # It must never hijack the generic control that advances the page, which names no
        # place by design.
        browser = _Browser(
            [
                _candidate("next", name="Next", role="link", tag_name="a"),
                _candidate(
                    "chico",
                    name="CHICO 2382 Notre Dame Boulevard, CHICO",
                    role="link",
                    tag_name="a",
                ),
            ]
        )
        planner = _Planner(
            [
                AgentPlan(
                    action=AgentActionKind.CLICK,
                    candidate_id="next",
                    narration="Opening the next page of offices.",
                ),
                AgentPlan(action=AgentActionKind.DONE, narration="Done.", task_complete=True),
            ]
        )
        service = self._service(browser, planner)

        self._run(service, uuid4(), prompt=DEMO_TASKS_BY_ID["dmv-get-in-line"].prompt)

        self.assertEqual([action["candidate_id"] for action in browser.actions], ["next"])

    def test_a_redirected_choice_is_only_tried_once(self) -> None:
        # The check trades one step for not queueing at the wrong office: when a task names
        # several things -- a shop and a service -- it can prefer the longer name over the
        # planner's pick. That has to cost a single step, not the run, so the row it
        # redirected to counts as tried and the planner's own choice then goes through.
        browser = _Browser(
            [
                _candidate("service", name="Haircut", role="link", tag_name="a"),
                _candidate("shop", name="Society Barbershop San Jose", role="link", tag_name="a"),
            ]
        )
        cut = AgentPlan(
            action=AgentActionKind.CLICK, candidate_id="service", narration="Choosing a cut."
        )
        planner = _Planner(
            [
                cut,
                cut,
                AgentPlan(action=AgentActionKind.DONE, narration="Done.", task_complete=True),
            ]
        )
        service = self._service(browser, planner)

        self._run(service, uuid4(), prompt=DEMO_TASKS_BY_ID["haircut-appointment"].prompt)

        self.assertEqual(
            [action["candidate_id"] for action in browser.actions], ["shop", "service"]
        )

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
                start_url="https://booksy.com/",
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
                start_url="https://booksy.com/",
            )
            await asyncio.sleep(0)
            return await service.stop(session_id)

        view = asyncio.run(scenario())

        self.assertEqual(view.state, AgentRunState.STOPPED)
        self.assertIn("Nothing further was changed", view.summary or "")


class LocalActionPlannerTests(unittest.TestCase):
    def test_a_clear_continue_link_is_selected_without_a_model(self) -> None:
        planner = LocalActionPlanner()
        candidate = _candidate("continue", name="Continue to finish", role="link", tag_name="a")

        plan = asyncio.run(
            planner.plan(
                prompt="Complete the local navigation check",
                candidates=[candidate],
                history=[],
                page_title="Local navigation",
                origin="http://127.0.0.1:8765",
            )
        )

        assert plan is not None
        self.assertEqual(plan.action, AgentActionKind.CLICK)
        self.assertEqual(plan.candidate_id, "continue")

    def test_a_completion_title_finishes_without_another_action(self) -> None:
        plan = asyncio.run(
            LocalActionPlanner().plan(
                prompt="Complete the local navigation check",
                candidates=[],
                history=["1. Choosing Continue to finish."],
                page_title="Task complete",
                origin="http://127.0.0.1:8765",
            )
        )

        assert plan is not None
        self.assertTrue(plan.task_complete)
        self.assertEqual(plan.action, AgentActionKind.DONE)

    def test_a_generic_submit_button_advances_the_run(self) -> None:
        # "Submit" is how a service selection, a search, and a date choice all advance.
        # Refusing the word itself is what stranded the DMV demo on an empty form.
        plan = asyncio.run(
            LocalActionPlanner().plan(
                prompt="Send the form",
                candidates=[_candidate("submit", name="Submit form")],
                history=[],
                page_title="Details",
                origin="http://127.0.0.1:8765",
            )
        )

        assert plan is not None
        self.assertEqual(plan.action, AgentActionKind.CLICK)
        self.assertEqual(plan.candidate_id, "submit")
        self.assertEqual(plan.safety_classification, SafetyClassification.SAFE)

    def test_a_button_that_spends_money_is_still_classified_as_money(self) -> None:
        plan = asyncio.run(
            LocalActionPlanner().plan(
                prompt="Finish the order",
                candidates=[_candidate("pay", name="Submit payment")],
                history=[],
                page_title="Checkout",
                origin="http://127.0.0.1:8765",
            )
        )

        assert plan is not None
        self.assertEqual(plan.safety_classification, SafetyClassification.MONEY)


class DemoPersonaRunTests(unittest.TestCase):
    """A curated demo runs on made-up details, so it never stops to ask for real ones."""

    def _service(self, browser: Any, planner: Any) -> AutopilotService:
        return AutopilotService(
            browser=browser,
            planner=planner,
            event_hub=SessionEventHub(),
            repository=_Repository(),
        )

    def test_a_demo_types_the_persona_into_a_labelled_field(self) -> None:
        browser = _Browser([_field("first", "First Name")])
        planner = _Planner([AgentPlan(action=AgentActionKind.DONE, narration="Done.")])
        service = self._service(browser, planner)
        session_id = uuid4()

        async def scenario() -> None:
            await service.start(
                session_id=session_id,
                user_id="user-1",
                task_name="Get in line at the DMV",
                prompt=DEMO_TASKS_BY_ID["dmv-get-in-line"].prompt,
                start_url=DEMO_TASKS_BY_ID["dmv-get-in-line"].start_url,
                demo=DEMO_TASKS_BY_ID["dmv-get-in-line"],
            )
            run = service.get(session_id)
            assert run is not None and run.task is not None
            await run.task

        asyncio.run(scenario())

        fills = [action for action in browser.actions if action["action"] is AgentActionKind.FILL]
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0]["value"], "Margaret")

    def test_a_field_is_only_filled_once_even_if_it_stays_on_the_page(self) -> None:
        browser = _Browser([_field("email", "Email Address")])
        planner = _Planner([AgentPlan(action=AgentActionKind.DONE, narration="Done.")])
        service = self._service(browser, planner)
        session_id = uuid4()

        async def scenario() -> None:
            await service.start(
                session_id=session_id,
                user_id="user-1",
                task_name="Book a haircut",
                prompt="book it",
                start_url="https://booksy.com/",
                demo=DEMO_TASKS_BY_ID["haircut-appointment"],
            )
            run = service.get(session_id)
            assert run is not None and run.task is not None
            await run.task

        asyncio.run(scenario())

        fills = [action for action in browser.actions if action["action"] is AgentActionKind.FILL]
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0]["value"], "margaret.whitfield@example.com")

    def test_a_free_form_run_invents_nothing(self) -> None:
        browser = _Browser([_field("first", "First Name")])
        planner = _Planner([AgentPlan(action=AgentActionKind.DONE, narration="Done.")])
        service = self._service(browser, planner)
        session_id = uuid4()

        async def scenario() -> None:
            await service.start(
                session_id=session_id,
                user_id="user-1",
                task_name="Renew my library book",
                prompt="Renew my library book",
                start_url="https://booksy.com/",
            )
            run = service.get(session_id)
            assert run is not None and run.task is not None
            await run.task

        asyncio.run(scenario())

        fills = [action for action in browser.actions if action["action"] is AgentActionKind.FILL]
        self.assertEqual(fills, [])

    def test_one_control_cannot_swallow_the_whole_run(self) -> None:
        # A live DMV run spent all 24 steps re-clicking the site's own search box,
        # because nothing stopped the planner re-picking a control that changed nothing.
        browser = _Browser([_candidate("search", name="Submit search form")])
        service = self._service(browser, LocalActionPlanner())
        session_id = uuid4()

        async def scenario() -> None:
            await service.start(
                session_id=session_id,
                user_id="user-1",
                task_name="Get in line at the DMV",
                prompt=DEMO_TASKS_BY_ID["dmv-get-in-line"].prompt,
                start_url=DEMO_TASKS_BY_ID["dmv-get-in-line"].start_url,
                demo=DEMO_TASKS_BY_ID["dmv-get-in-line"],
            )
            run = service.get(session_id)
            assert run is not None and run.task is not None
            await run.task

        asyncio.run(scenario())

        self.assertLessEqual(len(browser.actions), 1)

    def test_a_demo_fills_the_form_and_then_submits_it(self) -> None:
        # The whole point: one tap, no question asked of the participant. This runs the
        # real planner, because a stub planner is what hid the bug the first time.
        browser = _CompletingBrowser(
            [_field("first", "First Name"), _candidate("go", name="Submit")]
        )
        service = self._service(browser, LocalActionPlanner())
        session_id = uuid4()

        async def scenario() -> None:
            await service.start(
                session_id=session_id,
                user_id="user-1",
                task_name="Get in line at the DMV",
                prompt=DEMO_TASKS_BY_ID["dmv-get-in-line"].prompt,
                start_url=DEMO_TASKS_BY_ID["dmv-get-in-line"].start_url,
                demo=DEMO_TASKS_BY_ID["dmv-get-in-line"],
            )
            run = service.get(session_id)
            assert run is not None and run.task is not None
            await run.task

        asyncio.run(scenario())

        performed = [action["action"] for action in browser.actions]
        self.assertEqual(performed, [AgentActionKind.FILL, AgentActionKind.CLICK])
        self.assertEqual(browser.actions[0]["value"], "Margaret")
        self.assertEqual(service.view(session_id).state, AgentRunState.COMPLETED)


class ProviderBlockTests(unittest.TestCase):
    """The provider's own refusal page must never be mistaken for the target site."""

    def test_the_refusal_interstitial_is_recognized(self) -> None:
        self.assertTrue(
            is_provider_block(
                "https://www.browserbase.com/navigation-blocked", "Navigation blocked"
            )
        )
        self.assertTrue(is_provider_block("https://browserbase.com/navigation-blocked"))

    def test_the_title_alone_is_enough_to_recognize_it(self) -> None:
        self.assertTrue(
            is_provider_block("https://example.test/x", "Navigation Blocked | Browserbase")
        )

    def test_an_ordinary_page_is_not_treated_as_blocked(self) -> None:
        self.assertFalse(is_provider_block("https://booksy.com/en-us/s/haircut", "Book a haircut"))
        self.assertFalse(
            is_provider_block("https://www.dmv.ca.gov/portal/appointments/", "Appointments")
        )

    def test_the_providers_own_marketing_pages_are_not_flagged(self) -> None:
        # Only the refusal path counts; browserbase.com/pricing is simply a page.
        self.assertFalse(is_provider_block("https://www.browserbase.com/pricing", "Pricing"))

    def test_a_blocked_page_stops_the_run_instead_of_being_worked_on(self) -> None:
        @dataclass(frozen=True)
        class _Blocked:
            origin: str = "https://www.browserbase.com"
            redacted_path: str = "/navigation-blocked"
            title: str | None = "Navigation blocked | Browserbase"
            blocked: bool = True

        class _BlockedBrowser(_Browser):
            async def page_state(self, _session_id: Any) -> _Blocked:
                return _Blocked()

        browser = _BlockedBrowser([_candidate("bb-pricing", name="Pricing")])
        planner = _Planner(
            [
                AgentPlan(
                    action=AgentActionKind.CLICK,
                    candidate_id="bb-pricing",
                    narration="Opening pricing",
                )
            ]
        )
        service = AutopilotService(
            browser=browser,
            planner=planner,
            event_hub=SessionEventHub(),
            repository=_Repository(),
        )
        session_id = uuid4()

        async def scenario() -> Any:
            await service.start(
                session_id=session_id,
                user_id="margaret",
                task_name="Book a haircut",
                prompt="book a haircut",
                start_url="https://booksy.com/en-us/s/haircut",
            )
            run = service.get(session_id)
            assert run is not None and run.task is not None
            await run.task
            return service.view(session_id)

        view = asyncio.run(scenario())

        self.assertEqual(view.state, AgentRunState.FAILED)
        self.assertEqual(browser.actions, [], "no action may be taken on the refusal page")
        self.assertEqual(planner.calls, 0, "the planner must never see the refusal page")
        self.assertIn("cannot be opened", view.summary or "")


class DemoCatalogueTests(unittest.TestCase):
    def test_the_three_offered_demos_are_the_promised_errands(self) -> None:
        self.assertEqual(
            [task.id for task in DEMO_TASKS],
            ["dmv-get-in-line", "target-groceries", "haircut-appointment"],
        )
        self.assertEqual(
            {task.category for task in DEMO_TASKS},
            {"government", "shopping", "appointment"},
        )

    def test_every_demo_starts_on_a_real_https_site(self) -> None:
        for task in DEMO_TASKS:
            with self.subTest(task=task.id):
                self.assertTrue(task.start_url.startswith("https://"))
                self.assertNotIn("w3.org", task.start_url)

    def test_no_demo_points_at_a_domain_the_provider_refuses(self) -> None:
        # greatclips.com is refused by the provider's navigation policy; offering it
        # would send the run straight to the refusal interstitial.
        refused = ("greatclips.com", "browserbase.com")
        for task in DEMO_TASKS:
            with self.subTest(task=task.id):
                for host in refused:
                    self.assertNotIn(host, task.start_url)

    def test_every_demo_carries_a_prompt_the_agent_can_act_on(self) -> None:
        for task in DEMO_TASKS:
            with self.subTest(task=task.id):
                self.assertGreater(len(task.prompt), 20)
                self.assertEqual(DEMO_TASKS_BY_ID[task.id], task)

    def test_dmv_demo_starts_at_the_official_queue_instead_of_the_captcha_shell(self) -> None:
        task = DEMO_TASKS_BY_ID["dmv-get-in-line"]

        self.assertEqual(
            task.start_url,
            "https://mt-cadmvoas.us.qmatic.cloud/branches",
        )
        self.assertNotIn("mydmv", task.start_url.casefold())

    def test_an_origin_is_normalized_consistently(self) -> None:
        self.assertEqual(origin_of("https://Example.COM/path?x=1"), "https://example.com")


if __name__ == "__main__":
    unittest.main()

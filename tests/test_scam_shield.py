from __future__ import annotations

import asyncio
import unittest
from typing import Any

from backend.app.services.scam_shield import ScamShieldService


class _Cortex:
    def __init__(self, value: Any) -> None:
        self.value = value
        self.calls: list[tuple[str, list[str]]] = []

    async def ai_classify(
        self,
        text: str,
        categories: list[str],
        *,
        task_description: str | None = None,
    ) -> Any:
        self.calls.append((text, categories))
        if isinstance(self.value, Exception):
            raise self.value

        class _Result:
            value = self.value

        return _Result()


class ScamShieldServiceTests(unittest.TestCase):
    def test_an_identity_request_produces_a_calm_specific_message(self) -> None:
        cortex = _Cortex({"labels": ["identity_document_request"]})
        shield = ScamShieldService(cortex)

        verdict = asyncio.run(
            shield.triage("Enter your Social Security number to release your refund")
        )

        assert verdict is not None
        self.assertEqual(verdict.category, "identity_document_request")
        self.assertIn("government identity number", verdict.message)
        self.assertTrue(verdict.notify_caregiver)

    def test_an_ordinary_page_produces_no_verdict(self) -> None:
        shield = ScamShieldService(_Cortex({"labels": ["ordinary_page"]}))

        verdict = asyncio.run(shield.triage("Choose lettuce and tomato for your sandwich"))

        self.assertIsNone(verdict)

    def test_a_plain_string_label_is_accepted(self) -> None:
        shield = ScamShieldService(_Cortex("gift_card_request"))

        verdict = asyncio.run(shield.triage("Buy three gift cards and enter the codes here"))

        assert verdict is not None
        self.assertEqual(verdict.category, "gift_card_request")

    def test_a_json_encoded_label_is_accepted(self) -> None:
        shield = ScamShieldService(_Cortex('{"labels":["fake_security_alert"]}'))

        verdict = asyncio.run(shield.triage("Warning: your computer is infected, call now"))

        assert verdict is not None
        self.assertEqual(verdict.category, "fake_security_alert")

    def test_an_unrecognized_label_is_ignored(self) -> None:
        shield = ScamShieldService(_Cortex({"labels": ["something_else"]}))

        verdict = asyncio.run(shield.triage("Enter your Social Security number now please"))

        self.assertIsNone(verdict)

    def test_a_classifier_outage_never_blocks_the_pause(self) -> None:
        shield = ScamShieldService(_Cortex(RuntimeError("Cortex unavailable")))

        verdict = asyncio.run(shield.triage("Enter your bank routing number to continue"))

        self.assertIsNone(verdict)

    def test_page_text_is_bounded_before_classification(self) -> None:
        cortex = _Cortex({"labels": ["ordinary_page"]})
        shield = ScamShieldService(cortex, max_chars=50)

        asyncio.run(shield.triage("word " * 500))

        self.assertLessEqual(len(cortex.calls[0][0]), 50)

    def test_very_short_text_is_not_sent_to_the_classifier(self) -> None:
        cortex = _Cortex({"labels": ["ordinary_page"]})
        shield = ScamShieldService(cortex)

        verdict = asyncio.run(shield.triage("Next"))

        self.assertIsNone(verdict)
        self.assertEqual(cortex.calls, [])

    def test_an_unconfigured_provider_is_tolerated(self) -> None:
        shield = ScamShieldService(object())

        verdict = asyncio.run(shield.triage("Enter your Social Security number to continue"))

        self.assertIsNone(verdict)


if __name__ == "__main__":
    unittest.main()

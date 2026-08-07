from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from backend.app.contracts.models import (
    ElementCandidate,
    GuidanceDecision,
    SafetyClassification,
    SafetyPresentation,
    SensitivityFlag,
)


@dataclass(frozen=True)
class SafetyResult:
    allowed: bool
    should_escalate: bool
    presentation: SafetyPresentation | None = None


class SafetyPolicy:
    def evaluate(
        self,
        *,
        decision: GuidanceDecision,
        target: ElementCandidate,
        current_origin: str,
        allowed_origins: list[str],
    ) -> SafetyResult:
        sensitive = set(target.sensitivity_flags)
        classification = decision.safety_classification
        unknown_origin = self._origin(current_origin) not in {
            self._origin(item) for item in allowed_origins
        }

        if SensitivityFlag.PASSWORD in sensitive:
            return SafetyResult(
                allowed=False,
                should_escalate=False,
                presentation=SafetyPresentation(
                    classification=SafetyClassification.IDENTITY,
                    message=(
                        "Please use the site's saved sign-in controls; "
                        "WebAccessible cannot read or enter a password."
                    ),
                ),
            )

        risky = classification in {
            SafetyClassification.MONEY,
            SafetyClassification.IDENTITY,
            SafetyClassification.DELETION,
            SafetyClassification.SUSPICIOUS,
            SafetyClassification.UNKNOWN,
        }
        if risky or sensitive.intersection(
            {SensitivityFlag.PAYMENT, SensitivityFlag.IDENTITY, SensitivityFlag.BANK}
        ):
            action = self._action_label(classification)
            amount_text = ""
            if decision.amount and decision.amount.source != "unknown":
                amount_text = f" for {decision.amount.currency} {decision.amount.value}"
            message = (
                f"Let's pause before {action}{amount_text}; "
                "the real page is waiting for your choice."
            )
            if unknown_origin or classification in {
                SafetyClassification.SUSPICIOUS,
                SafetyClassification.UNKNOWN,
            }:
                message = (
                    "Let's pause a moment; this unfamiliar page is asking for "
                    "sensitive information."
                )
            return SafetyResult(
                allowed=False,
                should_escalate=unknown_origin
                or classification
                in {SafetyClassification.SUSPICIOUS, SafetyClassification.UNKNOWN},
                presentation=SafetyPresentation(
                    classification=classification,
                    message=message,
                    irreversible_action=action,
                    amount=decision.amount,
                ),
            )

        return SafetyResult(allowed=True, should_escalate=False)

    @staticmethod
    def _origin(url: str) -> str:
        parsed = urlsplit(url)
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"

    @staticmethod
    def _action_label(classification: SafetyClassification) -> str:
        return {
            SafetyClassification.MONEY: "moving money",
            SafetyClassification.IDENTITY: "sending personal information",
            SafetyClassification.DELETION: "deleting anything",
        }.get(classification, "continuing")

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum
from typing import Any

from backend.app.integrations.snowflake import SnowflakeAdapter


class CostCalculationError(RuntimeError):
    """Base error for an unavailable, ambiguous, or invalid actual cost."""


class ActualUsageRequiredError(CostCalculationError):
    """Raised when a caller supplies estimates or incomplete actual usage."""


class UnknownRateCardError(CostCalculationError):
    """Raised when no unique effective rate exists for every used token class."""


class TokenClass(StrEnum):
    INPUT = "input"
    CACHED_INPUT = "cached_input"
    REASONING = "reasoning"
    OUTPUT = "output"


@dataclass(frozen=True, slots=True)
class ActualTokenUsage:
    input_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        for field_name, value in self.as_counts().items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ActualUsageRequiredError(
                    f"{field_name.value} token usage must be an actual non-negative integer"
                )
        if not any(self.as_counts().values()):
            raise ActualUsageRequiredError("actual token usage cannot be entirely zero")

    def as_counts(self) -> dict[TokenClass, int]:
        return {
            TokenClass.INPUT: self.input_tokens,
            TokenClass.CACHED_INPUT: self.cached_input_tokens,
            TokenClass.REASONING: self.reasoning_tokens,
            TokenClass.OUTPUT: self.output_tokens,
        }


@dataclass(frozen=True, slots=True)
class EffectiveRate:
    rate_card_id: str
    rate_card_version: str
    token_class: TokenClass
    unit_quantity: Decimal
    unit_price: Decimal
    currency: str
    usd_conversion_rate: Decimal
    source_reference: str
    rounding_rule: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> EffectiveRate:
        try:
            token_class = TokenClass(str(row["token_class"]))
        except (KeyError, ValueError) as exc:
            raise UnknownRateCardError("rate card has an unsupported token class") from exc

        rate_card_id = _required_text(row, "rate_card_id")
        rate_card_version = _required_text(row, "rate_card_version")
        currency = _required_text(row, "currency").upper()
        source_reference = _required_text(row, "source_reference")
        rounding_rule = _required_text(row, "rounding_rule")
        unit_quantity = _decimal(row.get("unit_quantity"), "unit_quantity")
        unit_price = _decimal(row.get("unit_price"), "unit_price")
        if unit_quantity <= 0:
            raise UnknownRateCardError("rate-card unit_quantity must be positive")
        if unit_price < 0:
            raise UnknownRateCardError("rate-card unit_price cannot be negative")

        raw_conversion = row.get("usd_conversion_rate")
        if raw_conversion is None and currency == "USD":
            usd_conversion_rate = Decimal(1)
        elif raw_conversion is None:
            raise UnknownRateCardError("non-USD rate card requires an explicit USD conversion rate")
        else:
            usd_conversion_rate = _decimal(raw_conversion, "usd_conversion_rate")
        if usd_conversion_rate <= 0:
            raise UnknownRateCardError("USD conversion rate must be positive")

        return cls(
            rate_card_id=rate_card_id,
            rate_card_version=rate_card_version,
            token_class=token_class,
            unit_quantity=unit_quantity,
            unit_price=unit_price,
            currency=currency,
            usd_conversion_rate=usd_conversion_rate,
            source_reference=source_reference,
            rounding_rule=rounding_rule,
        )


@dataclass(frozen=True, slots=True)
class CalculatedModelCost:
    cost_id: str
    call_id: str
    session_id: str
    run_id: str
    user_id: str
    rate_card_version: str
    usage: ActualTokenUsage
    input_amount: Decimal
    cached_input_amount: Decimal
    reasoning_amount: Decimal
    output_amount: Decimal
    amount_currency: Decimal
    currency: str
    amount_usd: Decimal
    credits: Decimal | None
    source_environment: str
    calculated_at: datetime

    def to_outbox_payload(self) -> dict[str, Any]:
        return {
            "cost_id": self.cost_id,
            "call_id": self.call_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "user_id": self.user_id,
            "rate_card_version": self.rate_card_version,
            "actual_input_tokens": self.usage.input_tokens,
            "actual_cached_input_tokens": self.usage.cached_input_tokens,
            "actual_reasoning_tokens": self.usage.reasoning_tokens,
            "actual_output_tokens": self.usage.output_tokens,
            "input_amount": self.input_amount,
            "cached_input_amount": self.cached_input_amount,
            "reasoning_amount": self.reasoning_amount,
            "output_amount": self.output_amount,
            "credits": self.credits,
            "amount_currency": self.amount_currency,
            "currency": self.currency,
            "amount_usd": self.amount_usd,
            "calculation_status": "calculated",
            "source_environment": self.source_environment,
            "calculated_at": self.calculated_at,
        }


class CostCalculator:
    """Calculate actual inference cost from effective Snowflake rate-card rows."""

    def __init__(self, snowflake: SnowflakeAdapter) -> None:
        self.snowflake = snowflake

    async def calculate(
        self,
        *,
        call_id: str,
        session_id: str,
        run_id: str,
        user_id: str,
        provider: str,
        model: str,
        model_version: str | None,
        rate_card_version: str,
        usage: ActualTokenUsage,
        usage_status: str,
        effective_at: datetime,
        source_environment: str,
        cost_id: str | None = None,
    ) -> CalculatedModelCost:
        if usage_status != "actual":
            raise ActualUsageRequiredError(
                "cost cannot be calculated as actual without provider-returned actual usage"
            )
        identifiers = {
            "call_id": call_id,
            "session_id": session_id,
            "run_id": run_id,
            "user_id": user_id,
            "provider": provider,
            "model": model,
            "rate_card_version": rate_card_version,
            "source_environment": source_environment,
        }
        for name, value in identifiers.items():
            if not value or not value.strip():
                raise ValueError(f"{name} must not be blank")
        if effective_at.tzinfo is None or effective_at.utcoffset() is None:
            raise ValueError("effective_at must include a timezone")

        normalized_model_version = model_version.strip() if model_version else None
        effective_utc = effective_at.astimezone(UTC).replace(tzinfo=None)
        result = await self.snowflake.query(
            """
            SELECT
                rate_card_id,
                rate_card_version,
                token_class,
                unit_quantity,
                unit_price,
                currency,
                usd_conversion_rate,
                source_reference,
                rounding_rule
            FROM COST_RATE_CARDS
            WHERE rate_card_version = %s
              AND provider = %s
              AND model = %s
              AND (
                    model_version = %s
                    OR (model_version IS NULL AND %s IS NULL)
                  )
              AND effective_from <= %s
              AND (effective_to IS NULL OR effective_to > %s)
            ORDER BY token_class, effective_from DESC, rate_card_id
            """,
            (
                rate_card_version,
                provider,
                model,
                normalized_model_version,
                normalized_model_version,
                effective_utc,
                effective_utc,
            ),
        )
        rates = [EffectiveRate.from_row(row) for row in result.rows]
        return self.calculate_from_rates(
            call_id=call_id,
            session_id=session_id,
            run_id=run_id,
            user_id=user_id,
            rate_card_version=rate_card_version,
            usage=usage,
            usage_status=usage_status,
            rates=rates,
            source_environment=source_environment,
            cost_id=cost_id,
        )

    def calculate_from_rates(
        self,
        *,
        call_id: str,
        session_id: str,
        run_id: str,
        user_id: str,
        rate_card_version: str,
        usage: ActualTokenUsage,
        usage_status: str,
        rates: Sequence[EffectiveRate],
        source_environment: str,
        cost_id: str | None = None,
    ) -> CalculatedModelCost:
        if usage_status != "actual":
            raise ActualUsageRequiredError("estimated usage cannot be persisted as actual cost")
        identifiers = {
            "call_id": call_id,
            "session_id": session_id,
            "run_id": run_id,
            "user_id": user_id,
            "rate_card_version": rate_card_version,
            "source_environment": source_environment,
        }
        for name, value in identifiers.items():
            if not value or not value.strip():
                raise ValueError(f"{name} must not be blank")

        rates_by_class: dict[TokenClass, list[EffectiveRate]] = {}
        for rate in rates:
            if rate.rate_card_version != rate_card_version:
                continue
            rates_by_class.setdefault(rate.token_class, []).append(rate)

        counts = usage.as_counts()
        selected_rates: dict[TokenClass, EffectiveRate] = {}
        for token_class, count in counts.items():
            if count == 0:
                continue
            matches = rates_by_class.get(token_class, [])
            if not matches:
                raise UnknownRateCardError(
                    f"no effective {token_class.value} rate exists for {rate_card_version}"
                )
            if len(matches) != 1:
                raise UnknownRateCardError(
                    f"multiple effective {token_class.value} rates overlap for {rate_card_version}"
                )
            selected_rates[token_class] = matches[0]

        currencies = {rate.currency for rate in selected_rates.values()}
        conversions = {rate.usd_conversion_rate for rate in selected_rates.values()}
        rounding_rules = {rate.rounding_rule for rate in selected_rates.values()}
        if len(currencies) != 1 or len(conversions) != 1 or len(rounding_rules) != 1:
            raise UnknownRateCardError(
                "effective token-class rates must share currency, conversion, and rounding rules"
            )

        amounts = {token_class: Decimal(0) for token_class in TokenClass}
        with localcontext() as context:
            context.prec = 38
            for token_class, rate in selected_rates.items():
                amounts[token_class] = (
                    Decimal(counts[token_class]) / rate.unit_quantity
                ) * rate.unit_price
            amount_currency = sum(amounts.values(), start=Decimal(0))
            conversion = next(iter(conversions))
            amount_usd = amount_currency * conversion

        currency = next(iter(currencies))
        stable_cost_id = cost_id or f"model-cost:{call_id}:{rate_card_version}"
        if not stable_cost_id.strip():
            raise ValueError("cost_id must not be blank")
        return CalculatedModelCost(
            cost_id=stable_cost_id,
            call_id=call_id,
            session_id=session_id,
            run_id=run_id,
            user_id=user_id,
            rate_card_version=rate_card_version,
            usage=usage,
            input_amount=amounts[TokenClass.INPUT],
            cached_input_amount=amounts[TokenClass.CACHED_INPUT],
            reasoning_amount=amounts[TokenClass.REASONING],
            output_amount=amounts[TokenClass.OUTPUT],
            amount_currency=amount_currency,
            currency=currency,
            amount_usd=amount_usd,
            credits=amount_currency if currency in {"CREDIT", "CREDITS"} else None,
            source_environment=source_environment,
            calculated_at=datetime.now(UTC),
        )


def _required_text(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if value is None or not str(value).strip():
        raise UnknownRateCardError(f"rate card requires {field}")
    return str(value).strip()


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise UnknownRateCardError(f"rate card has invalid {field}") from exc
    if not result.is_finite():
        raise UnknownRateCardError(f"rate card has non-finite {field}")
    return result

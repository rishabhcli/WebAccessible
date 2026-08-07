"""The made-up participant the curated demos run as.

A demo has to fill real forms. The California DMV wants a name, a date of birth, and a
phone number before it will show a single open slot. None of that may be a real person's
data, and none of it may be asked of the participant watching -- a demo that stops to
collect a date of birth is not a demo.

So the demos carry this persona instead. Every value here is fictional by construction
rather than by hope:

* the address is an RFC 2606 `example.com` mailbox, which can never receive mail;
* the phone sits in the NANP 555-0100..555-0199 block reserved for fiction;
* the licence number matches California's one-letter-seven-digit shape without being a
  licence.

A free-form prompt never touches this. When a participant asks for their own appointment
the run fills only what they typed, and pauses for anything it does not have.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class DemoPersona:
    """A complete, fictional identity good enough to satisfy a real form."""

    first_name: str
    last_name: str
    email: str
    # Digits only. Masked telephone inputs are common and usually reject punctuation,
    # while a plain text input accepts digits fine.
    phone: str
    birth_date_us: str
    birth_date_iso: str
    address_line1: str
    city: str
    state_code: str
    state_name: str
    postal_code: str
    license_number: str

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


DEMO_PERSONA: Final = DemoPersona(
    first_name="Margaret",
    last_name="Whitfield",
    email="margaret.whitfield@example.com",
    phone="4155550142",
    birth_date_us="03/12/1948",
    birth_date_iso="1948-03-12",
    address_line1="1200 Example Avenue",
    city="San Francisco",
    state_code="CA",
    state_name="California",
    postal_code="94102",
    license_number="D1234567",
)


def persona_brief(persona: DemoPersona = DEMO_PERSONA) -> str:
    """The persona as one block a planner can read and act on.

    Without this a planner stops to ask the participant where they live, which is exactly
    the question a demo exists to never ask.
    """

    return (
        "Use these details for anything the page asks for. They are already yours; never "
        "stop to ask for them.\n"
        f"- Name: {persona.full_name}\n"
        f"- Email: {persona.email}\n"
        f"- Phone: {persona.phone}\n"
        f"- Date of birth: {persona.birth_date_us}\n"
        f"- Address: {persona.address_line1}, {persona.city}, {persona.state_code} "
        f"{persona.postal_code}\n"
        f"- Driver licence number: {persona.license_number}"
    )


def _birth_date(persona: DemoPersona, input_type: str | None) -> str:
    return persona.birth_date_iso if input_type == "date" else persona.birth_date_us


# Ordered longest-match-first, because the obvious substrings overlap: "last name"
# contains "name", and "email address" contains "address". The first rule that matches
# a label wins, so the specific ones have to come first.
_RULES: Final[tuple[tuple[tuple[str, ...], Callable[[DemoPersona, str | None], str]], ...]] = (
    (
        ("email", "e-mail"),
        lambda persona, _type: persona.email,
    ),
    (
        ("first name", "given name", "forename"),
        lambda persona, _type: persona.first_name,
    ),
    (
        ("last name", "surname", "family name"),
        lambda persona, _type: persona.last_name,
    ),
    (
        ("date of birth", "birth date", "birthdate", "birthday", "dob"),
        _birth_date,
    ),
    (
        ("phone", "telephone", "mobile", "cell number", "cell phone"),
        lambda persona, _type: persona.phone,
    ),
    (
        ("zip", "postal code", "postcode"),
        lambda persona, _type: persona.postal_code,
    ),
    (
        ("driver license", "driver's license", "licence number", "license number", "dl number"),
        lambda persona, _type: persona.license_number,
    ),
    (
        ("street address", "address line 1", "street", "mailing address", "home address"),
        lambda persona, _type: persona.address_line1,
    ),
    (
        ("city", "town"),
        lambda persona, _type: persona.city,
    ),
    (
        ("state", "province"),
        lambda persona, _type: persona.state_code,
    ),
    (
        ("full name", "your name", "name"),
        lambda persona, _type: persona.full_name,
    ),
)

# Fields a demo deliberately leaves blank. They are optional on every form the curated
# tasks touch, and inventing a suite number reads as noise in the narration.
_SKIPPED: Final = (
    "address line 2",
    "apartment",
    "apt",
    "suite",
    "unit number",
    "middle name",
    "middle initial",
    "company",
    "organization",
)

# When a form gives an input no usable label at all, its type is the only signal left.
_BY_INPUT_TYPE: Final[dict[str, Callable[[DemoPersona, str | None], str]]] = {
    "email": lambda persona, _type: persona.email,
    "tel": lambda persona, _type: persona.phone,
    "date": _birth_date,
}


def persona_value(
    label: str,
    input_type: str | None,
    persona: DemoPersona = DEMO_PERSONA,
) -> str | None:
    """Return the made-up value for a labelled field, or None to leave it alone."""

    normalized = " ".join(label.casefold().split())
    if any(marker in normalized for marker in _SKIPPED):
        return None
    for markers, resolve in _RULES:
        if any(marker in normalized for marker in markers):
            return resolve(persona, input_type)
    by_type = _BY_INPUT_TYPE.get((input_type or "").casefold())
    return by_type(persona, input_type) if by_type else None

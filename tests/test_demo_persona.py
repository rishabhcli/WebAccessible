from __future__ import annotations

import unittest

from backend.app.domain.persona import DEMO_PERSONA, persona_value


class PersonaValueTests(unittest.TestCase):
    def test_the_common_appointment_fields_all_resolve(self) -> None:
        cases = {
            "First Name": "Margaret",
            "Last Name": "Whitfield",
            "Email": "margaret.whitfield@example.com",
            "Phone Number": "4155550142",
            "Date of Birth": "03/12/1948",
            "ZIP Code": "94102",
            "City": "San Francisco",
            "Driver License Number": "D1234567",
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(persona_value(label, "text"), expected)

    def test_a_date_input_gets_the_iso_form(self) -> None:
        self.assertEqual(persona_value("Date of Birth", "date"), "1948-03-12")
        self.assertEqual(persona_value("Date of Birth", "text"), "03/12/1948")

    def test_email_address_is_an_email_and_not_a_street(self) -> None:
        # "Email Address" contains "address", so rule order is what makes this correct.
        self.assertEqual(persona_value("Email Address", "text"), DEMO_PERSONA.email)
        self.assertEqual(
            persona_value("Street Address", "text"), DEMO_PERSONA.address_line1
        )

    def test_last_name_is_a_surname_and_not_the_full_name(self) -> None:
        # "Last Name" contains "name", which the bare full-name rule would also match.
        self.assertEqual(persona_value("Last Name", "text"), DEMO_PERSONA.last_name)
        self.assertEqual(persona_value("Name", "text"), DEMO_PERSONA.full_name)

    def test_optional_fields_are_left_blank(self) -> None:
        for label in ("Address Line 2", "Apt / Suite", "Middle Initial", "Company"):
            with self.subTest(label=label):
                self.assertIsNone(persona_value(label, "text"))

    def test_an_unlabelled_input_falls_back_to_its_type(self) -> None:
        self.assertEqual(persona_value("", "email"), DEMO_PERSONA.email)
        self.assertEqual(persona_value("", "tel"), DEMO_PERSONA.phone)
        self.assertIsNone(persona_value("", "text"))

    def test_an_unrecognized_field_is_not_guessed_at(self) -> None:
        self.assertIsNone(persona_value("Vehicle Identification Number", "text"))


class PersonaIsFictionalTests(unittest.TestCase):
    """The demo persona has to be fake by construction, not by hope."""

    def test_the_mailbox_can_never_receive_mail(self) -> None:
        # RFC 2606 reserves example.com precisely so it cannot be anybody's address.
        self.assertTrue(DEMO_PERSONA.email.endswith("@example.com"))

    def test_the_phone_sits_in_the_block_reserved_for_fiction(self) -> None:
        # NANP holds 555-0100..555-0199 back from assignment for exactly this use.
        self.assertEqual(len(DEMO_PERSONA.phone), 10)
        self.assertTrue(DEMO_PERSONA.phone.isdigit())
        line = int(DEMO_PERSONA.phone[3:])
        self.assertTrue(5550100 <= line <= 5550199, DEMO_PERSONA.phone)

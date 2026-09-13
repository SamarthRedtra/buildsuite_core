# Copyright (c) 2026, BuildSuite Core contributors

from frappe.tests import UnitTestCase

from buildsuite_core.legacy_retirement import CUSTOM_FIELD_ALLOWLIST, has_legacy_value


class TestLegacyRetirement(UnitTestCase):
	def test_landed_cost_fields_are_retired(self):
		self.assertIn(("Landed Cost Taxes and Charges", "bill_no"), CUSTOM_FIELD_ALLOWLIST)
		self.assertIn(("Landed Cost Taxes and Charges", "boq_item"), CUSTOM_FIELD_ALLOWLIST)

	def test_only_populated_legacy_values_are_archived(self):
		for empty_value in (None, "", 0, False):
			self.assertFalse(has_legacy_value(empty_value))

		for populated_value in ("Issued", "BOQ-0001", 1, "0"):
			self.assertTrue(has_legacy_value(populated_value))

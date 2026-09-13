"""Item Conversion / Dismantling integration coverage."""

from pathlib import Path

import frappe

import buildsuite_core
from buildsuite_core.overrides.stock_entry import BuildSuiteStockEntry
from buildsuite_core.tests.base import BuildSuiteTestCase
from buildsuite_core.utils.item_conversion import (
	ITEM_CONVERSION_PURPOSE,
	ITEM_CONVERSION_TYPE,
	ensure_item_conversion_stock_entry_type,
)


class TestItemConversion(BuildSuiteTestCase):
	def setUp(self):
		super().setUp()
		ensure_item_conversion_stock_entry_type()
		self.warehouse = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name")
		self.source_item = self._item("SOURCE")
		self.output_one = self._item("OUTPUT-ONE")
		self.output_two = self._item("OUTPUT-TWO")

	def _item(self, suffix):
		item_code = f"BS-CONVERT-{suffix}-{self._n}"
		return frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"valuation_rate": 100,
			}
		).insert(ignore_permissions=True)

	def _conversion(self, output_rates=(40, 60)):
		return frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": ITEM_CONVERSION_TYPE,
				"company": self.company,
				"items": [
					{
						"item_code": self.source_item.name,
						"qty": 1,
						"s_warehouse": self.warehouse,
						"basic_rate": 100,
					},
					{
						"item_code": self.output_one.name,
						"qty": 1,
						"t_warehouse": self.warehouse,
						"basic_rate": output_rates[0],
					},
					{
						"item_code": self.output_two.name,
						"qty": 1,
						"t_warehouse": self.warehouse,
						"basic_rate": output_rates[1],
					},
				],
			}
		)

	def test_type_is_owned_by_buildsuite_runtime(self):
		doc = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": ITEM_CONVERSION_TYPE})
		self.assertIsInstance(doc, BuildSuiteStockEntry)
		self.assertEqual(
			frappe.db.get_value("Stock Entry Type", ITEM_CONVERSION_TYPE, "purpose"),
			ITEM_CONVERSION_PURPOSE,
		)

	def test_balanced_conversion_accepts_split_rows(self):
		doc = self._conversion().insert(ignore_permissions=True)
		self.assertEqual(doc.purpose, ITEM_CONVERSION_PURPOSE)
		self.assertEqual(doc.total_outgoing_value, 100)
		self.assertEqual(doc.total_incoming_value, 100)
		self.assertTrue(all(row.set_basic_rate_manually for row in doc.items))
		self.assertTrue(all(not row.is_finished_item for row in doc.items))

	def test_submitted_conversion_preserves_stock_value(self):
		receipt = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": self.company,
				"items": [
					{
						"item_code": self.source_item.name,
						"qty": 1,
						"t_warehouse": self.warehouse,
						"basic_rate": 100,
					}
				],
			}
		).insert(ignore_permissions=True)
		receipt.submit()

		entry = self._conversion().insert(ignore_permissions=True)
		entry.submit()
		ledger_rows = frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_type": "Stock Entry", "voucher_no": entry.name, "is_cancelled": 0},
			fields=["item_code", "actual_qty", "stock_value_difference"],
		)
		self.assertEqual(entry.docstatus, 1)
		self.assertEqual(len(ledger_rows), 3)
		self.assertAlmostEqual(sum(row.stock_value_difference for row in ledger_rows), 0, places=2)

		entry.cancel()
		self.assertEqual(entry.docstatus, 2)
		self.assertEqual(
			frappe.db.get_value(
				"Bin", {"item_code": self.source_item.name, "warehouse": self.warehouse}, "actual_qty"
			),
			1,
		)
		for output_item in (self.output_one, self.output_two):
			self.assertEqual(
				frappe.db.get_value(
					"Bin", {"item_code": output_item.name, "warehouse": self.warehouse}, "actual_qty"
				),
				0,
			)

	def test_conversion_rejects_unbalanced_output_value(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Total output valuation"):
			self._conversion((49, 49)).insert(ignore_permissions=True)

	def test_conversion_absorbs_a_small_rounding_difference(self):
		doc = self._conversion((49.75, 49.75)).insert(ignore_permissions=True)
		self.assertEqual(doc.total_outgoing_value, 100)
		self.assertEqual(doc.total_incoming_value, 100)
		self.assertEqual(doc.items[-1].basic_amount, 50.25)

	def test_conversion_rejects_a_row_with_both_warehouses(self):
		doc = self._conversion()
		doc.append(
			"items",
			{
				"item_code": self.output_one.name,
				"qty": 1,
				"s_warehouse": self.warehouse,
				"t_warehouse": self.warehouse,
				"basic_rate": 1,
			},
		)
		with self.assertRaisesRegex(frappe.ValidationError, "not both"):
			doc.insert(ignore_permissions=True)

	def test_standard_transfer_keeps_native_warehouse_validation(self):
		doc = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Transfer",
				"company": self.company,
				"items": [
					{
						"item_code": self.source_item.name,
						"qty": 1,
						"s_warehouse": self.warehouse,
					}
				],
			}
		)
		with self.assertRaisesRegex(frappe.ValidationError, "Target Warehouse is required"):
			doc.insert(ignore_permissions=True)

	def test_desk_script_does_not_hide_stock_entry_types(self):
		app_root = Path(buildsuite_core.__file__).resolve().parent
		script = (app_root / "public" / "js" / "stock_entry.js").read_text()
		self.assertNotIn('set_query("stock_entry_type"', script)

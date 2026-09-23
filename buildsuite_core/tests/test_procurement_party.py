# Copyright (c) 2026, Infraholic Innovations Pvt. Ltd and contributors
# For license information, please see license.txt

"""Party fields + posting date on Material Consumption / Material Request."""

import frappe
from frappe.utils import add_days, nowdate

from buildsuite_core.api import material_consumption as consumption_api
from buildsuite_core.api import procurement_docs
from buildsuite_core.tests.base import BuildSuiteTestCase
from buildsuite_core.utils.procurement_party import apply_party_fields


class TestProcurementPartyAndDate(BuildSuiteTestCase):
	def _supplier(self):
		return frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": f"UAT Party Supplier {self._n}",
				"supplier_group": frappe.db.get_value("Supplier Group", {}, "name"),
				"supplier_type": "Company",
			}
		).insert(ignore_permissions=True)

	def _customer(self):
		return frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"UAT Party Customer {self._n}",
				"customer_type": "Company",
				"customer_group": frappe.db.get_value("Customer Group", {}, "name"),
				"territory": frappe.db.get_value("Territory", {}, "name"),
			}
		).insert(ignore_permissions=True)

	def _item(self):
		return frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": f"UAT-CONS-{self._n}-{frappe.generate_hash(length=4)}",
				"item_name": "UAT Consumption Item",
				"item_group": frappe.db.get_value("Item Group", {}, "name"),
				"stock_uom": "Nos",
				"is_stock_item": 1,
			}
		).insert(ignore_permissions=True)

	def test_apply_party_fields_requires_both_or_neither(self):
		doc = frappe.new_doc("Stock Entry")
		doc.stock_entry_type = "Material Issue"
		with self.assertRaises(frappe.ValidationError):
			apply_party_fields(doc, "Supplier", None)
		with self.assertRaises(frappe.ValidationError):
			apply_party_fields(doc, None, "SOME-PARTY")
		with self.assertRaises(frappe.ValidationError):
			apply_party_fields(doc, "Contractor", "x")

	def test_material_request_saves_party(self):
		project = self._make_project(company=self.company)
		customer = self._customer()
		item = self._item()
		mr = procurement_docs.save_material_request(
			project=project.name,
			schedule_date=add_days(nowdate(), 7),
			party_type="Customer",
			party=customer.name,
			items=frappe.as_json([{"item_code": item.name, "qty": 2, "rate": 10}]),
		)
		self.assertEqual(mr["party_type"], "Customer")
		self.assertEqual(mr["party"], customer.name)
		self.assertEqual(mr["party_name"], customer.customer_name)
		doc = frappe.get_doc("Material Request", mr["name"])
		self.assertEqual(doc.custom_party_type, "Customer")
		self.assertEqual(doc.custom_party, customer.name)

	def test_material_consumption_saves_posting_date_and_party(self):
		project = self._make_project(company=self.company)
		supplier = self._supplier()
		item = self._item()
		warehouse = frappe.db.get_value(
			"Warehouse", {"project": project.name, "is_group": 0, "disabled": 0}, "name"
		)
		self.assertTrue(warehouse)
		# Seed stock so Material Issue can resolve valuation rate on save.
		frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": self.company,
				"project": project.name,
				"to_warehouse": warehouse,
				"items": [
					{
						"item_code": item.name,
						"qty": 5,
						"t_warehouse": warehouse,
						"basic_rate": 25,
					}
				],
			}
		).insert(ignore_permissions=True).submit()

		backdated = add_days(nowdate(), -3)
		res = consumption_api.save_material_consumption(
			project=project.name,
			posting_date=backdated,
			party_type="Supplier",
			party=supplier.name,
			items=frappe.as_json([{"item_code": item.name, "qty": 1}]),
		)
		self.assertEqual(res["posting_date"], str(backdated))
		self.assertEqual(res["party_type"], "Supplier")
		self.assertEqual(res["party"], supplier.name)
		self.assertEqual(res["party_name"], supplier.supplier_name)
		doc = frappe.get_doc("Stock Entry", res["name"])
		self.assertEqual(str(doc.posting_date), str(backdated))
		self.assertEqual(doc.custom_party_type, "Supplier")
		self.assertEqual(doc.custom_party, supplier.name)

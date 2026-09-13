"""Finance reads remain available while optional ERPNext fields are being synchronized."""

from unittest.mock import patch

import frappe

from buildsuite_core.tests.base import BuildSuiteTestCase


class TestFinanceSchemaCompatibility(BuildSuiteTestCase):
	def setUp(self):
		super().setUp()
		self.company = frappe.db.get_single_value("Global Defaults", "default_company") or self.company
		self.project = self._make_project(company=self.company).name

	def test_schema_helper_exposes_only_available_fields(self):
		from buildsuite_core.utils.invoice_finance import (
			available_invoice_finance_fields,
			invoice_finance_sql_field,
		)

		with patch.object(frappe.db, "get_table_columns", return_value=["retention_amount"]):
			fields = set(available_invoice_finance_fields("Sales Invoice"))
		self.assertEqual(fields, {"retention_amount"})
		self.assertEqual(invoice_finance_sql_field("retention_amount", fields, "si"), "si.`retention_amount`")
		self.assertEqual(invoice_finance_sql_field("total_advance", fields), "0")

	def test_invoice_and_payable_lists_tolerate_missing_finance_fields(self):
		from buildsuite_core.api import invoice, supplier_bill

		with patch.object(invoice, "available_invoice_finance_fields", return_value=[]):
			self.assertIsInstance(invoice.list_invoices(company=self.company), list)
		with patch.object(supplier_bill, "available_invoice_finance_fields", return_value=[]):
			self.assertIsInstance(supplier_bill.list_payables(company=self.company), list)

	def test_finance_views_tolerate_missing_finance_fields(self):
		from buildsuite_core.api import finance_report
		from buildsuite_core.buildsuite_core.report.billing_and_collection import billing_and_collection
		from buildsuite_core.buildsuite_core.report.subcontractor_bill_register import (
			subcontractor_bill_register,
		)
		from buildsuite_core.buildsuite_core.report.subcontractor_position import subcontractor_position

		with patch.object(finance_report, "available_invoice_finance_fields", return_value=[]):
			aged = finance_report.receivables_and_payables(company=self.company)
		self.assertIn("receivables", aged)
		self.assertIn("payables", aged)

		for report in (billing_and_collection, subcontractor_bill_register, subcontractor_position):
			with patch.object(report, "available_invoice_finance_fields", return_value=[]):
				result = report.execute({"project": self.project})
			self.assertIsInstance(result[1], list)

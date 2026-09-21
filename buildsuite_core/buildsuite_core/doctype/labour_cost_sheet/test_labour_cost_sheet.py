# Copyright (c) 2026, Infraholic Innovations Pvt. Ltd and Contributors
# See license.txt

import frappe
from frappe.utils import flt

from buildsuite_core.tests.base import BuildSuiteTestCase


class TestLabourCostSheet(BuildSuiteTestCase):
	def setUp(self):
		super().setUp()
		self._sync_journal_entry_series()
		self.project = self._make_project(company=self.company).name
		self.employee = self._make_employee()
		self.expense_account = self._account(
			f"Labour Cost {self._n}", "Expense", "Expense Account", "Expenses"
		)
		self.credit_account = self._account(
			f"Labour Accrual {self._n}", "Liability", "", "Current Liabilities"
		)

	def _sync_journal_entry_series(self):
		"""Some shared UAT fixtures carry JEs above their rolled-back test series counter."""
		prefix = "ACC-JV-2026-"
		latest = frappe.db.get_value(
			"Journal Entry", {"name": ["like", f"{prefix}%"]}, "name", order_by="name desc"
		)
		if not latest:
			return
		current = int(latest.rsplit("-", 1)[-1])
		frappe.db.sql(
			"UPDATE `tabSeries` SET current = GREATEST(current, %s) WHERE name = %s",
			(current, prefix),
		)

	def _make_employee(self):
		return (
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": f"Labour {self._n}",
					"employee_name": f"Labour {self._n}",
					"company": self.company,
					"status": "Active",
					"date_of_joining": "2020-01-01",
					"date_of_birth": "1990-01-01",
					"gender": frappe.db.get_value("Gender", {}, "name") or "Male",
					"custom_wage": 300,
					"custom_wage_for_overtime": 25,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _account(self, name, root_type, account_type, parent):
		from buildsuite_core.utils.subcontract_billing import _ensure_account

		return _ensure_account(self.company, name, root_type, account_type, parent)

	def _make_attendance(self):
		regular = frappe.get_doc(
			{
				"doctype": "Labour Attendance Register",
				"employee": self.employee,
				"project": self.project,
				"attendance_date": "2026-09-15",
				"status": "Full Day",
			}
		).insert(ignore_permissions=True)
		regular.submit()

		overtime = frappe.get_doc(
			{
				"doctype": "Overtime Attendance Register",
				"employee": self.employee,
				"project": self.project,
				"overtime_date": "2026-09-15",
				"overtime_hours": 2,
			}
		).insert(ignore_permissions=True)
		overtime.submit()
		return regular, overtime

	def _make_sheet(self, submit=False):
		doc = frappe.get_doc(
			{
				"doctype": "Labour Cost Sheet",
				"project": self.project,
				"from_date": "2026-09-01",
				"to_date": "2026-09-30",
				"posting_date": "2026-09-30",
				"expense_account": self.expense_account,
				"credit_account": self.credit_account,
			}
		).insert(ignore_permissions=True)
		if submit:
			doc.submit()
		return doc

	def test_collects_regular_and_overtime_cost(self):
		self._make_attendance()
		doc = self._make_sheet()

		self.assertEqual(len(doc.sources), 2)
		self.assertEqual(len(doc.employees), 1)
		self.assertEqual(flt(doc.regular_cost), 300)
		self.assertEqual(flt(doc.overtime_cost), 50)
		self.assertEqual(flt(doc.total_cost), 350)
		self.assertEqual(flt(doc.employees[0].regular_days), 1)
		self.assertEqual(flt(doc.employees[0].overtime_hours), 2)

	def test_submit_posts_project_expense_and_cancel_reverses_it(self):
		self._make_attendance()
		doc = self._make_sheet(submit=True)
		self.assertTrue(doc.journal_entry)
		self.assertEqual(frappe.db.get_value("Journal Entry", doc.journal_entry, "docstatus"), 1)

		debit = frappe.db.get_value(
			"GL Entry",
			{
				"voucher_type": "Journal Entry",
				"voucher_no": doc.journal_entry,
				"account": self.expense_account,
			},
			["project", "debit", "credit"],
			as_dict=True,
		)
		self.assertEqual(debit.project, self.project)
		self.assertEqual(flt(debit.debit), 350)
		self.assertEqual(flt(debit.credit), 0)

		doc.db_set("cost_code_type", "Group")
		doc.db_set("cost_code_group", "L")
		doc.db_set("cost_code_label", "L · Labour")
		from buildsuite_core.api.boq_actuals import get_actuals_log

		actuals = get_actuals_log(self.project, cost_type="Labour")
		self.assertEqual(len(actuals), 1)
		self.assertEqual(flt(actuals[0]["amount"]), 350)
		self.assertEqual(actuals[0]["source_name"], doc.name)

		journal_entry = doc.journal_entry
		doc.cancel()
		self.assertEqual(frappe.db.get_value("Journal Entry", journal_entry, "docstatus"), 2)

	def test_submitted_sources_cannot_be_posted_twice(self):
		self._make_attendance()
		self._make_sheet(submit=True)

		with self.assertRaises(frappe.ValidationError):
			self._make_sheet()

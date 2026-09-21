# Copyright (c) 2026, Infraholic Innovations Pvt. Ltd and contributors
# For license information, please see license.txt

import frappe
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
)
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


def _regular_days(status):
	return {"Full Day": 1.0, "Half Day": 0.5}.get(status, 0.0)


def get_available_sources(project, from_date, to_date, exclude_sheet=None):
	"""Return submitted, cost-bearing attendance that is not in another submitted sheet."""
	if not project or not from_date or not to_date:
		return []

	used_filters = {"parenttype": "Labour Cost Sheet", "docstatus": 1}
	if exclude_sheet:
		used_filters["parent"] = ["!=", exclude_sheet]
	used = {
		(row.source_doctype, row.source_name)
		for row in frappe.get_all(
			"Labour Cost Source",
			filters=used_filters,
			fields=["source_doctype", "source_name"],
			limit_page_length=0,
		)
	}

	sources = []
	regular = frappe.get_all(
		"Labour Attendance Register",
		filters={
			"project": project,
			"docstatus": 1,
			"attendance_date": ["between", [from_date, to_date]],
		},
		fields=[
			"name",
			"employee",
			"employee_name",
			"attendance_date",
			"status",
			"daily_wage_calculated",
		],
		order_by="attendance_date, employee, name",
		limit_page_length=0,
	)
	for row in regular:
		cost = flt(row.daily_wage_calculated)
		if cost <= 0 or ("Labour Attendance Register", row.name) in used:
			continue
		sources.append(
			{
				"source_doctype": "Labour Attendance Register",
				"source_name": row.name,
				"employee": row.employee,
				"employee_name": row.employee_name,
				"source_date": row.attendance_date,
				"regular_days": _regular_days(row.status),
				"regular_cost": cost,
				"overtime_hours": 0,
				"overtime_cost": 0,
				"total_cost": cost,
			}
		)

	overtime = frappe.get_all(
		"Overtime Attendance Register",
		filters={
			"project": project,
			"docstatus": 1,
			"overtime_date": ["between", [from_date, to_date]],
		},
		fields=[
			"name",
			"employee",
			"employee_name",
			"overtime_date",
			"overtime_hours",
			"overtime_wage_calculated",
		],
		order_by="overtime_date, employee, name",
		limit_page_length=0,
	)
	for row in overtime:
		cost = flt(row.overtime_wage_calculated)
		if cost <= 0 or ("Overtime Attendance Register", row.name) in used:
			continue
		sources.append(
			{
				"source_doctype": "Overtime Attendance Register",
				"source_name": row.name,
				"employee": row.employee,
				"employee_name": row.employee_name,
				"source_date": row.overtime_date,
				"regular_days": 0,
				"regular_cost": 0,
				"overtime_hours": flt(row.overtime_hours),
				"overtime_cost": cost,
				"total_cost": cost,
			}
		)

	return sources


def aggregate_sources(sources):
	by_employee = {}
	for source in sources:
		employee = source.get("employee")
		row = by_employee.setdefault(
			employee,
			{
				"employee": employee,
				"employee_name": source.get("employee_name")
				or frappe.db.get_value("Employee", employee, "employee_name"),
				"regular_days": 0,
				"regular_cost": 0,
				"overtime_hours": 0,
				"overtime_cost": 0,
				"total_cost": 0,
			},
		)
		for field in (
			"regular_days",
			"regular_cost",
			"overtime_hours",
			"overtime_cost",
			"total_cost",
		):
			row[field] += flt(source.get(field))
	return sorted(by_employee.values(), key=lambda row: (row["employee_name"] or "", row["employee"]))


class LabourCostSheet(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from buildsuite_core.buildsuite_core.doctype.labour_cost_sheet_row.labour_cost_sheet_row import LabourCostSheetRow
		from buildsuite_core.buildsuite_core.doctype.labour_cost_source.labour_cost_source import LabourCostSource
		from frappe.types import DF

		amended_from: DF.Link | None
		company: DF.Link
		cost_center: DF.Link | None
		cost_code_group: DF.Data | None
		cost_code_item: DF.Data | None
		cost_code_label: DF.Data | None
		cost_code_type: DF.Literal["", "Group", "Item"]
		credit_account: DF.Link
		employees: DF.Table[LabourCostSheetRow]
		expense_account: DF.Link
		from_date: DF.Date
		journal_entry: DF.Link | None
		naming_series: DF.Literal["LCS-.YYYY.-.#####"]
		overtime_cost: DF.Currency
		posting_date: DF.Date
		project: DF.Link
		regular_cost: DF.Currency
		sources: DF.Table[LabourCostSource]
		to_date: DF.Date
		total_cost: DF.Currency
	# end: auto-generated types

	def validate(self):
		self.validate_dates_and_project()
		self.validate_accounts()
		self.validate_cost_code()
		self.refresh_attendance_sources()

	def before_submit(self):
		self.lock_and_validate_source_ownership()

	def on_submit(self):
		self.create_journal_entry()

	def on_cancel(self):
		self.ignore_linked_doctypes = ("GL Entry",)
		self.cancel_journal_entry()

	def validate_dates_and_project(self):
		if getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(_("From Date cannot be after To Date."))
		project = frappe.db.get_value("Project", self.project, ["company"], as_dict=True)
		if not project:
			frappe.throw(_("Project {0} was not found.").format(frappe.bold(self.project)))
		self.company = project.company

	def validate_accounts(self):
		for fieldname, expected_root in (
			("expense_account", "Expense"),
			("credit_account", None),
		):
			account = self.get(fieldname)
			values = frappe.db.get_value(
				"Account", account, ["company", "is_group", "root_type"], as_dict=True
			)
			if not values or values.company != self.company or values.is_group:
				frappe.throw(
					_("{0} must be a ledger account belonging to {1}.").format(
						frappe.bold(account), frappe.bold(self.company)
					)
				)
			if expected_root and values.root_type != expected_root:
				frappe.throw(_("Labour Expense Account must be an Expense account."))
			if fieldname == "credit_account" and values.root_type not in ("Asset", "Liability"):
				frappe.throw(_("Credit / Payable Account must be an Asset or Liability account."))
		if self.expense_account == self.credit_account:
			frappe.throw(_("The expense and credit accounts must be different."))

	def validate_cost_code(self):
		if not self.cost_code_type:
			self.cost_code_group = None
			self.cost_code_item = None
			self.cost_code_label = None
			return
		if self.cost_code_type == "Group" and not self.cost_code_group:
			frappe.throw(_("Choose a BOQ group cost code."))
		if self.cost_code_type == "Item" and not self.cost_code_item:
			frappe.throw(_("Choose a BOQ item cost code."))

		from buildsuite_core.api.subcontract import get_project_cost_codes

		matches = [
			code
			for code in get_project_cost_codes(self.project)
			if (code.get("type") or "").lower() == self.cost_code_type.lower()
			and code.get("group_code") == (self.cost_code_group or "")
			and code.get("item_code") == (self.cost_code_item or "")
		]
		if not matches:
			frappe.throw(_("The selected BOQ cost code is not valid for this project."))
		self.cost_code_label = matches[0].get("label")

	def refresh_attendance_sources(self):
		sources = get_available_sources(self.project, self.from_date, self.to_date, self.name)
		if not sources:
			frappe.throw(_("No unprocessed submitted labour or overtime attendance was found."))
		self.set("sources", sources)
		self.set("employees", aggregate_sources(sources))
		self.regular_cost = sum(flt(row.get("regular_cost")) for row in sources)
		self.overtime_cost = sum(flt(row.get("overtime_cost")) for row in sources)
		self.total_cost = self.regular_cost + self.overtime_cost

	def lock_and_validate_source_ownership(self):
		for source in self.sources:
			frappe.db.sql(
				f"SELECT name FROM `tab{source.source_doctype}` WHERE name = %s FOR UPDATE",  # nosec B608
				(source.source_name,),
			)
			owner = frappe.db.get_value(
				"Labour Cost Source",
				{
					"source_doctype": source.source_doctype,
					"source_name": source.source_name,
					"parenttype": self.doctype,
					"parent": ["!=", self.name],
					"docstatus": 1,
				},
				"parent",
			)
			if owner:
				frappe.throw(
					_("Attendance {0} is already posted by Labour Cost Sheet {1}.").format(
						frappe.bold(source.source_name), frappe.bold(owner)
					)
				)

	def create_journal_entry(self):
		default_cost_center = self.cost_center or frappe.db.get_value(
			"Company", self.company, "cost_center"
		)
		credit_type = frappe.db.get_value("Account", self.credit_account, "account_type")
		if credit_type == "Receivable":
			frappe.throw(_("A Receivable account cannot be used as the labour credit account."))

		accounts = []
		accounting_dimensions = get_accounting_dimensions() or []
		for employee_row in self.employees:
			amount = flt(employee_row.total_cost)
			debit = {
				"account": self.expense_account,
				"debit_in_account_currency": amount,
				"credit_in_account_currency": 0,
				"cost_center": default_cost_center,
				"project": self.project,
				"user_remark": _("Labour cost for {0}").format(employee_row.employee_name),
			}
			if "employee" in accounting_dimensions:
				debit["employee"] = employee_row.employee
			accounts.append(debit)

			credit = {
				"account": self.credit_account,
				"debit_in_account_currency": 0,
				"credit_in_account_currency": amount,
				"cost_center": default_cost_center,
				"user_remark": _("Labour cost payable for {0}").format(employee_row.employee_name),
			}
			if credit_type == "Payable":
				credit.update({"party_type": "Employee", "party": employee_row.employee})
			accounts.append(credit)

		je = frappe.new_doc("Journal Entry")
		je.update(
			{
				"voucher_type": "Journal Entry",
				"company": self.company,
				"posting_date": self.posting_date,
				"cheque_no": self.name if credit_type == "Bank" else None,
				"cheque_date": self.posting_date if credit_type == "Bank" else None,
				"remark": _("Labour Cost Sheet {0} for project {1}").format(
					self.name, self.project
				),
				"reference_doctype": self.doctype,
				"reference_docname": self.name,
			}
		)
		je.set("accounts", accounts)
		je.flags.ignore_permissions = True
		je.insert()
		je.submit()
		self.db_set("journal_entry", je.name)

	def cancel_journal_entry(self):
		if not self.journal_entry:
			return
		if frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus") == 1:
			je = frappe.get_doc("Journal Entry", self.journal_entry)
			je.flags.ignore_permissions = True
			je.cancel()
		self.db_set("journal_entry", None)

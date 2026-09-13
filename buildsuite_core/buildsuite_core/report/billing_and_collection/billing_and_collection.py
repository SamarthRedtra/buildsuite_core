# Copyright (c) 2026, Infraholic Innovations Pvt. Ltd and contributors
# For license information, please see license.txt

"""Billing and Collection — one row per client invoice on a project (raised, cash received,
outstanding, days overdue), with Invoiced / Received / Overdue / Retention held summary
cards. Matches the prototype's per-invoice view rather than a single cumulative total.

A Script Report so the filters bind only when present (Frappe runs with empty filters on
page load; a Query Report's %(x)s would crash). Project is required; the date range is
optional and applied only when supplied.

Retention and advances are read from ERPNext's native Sales Invoice fields and are never
classified as cash receipts."""

import frappe
from frappe import _

from buildsuite_core.utils.invoice_finance import (
	available_invoice_finance_fields,
	invoice_finance_sql_field,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{
			"label": _("Invoice"),
			"fieldname": "invoice",
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 160,
		},
		{
			"label": _("Customer"),
			"fieldname": "customer",
			"fieldtype": "Link",
			"options": "Customer",
			"width": 180,
		},
		{"label": _("Raised"), "fieldname": "raised", "fieldtype": "Date", "width": 100},
		{"label": _("Due"), "fieldname": "due_date", "fieldtype": "Date", "width": 100},
		{"label": _("Overdue (days)"), "fieldname": "overdue_days", "fieldtype": "Int", "width": 110},
		{"label": _("Invoiced"), "fieldname": "invoiced", "fieldtype": "Currency", "width": 120},
		{"label": _("Cash Received"), "fieldname": "received", "fieldtype": "Currency", "width": 120},
		{"label": _("Advance"), "fieldname": "advance", "fieldtype": "Currency", "width": 110},
		{"label": _("Outstanding"), "fieldname": "outstanding", "fieldtype": "Currency", "width": 120},
		{"label": _("Retention"), "fieldname": "retention", "fieldtype": "Currency", "width": 110},
	]
	if not filters.get("project"):
		return columns, [], None, None, []

	conditions = ""
	if filters.get("from_date"):
		conditions += " AND si.posting_date >= %(from_date)s"
	if filters.get("to_date"):
		conditions += " AND si.posting_date <= %(to_date)s"
	if filters.get("overdue_only"):
		conditions += " AND si.outstanding_amount > 0 AND si.due_date < CURDATE()"
	si_fields = set(available_invoice_finance_fields("Sales Invoice"))
	retention_field = invoice_finance_sql_field("retention_outstanding_amount", si_fields, "si")
	advance_field = invoice_finance_sql_field("total_advance", si_fields, "si")

	data = frappe.db.sql(
		f"""
		SELECT si.name AS invoice,
			si.customer AS customer,
			si.posting_date AS raised,
			si.due_date AS due_date,
			CASE WHEN si.outstanding_amount > 0 AND si.due_date < CURDATE()
				THEN DATEDIFF(CURDATE(), si.due_date) ELSE 0 END AS overdue_days,
			si.grand_total AS invoiced,
			GREATEST(si.grand_total - IFNULL({retention_field}, 0)
				- IFNULL({advance_field}, 0) - si.outstanding_amount, 0) AS received,
			IFNULL({advance_field}, 0) AS advance,
			si.outstanding_amount AS outstanding,
			IFNULL({retention_field}, 0) AS retention
		FROM `tabSales Invoice` si
		WHERE si.docstatus = 1 AND si.project = %(project)s """
		+ conditions
		+ """
		ORDER BY si.posting_date DESC, si.name DESC
		""",
		filters,
		as_dict=True,
	)

	invoiced = sum(row.invoiced or 0 for row in data)
	received = sum(row.received or 0 for row in data)
	retention = sum(row.retention or 0 for row in data)
	overdue = sum(row.outstanding or 0 for row in data if row.overdue_days)

	report_summary = [
		{"label": _("Invoiced"), "value": invoiced, "datatype": "Currency"},
		{"label": _("Cash received"), "value": received, "datatype": "Currency", "indicator": "green"},
		{
			"label": _("Overdue"),
			"value": overdue,
			"datatype": "Currency",
			"indicator": "red" if overdue else "",
		},
		{"label": _("Retention outstanding"), "value": retention, "datatype": "Currency"},
	]

	return columns, data, None, None, report_summary

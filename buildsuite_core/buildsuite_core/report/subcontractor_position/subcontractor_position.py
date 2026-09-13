# Copyright (c) 2026, Infraholic Innovations Pvt. Ltd and contributors
# For license information, please see license.txt

"""Subcontractor Position — WO value, measured, billed, paid, retention and outstanding per
subcontractor, for one project.

A Script Report so the project condition binds only when set (Frappe runs with empty filters
on page load; a Query Report's %(project)s would crash). Project is required."""

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
			"label": _("Subcontractor"),
			"fieldname": "subcontractor",
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 200,
		},
		{"label": _("Name"), "fieldname": "subcontractor_name", "fieldtype": "Data", "width": 200},
		{"label": _("WO Value"), "fieldname": "wo_value", "fieldtype": "Currency", "width": 110},
		{"label": _("Measured Qty"), "fieldname": "measured", "fieldtype": "Float", "width": 110},
		{"label": _("Billed"), "fieldname": "billed", "fieldtype": "Currency", "width": 110},
		{"label": _("Retention"), "fieldname": "retention", "fieldtype": "Currency", "width": 110},
		{"label": _("Advance"), "fieldname": "advance", "fieldtype": "Currency", "width": 110},
		{"label": _("Paid"), "fieldname": "paid", "fieldtype": "Currency", "width": 110},
		{"label": _("Outstanding"), "fieldname": "outstanding", "fieldtype": "Currency", "width": 110},
	]
	if not filters.get("project"):
		return columns, []

	# Optional Subcontractor filter — narrow to one subcontractor across all three legs.
	sub_cond = " AND x.subcontractor = %(subcontractor)s" if filters.get("subcontractor") else ""
	pi_fields = set(available_invoice_finance_fields("Purchase Invoice"))
	retention_field = invoice_finance_sql_field(
		"retention_outstanding_amount", pi_fields, "pi", missing="NULL"
	)
	advance_field = invoice_finance_sql_field("total_advance", pi_fields, "pi")

	data = frappe.db.sql(
		f"""
		SELECT subcontractor, MAX(subcontractor_name) AS subcontractor_name,
			SUM(wo_value) AS wo_value, SUM(measured) AS measured, SUM(billed) AS billed,
			SUM(retention) AS retention, SUM(advance) AS advance, SUM(paid) AS paid,
			SUM(outstanding) AS outstanding
		FROM (
			SELECT wo.subcontractor, wo.subcontractor_name, wo.total_value AS wo_value,
				0 measured, 0 billed, 0 retention, 0 advance, 0 paid, 0 outstanding
				FROM `tabSubcontractor Work Order` wo
				WHERE wo.docstatus = 1 AND wo.project = %(project)s
			UNION ALL
			SELECT wo.subcontractor, wo.subcontractor_name, 0, mb.measured_total, 0, 0, 0, 0, 0
				FROM `tabMeasurement Book` mb
				JOIN `tabSubcontractor Work Order` wo ON wo.name = mb.work_order
				WHERE mb.status = 'Certified' AND mb.project = %(project)s
			UNION ALL
			SELECT sb.subcontractor, sb.subcontractor_name, 0, 0,
				IFNULL(pi.grand_total, sb.gross),
				IFNULL({retention_field}, sb.retention_amount),
				IFNULL({advance_field}, 0),
				GREATEST(IFNULL(pi.grand_total, 0) - IFNULL({retention_field}, 0)
					- IFNULL({advance_field}, 0) - IFNULL(pi.outstanding_amount, 0), 0),
				IFNULL(pi.outstanding_amount, 0)
				FROM `tabSubcontractor Bill` sb
				LEFT JOIN `tabPurchase Invoice` pi ON pi.name = sb.purchase_invoice AND pi.docstatus = 1
				WHERE sb.docstatus = 1 AND sb.project = %(project)s
		) x
		WHERE 1=1 """
		+ sub_cond
		+ """
		GROUP BY subcontractor HAVING SUM(wo_value) + SUM(billed) > 0 ORDER BY SUM(wo_value) DESC
		""",
		filters,
		as_dict=True,
	)
	return columns, data

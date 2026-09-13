"""Migrate legacy amount-based subcontract advance recovery to a percentage."""

import frappe
from frappe.utils import flt


def execute():
	if not frappe.db.exists("DocType", "Subcontractor Bill"):
		return
	columns = set(frappe.db.get_table_columns("Subcontractor Bill"))
	if not {"advance_recovery", "advance_recovery_percent"}.issubset(columns):
		return

	rows = frappe.db.sql(
		"""
			SELECT name, advance_recovery, invoice_value, grand_total
			FROM `tabSubcontractor Bill`
			WHERE IFNULL(advance_recovery_percent, 0) = 0
				AND IFNULL(advance_recovery, 0) > 0
		""",
		as_dict=True,
	)
	for row in rows:
		base = flt(row.invoice_value or row.grand_total)
		if base <= 0:
			continue
		percentage = flt(flt(row.advance_recovery) * 100 / base, 6)
		frappe.db.set_value(
			"Subcontractor Bill",
			row.name,
			"advance_recovery_percent",
			percentage,
			update_modified=False,
		)

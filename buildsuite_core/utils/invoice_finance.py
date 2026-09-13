"""Shared native retention, advance, cash, and PDC summaries for ERPNext invoices."""

import frappe
from frappe.utils import flt

INVOICE_FINANCE_FIELDS = (
	"retention_amount",
	"retention_released_amount",
	"retention_outstanding_amount",
	"advance_recovery_amount",
	"total_advance",
)


def available_invoice_finance_fields(doctype):
	columns = set(frappe.db.get_table_columns(doctype))
	return [fieldname for fieldname in INVOICE_FINANCE_FIELDS if fieldname in columns]


def invoice_finance_sql_field(fieldname, available_fields, table_alias=None, missing="0"):
	if fieldname not in INVOICE_FINANCE_FIELDS:
		raise ValueError(f"Unsupported invoice finance field: {fieldname}")
	if fieldname not in available_fields:
		return missing
	prefix = f"{table_alias}." if table_alias else ""
	return f"{prefix}`{fieldname}`"


def invoice_finance_summary(doc, advance_adjusted=0, cash_key=None):
	"""Return a settlement waterfall without classifying retention or advances as cash."""
	gross_total = flt(doc.get("rounded_total") or doc.get("grand_total"))
	retention_held = flt(doc.get("retention_amount"))
	retention_released = flt(doc.get("retention_released_amount"))
	retention_outstanding = flt(doc.get("retention_outstanding_amount"))
	advance_limit = flt(doc.get("advance_recovery_amount"))
	advance_adjusted = flt(advance_adjusted)
	docstatus = int(doc.get("docstatus") or 0)

	if docstatus == 1:
		amount_due_now = max(flt(doc.get("outstanding_amount")), 0)
		cash_settled = max(gross_total - retention_outstanding - advance_adjusted - amount_due_now, 0)
	elif docstatus == 0:
		amount_due_now = max(gross_total - retention_outstanding - advance_adjusted, 0)
		cash_settled = 0
	else:
		amount_due_now = 0
		cash_settled = 0

	if docstatus == 0:
		status = "Draft"
	elif docstatus == 2:
		status = "Cancelled"
	elif amount_due_now <= 0.01 and gross_total > 0:
		status = "Paid"
	elif cash_settled > 0.01 or advance_adjusted > 0.01:
		status = "Partly Paid"
	else:
		status = "Unpaid"

	summary = {
		"invoiced": gross_total,
		"gross_total": gross_total,
		"retention_held": retention_held,
		"retention_released": retention_released,
		"retention_outstanding": retention_outstanding,
		"advance_recovery_limit": advance_limit,
		"advance_adjusted": advance_adjusted,
		"cash_settled": cash_settled,
		"amount_due_now": amount_due_now,
		"outstanding": amount_due_now,
		"status": status,
	}
	if cash_key:
		summary[cash_key] = cash_settled
	return summary


def invoice_pdc_summary(reference_doctype, reference_name):
	presented_on_field = (
		"pdc.presented_on"
		if "presented_on" in frappe.db.get_table_columns("Post Dated Cheques")
		else "NULL AS presented_on"
	)
	rows = frappe.db.sql(
		f"""
			SELECT
				pdc.name,
				pdc.payment_type,
				pdc.status,
				pdc.reference_no,
				pdc.reference_date,
				{presented_on_field},
				pdc.actual_posting_date,
				pdc.payment_entry,
				ref.allocated_amount
			FROM `tabPDC Invoice Reference` ref
			INNER JOIN `tabPost Dated Cheques` pdc ON pdc.name = ref.parent
			WHERE ref.reference_doctype = %(reference_doctype)s
				AND ref.reference_name = %(reference_name)s
			ORDER BY pdc.reference_date, pdc.creation
		""",
		{"reference_doctype": reference_doctype, "reference_name": reference_name},
		as_dict=True,
	)
	active = {"Pending", "Presented"}
	return {
		"rows": rows,
		"active_allocated": sum(flt(row.allocated_amount) for row in rows if row.status in active),
		"cleared": sum(flt(row.allocated_amount) for row in rows if row.status in {"Cleared", "Converted"}),
		"bounced": sum(flt(row.allocated_amount) for row in rows if row.status == "Bounced"),
	}


def invoice_retention_releases(reference_doctype, reference_name):
	"""Return native retention releases without re-deriving their posted accounting."""
	if not reference_name or not frappe.db.exists("DocType", "Retention Release Entry"):
		return []
	return frappe.get_all(
		"Retention Release Entry",
		filters={
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
		},
		fields=["name", "posting_date", "retention_amount", "docstatus", "remarks"],
		order_by="posting_date desc, creation desc",
		limit_page_length=0,
	)

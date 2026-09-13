"""BuildSuite façade for ERPNext's native Retention Release Entry lifecycle."""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from buildsuite_core.utils.invoice_finance import invoice_finance_summary

RRE = "Retention Release Entry"
INVOICE_TYPES = ("Sales Invoice", "Purchase Invoice")


def _serialize(doc):
	return {
		"name": doc.name,
		"docstatus": doc.docstatus,
		"company": doc.company,
		"posting_date": str(doc.posting_date) if doc.posting_date else None,
		"reference_doctype": doc.reference_doctype,
		"reference_name": doc.reference_name,
		"party_type": doc.party_type,
		"party": doc.party,
		"project": doc.project,
		"party_account": doc.party_account,
		"retention_account": doc.retention_account,
		"retention_amount": flt(doc.retention_amount),
		"base_retention_amount": flt(doc.base_retention_amount),
		"remarks": doc.remarks,
	}


def _invoice_summary(reference_doctype, reference_name):
	invoice = frappe.get_doc(reference_doctype, reference_name)
	invoice.check_permission("read")
	return invoice_finance_summary(
		invoice,
		advance_adjusted=flt(invoice.get("total_advance")),
		cash_key="received" if reference_doctype == "Sales Invoice" else "paid",
	)


@frappe.whitelist()
def list_retention_releases(project=None, company=None, reference_doctype=None, reference_name=None):
	filters = {}
	if project:
		filters["project"] = project
	if company:
		filters["company"] = company
	if reference_doctype:
		if reference_doctype not in INVOICE_TYPES:
			frappe.throw(_("Reference Document Type must be Sales Invoice or Purchase Invoice"))
		filters["reference_doctype"] = reference_doctype
	if reference_name:
		filters["reference_name"] = reference_name

	return frappe.get_list(
		RRE,
		filters=filters,
		fields=[
			"name",
			"docstatus",
			"company",
			"posting_date",
			"reference_doctype",
			"reference_name",
			"party_type",
			"party",
			"project",
			"retention_amount",
			"remarks",
		],
		order_by="posting_date desc, creation desc",
		limit_page_length=0,
	)


@frappe.whitelist()
def get_retention_release(name):
	doc = frappe.get_doc(RRE, name)
	doc.check_permission("read")
	return _serialize(doc)


@frappe.whitelist()
def create_retention_release(
	reference_doctype,
	reference_name,
	amount=None,
	posting_date=None,
	remarks=None,
	submit=False,
):
	"""Create a native release entry; ERPNext validates the available retained balance."""
	if reference_doctype not in INVOICE_TYPES:
		frappe.throw(_("Reference Document Type must be Sales Invoice or Purchase Invoice"))

	invoice = frappe.get_doc(reference_doctype, reference_name)
	invoice.check_permission("read")
	available = flt(invoice.get("retention_outstanding_amount"))
	release_amount = flt(amount) if amount not in (None, "") else available
	if release_amount <= 0:
		frappe.throw(_("Retention Release Amount must be greater than zero"))
	if release_amount > available:
		frappe.throw(_("Retention Release Amount cannot exceed {0}").format(available))

	doc = frappe.get_doc(
		{
			"doctype": RRE,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"posting_date": posting_date or nowdate(),
			"retention_amount": release_amount,
			"remarks": remarks,
		}
	)
	doc.insert()
	if frappe.utils.cint(submit):
		doc.submit()
	return {"release": _serialize(doc), "invoice": _invoice_summary(reference_doctype, reference_name)}


@frappe.whitelist()
def submit_retention_release(name):
	doc = frappe.get_doc(RRE, name)
	doc.check_permission("submit")
	if doc.docstatus == 0:
		doc.submit()
	elif doc.docstatus != 1:
		frappe.throw(_("Cancelled retention releases cannot be submitted"))
	return {
		"release": _serialize(doc),
		"invoice": _invoice_summary(doc.reference_doctype, doc.reference_name),
	}


@frappe.whitelist()
def cancel_retention_release(name):
	doc = frappe.get_doc(RRE, name)
	doc.check_permission("cancel")
	if doc.docstatus == 1:
		doc.cancel()
	elif doc.docstatus != 2:
		frappe.throw(_("Only a submitted retention release can be cancelled"))
	return {
		"release": _serialize(doc),
		"invoice": _invoice_summary(doc.reference_doctype, doc.reference_name),
	}

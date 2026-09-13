"""BuildSuite PDC register over ERPNext's native Post Dated Cheques workflow."""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

PDC = "Post Dated Cheques"


def serialize_pdc(doc):
	return {
		"name": doc.name,
		"docstatus": doc.docstatus,
		"status": doc.status,
		"company": doc.company,
		"project": doc.project,
		"payment_type": doc.payment_type,
		"direction": "Incoming" if doc.payment_type == "Receive" else "Outgoing",
		"party_type": doc.party_type,
		"party": doc.party,
		"party_name": doc.party_name,
		"posting_date": doc.posting_date,
		"presented_on": doc.get("presented_on"),
		"actual_posting_date": doc.actual_posting_date,
		"mode_of_payment": doc.mode_of_payment,
		"reference_no": doc.reference_no,
		"reference_date": doc.reference_date,
		"amount": flt(doc.amount),
		"bank_account": doc.bank_account,
		"payment_entry": doc.payment_entry,
		"notes": doc.notes,
		"invoice_references": [
			{
				"reference_doctype": row.reference_doctype,
				"reference_name": row.reference_name,
				"total_amount": flt(row.total_amount),
				"outstanding_amount": flt(row.outstanding_amount),
				"allocated_amount": flt(row.allocated_amount),
			}
			for row in doc.invoice_references
		],
	}


@frappe.whitelist()
def list_pdcs(project=None, company=None, direction=None, status=None):
	filters = {"docstatus": ["in", [1, 2]]}
	if project:
		filters["project"] = project
	if company:
		filters["company"] = company
	if direction:
		filters["payment_type"] = "Receive" if direction == "Incoming" else "Pay"
	if status:
		filters["status"] = status

	rows = frappe.get_list(
		PDC,
		filters=filters,
		fields=[
			"name",
			"status",
			"company",
			"project",
			"payment_type",
			"party_type",
			"party",
			"party_name",
			"reference_no",
			"reference_date",
			"amount",
			"bank_account",
			"payment_entry",
			"invoice_links_list",
			"docstatus",
		],
		order_by="reference_date desc, creation desc",
		limit_page_length=0,
	)
	for row in rows:
		row.direction = "Incoming" if row.payment_type == "Receive" else "Outgoing"
	return rows


@frappe.whitelist()
def get_pdc(name):
	doc = frappe.get_doc(PDC, name)
	doc.check_permission("read")
	return serialize_pdc(doc)


@frappe.whitelist()
def save_pdc(payload):
	data = frappe.parse_json(payload)
	name = data.get("name")
	if name and frappe.db.exists(PDC, name):
		doc = frappe.get_doc(PDC, name)
		doc.check_permission("write")
		if doc.docstatus != 0:
			frappe.throw(_("Only a draft PDC can be edited."))
	else:
		doc = frappe.new_doc(PDC)

	payment_type = data.get("payment_type") or (
		"Receive" if data.get("direction", "Incoming") == "Incoming" else "Pay"
	)
	doc.payment_type = payment_type
	doc.party_type = "Customer" if payment_type == "Receive" else "Supplier"
	for fieldname in (
		"company",
		"project",
		"party",
		"party_name",
		"posting_date",
		"mode_of_payment",
		"reference_no",
		"reference_date",
		"bank_account",
		"cost_center",
		"department",
		"notes",
	):
		if fieldname in data:
			doc.set(fieldname, data.get(fieldname))
	doc.posting_date = doc.posting_date or nowdate()
	if doc.party and not doc.party_name:
		name_field = "customer_name" if doc.party_type == "Customer" else "supplier_name"
		doc.party_name = frappe.db.get_value(doc.party_type, doc.party, name_field)

	doc.set("invoice_references", [])
	for row in data.get("invoice_references") or []:
		doc.append(
			"invoice_references",
			{
				"reference_doctype": row.get("reference_doctype"),
				"reference_name": row.get("reference_name"),
				"allocated_amount": flt(row.get("allocated_amount")),
			},
		)
	doc.amount = sum(flt(row.allocated_amount) for row in doc.invoice_references)
	doc.save()
	return serialize_pdc(doc)


@frappe.whitelist()
def submit_pdc(name):
	doc = frappe.get_doc(PDC, name)
	doc.check_permission("submit")
	doc.submit()
	return serialize_pdc(doc)


@frappe.whitelist()
def available_invoice_balances(reference_doctype, company, party, current_pdc=None):
	from erpnext.pdc.doctype.post_dated_cheques.post_dated_cheques import (
		list_available_invoice_balances,
	)

	return list_available_invoice_balances(reference_doctype, company, party, current_pdc)


@frappe.whitelist()
def present_pdc(name):
	from erpnext.pdc.doctype.post_dated_cheques.post_dated_cheques import present_post_dated_cheque

	return present_post_dated_cheque(name)


@frappe.whitelist()
def clear_pdc(name, bank_account=None, posting_date=None):
	from erpnext.pdc.doctype.post_dated_cheques.post_dated_cheques import clear_post_dated_cheque

	return clear_post_dated_cheque(name, bank_account=bank_account, posting_date=posting_date)


@frappe.whitelist()
def bounce_pdc(name):
	from erpnext.pdc.doctype.post_dated_cheques.post_dated_cheques import bounce_post_dated_cheque

	return bounce_post_dated_cheque(name)


@frappe.whitelist()
def cancel_pdc(name):
	from erpnext.pdc.doctype.post_dated_cheques.post_dated_cheques import cancel_post_dated_cheque

	return cancel_post_dated_cheque(name)

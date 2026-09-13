"""BOQ-to-contract and native progressive-billing orchestration."""

import frappe
from frappe import _
from frappe.utils import flt, nowdate


def ensure_contract_item(item_code="BuildSuite Contract Work", uom="Nos"):
	if frappe.db.exists("Item", item_code):
		return item_code
	if not frappe.db.exists("UOM", uom):
		frappe.get_doc({"doctype": "UOM", "uom_name": uom}).insert(ignore_permissions=True)
	item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
	frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"item_group": item_group,
			"stock_uom": uom,
			"is_stock_item": 0,
			"is_sales_item": 1,
			"is_purchase_item": 0,
		}
	).insert(ignore_permissions=True)
	return item_code


@frappe.whitelist()
def boq_to_sales_order(boq, payload=None):
	data = frappe.parse_json(payload) if payload else {}
	doc = frappe.get_doc("BOQ", boq)
	doc.check_permission("read")
	if not frappe.has_permission("Sales Order", "create"):
		frappe.throw(_("You are not permitted to create a Sales Order."), frappe.PermissionError)
	if doc.status != "Approved":
		frappe.throw(_("Only an Approved BOQ can create a Sales Order."))
	if doc.sales_order and frappe.db.exists("Sales Order", doc.sales_order):
		return {"sales_order": doc.sales_order, "already_created": True}

	project = frappe.get_doc("Project", doc.project)
	customer = data.get("customer") or project.customer
	if not customer:
		frappe.throw(_("The Project needs a Customer before creating its Sales Order."))

	items = data.get("items") or []
	if not items:
		item_code = ensure_contract_item()
		items = [
			{
				"item_code": item_code,
				"description": doc.title,
				"qty": 1,
				"rate": flt(doc.planned_amount) + flt(doc.margin_amount),
			}
		]

	so = frappe.new_doc("Sales Order")
	so.company = doc.company or project.company
	so.customer = customer
	so.project = doc.project
	so.custom_buildsuite_boq = doc.name
	so.transaction_date = data.get("transaction_date") or nowdate()
	so.delivery_date = data.get("delivery_date") or project.expected_end_date or so.transaction_date
	so.currency = frappe.db.get_value("Company", so.company, "default_currency")
	so.taxes_and_charges = data.get("taxes_and_charges") or None
	for line in items:
		item_code = ensure_contract_item(
			line.get("item_code") or "BuildSuite Contract Work", line.get("uom") or "Nos"
		)
		so.append(
			"items",
			{
				"item_code": item_code,
				"description": line.get("description") or doc.title,
				"qty": flt(line.get("qty")) or 1,
				"uom": line.get("uom"),
				"rate": flt(line.get("rate")),
				"project": doc.project,
			},
		)
	so.flags.ignore_permissions = True
	so.set_missing_values()
	so.calculate_taxes_and_totals()
	so.insert()
	frappe.db.set_value("BOQ", doc.name, "sales_order", so.name, update_modified=False)
	return {"sales_order": so.name, "boq": doc.name, "grand_total": flt(so.grand_total)}


@frappe.whitelist()
def sales_order_to_progress_invoice(sales_order, billing_percentage=100, posting_date=None):
	from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

	so = frappe.get_doc("Sales Order", sales_order)
	so.check_permission("read")
	if not frappe.has_permission("Sales Invoice", "create"):
		frappe.throw(_("You are not permitted to create a Sales Invoice."), frappe.PermissionError)
	if so.docstatus != 1:
		frappe.throw(_("Submit the Sales Order before creating a progress invoice."))
	percentage = flt(billing_percentage)
	if percentage <= 0 or percentage > 100:
		frappe.throw(_("Billing Percentage must be greater than 0 and no more than 100."))

	si = make_sales_invoice(so.name, ignore_permissions=True)
	if not si.items:
		frappe.throw(_("The Sales Order has no remaining amount to invoice."))
	so_items = {row.name: row for row in so.items}
	for row in si.items:
		source = so_items.get(row.so_detail)
		if not source:
			continue
		remaining_qty = flt(row.qty)
		target_qty = flt(source.qty) * percentage / 100
		row.qty = min(target_qty, remaining_qty)
		row.amount = flt(row.qty) * flt(row.rate)
		row.project = so.project
	si.project = so.project
	si.flags.ignore_permissions = True
	si.set_missing_values()
	si.posting_date = posting_date or nowdate()
	si.set_posting_time = 1
	si.due_date = si.posting_date
	si.calculate_taxes_and_totals()
	si.insert()
	return {
		"sales_invoice": si.name,
		"sales_order": so.name,
		"billing_percentage": percentage,
		"grand_total": flt(si.grand_total),
	}

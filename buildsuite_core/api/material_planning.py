"""Approved BOQ material requirements using ERPNext Item/BOM mappings."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, nowdate


def require_approved_boq(boq):
	doc = frappe.get_doc("BOQ", boq)
	doc.check_permission("read")
	if doc.status != "Approved":
		frappe.throw(_("Material requirements can only be generated from an Approved BOQ."))
	return doc


def add_requirement(requirements, item_code, supply_method, qty, uom, source, rate=0):
	key = (item_code, supply_method, uom)
	row = requirements[key]
	row.update(
		{
			"item_code": item_code,
			"item_name": frappe.db.get_value("Item", item_code, "item_name") or item_code,
			"supply_method": supply_method,
			"uom": uom,
			"estimated_rate": flt(rate),
		}
	)
	row["qty"] += flt(qty)
	row["sources"].append(source)


def explode_manufactured_item(requirements, item_code, finished_qty, source):
	bom = frappe.db.get_value(
		"BOM",
		{"item": item_code, "is_active": 1, "is_default": 1, "docstatus": 1},
		["name", "quantity"],
		as_dict=True,
	)
	if not bom:
		return None
	for component in frappe.get_all(
		"BOM Item", filters={"parent": bom.name}, fields=["item_code", "qty", "uom", "rate"]
	):
		required_qty = flt(component.qty) * flt(finished_qty) / (flt(bom.quantity) or 1)
		add_requirement(
			requirements,
			component.item_code,
			"Purchase",
			required_qty,
			component.uom,
			f"{source} / BOM {bom.name}",
			component.rate,
		)
	return bom.name


@frappe.whitelist()
def get_material_requirements(boq):
	doc = require_approved_boq(boq)
	requirements = defaultdict(lambda: {"qty": 0.0, "sources": []})
	for row in frappe.get_all(
		"BOQ Sub Item",
		filters={"boq": doc.name, "rate_master": ["is", "set"]},
		fields=["name", "boq_item", "rate_master", "description", "qty", "uom", "rate"],
	):
		resource = frappe.db.get_value(
			"Construction Rate Master",
			row.rate_master,
			["category", "item_code", "supply_method", "uom", "current_rate"],
			as_dict=True,
		)
		if not resource or resource.supply_method == "Non-stock" or not resource.item_code:
			continue
		add_requirement(
			requirements,
			resource.item_code,
			resource.supply_method,
			row.qty,
			resource.uom or row.uom,
			f"BOQ Sub Item {row.name}",
			resource.current_rate or row.rate,
		)
		if resource.supply_method == "Manufacture":
			explode_manufactured_item(requirements, resource.item_code, row.qty, f"BOQ Sub Item {row.name}")

	rows = sorted(requirements.values(), key=lambda row: (row["supply_method"], row["item_code"]))
	for row in rows:
		row["estimated_amount"] = flt(row["qty"]) * flt(row["estimated_rate"])
	return {"boq": doc.name, "project": doc.project, "company": doc.company, "requirements": rows}


@frappe.whitelist()
def create_material_request(boq, supply_method="Purchase", schedule_date=None, warehouse=None):
	if supply_method not in ("Purchase", "Manufacture"):
		frappe.throw(_("Supply Method must be Purchase or Manufacture."))
	if not frappe.has_permission("Material Request", "create"):
		frappe.throw(_("You are not permitted to create a Material Request."), frappe.PermissionError)

	plan = get_material_requirements(boq)
	request_type = "Purchase" if supply_method == "Purchase" else "Manufacture"
	existing = frappe.db.get_value(
		"Material Request",
		{
			"custom_buildsuite_boq": boq,
			"material_request_type": request_type,
			"docstatus": ["<", 2],
		},
		"name",
		order_by="creation desc",
	)
	if existing:
		return {"material_request": existing, "already_created": True}

	items = [row for row in plan["requirements"] if row["supply_method"] == supply_method]
	if not items:
		frappe.throw(_("No {0} requirements were found in this BOQ.").format(supply_method))
	if not warehouse:
		warehouse = frappe.db.get_value(
			"Warehouse",
			{"project": plan["project"], "company": plan["company"], "is_group": 0},
			"name",
			order_by="creation desc",
		)
	if not warehouse:
		warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")

	mr = frappe.new_doc("Material Request")
	mr.company = plan["company"]
	mr.project = plan["project"]
	mr.custom_buildsuite_boq = boq
	mr.material_request_type = request_type
	mr.transaction_date = schedule_date or nowdate()
	mr.schedule_date = schedule_date or mr.transaction_date
	for row in items:
		mr.append(
			"items",
			{
				"item_code": row["item_code"],
				"qty": row["qty"],
				"uom": row["uom"],
				"schedule_date": schedule_date or mr.transaction_date,
				"warehouse": warehouse,
				"project": plan["project"],
			},
		)
	mr.flags.ignore_permissions = True
	mr.set_missing_values()
	mr.insert()
	return {"material_request": mr.name, "supply_method": supply_method, "item_count": len(mr.items)}

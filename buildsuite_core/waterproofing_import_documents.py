"""Document builders for the exact workbook-cost waterproofing import."""

from decimal import Decimal

import frappe
from frappe.utils import flt

from buildsuite_core.api import boq as boq_api
from buildsuite_core.waterproofing_import import COMPANY, CUSTOMER, PROJECT_ID, PROJECT_NAME

ASSEMBLY = "ASM-WB-WATERPROOFING-3MM"
TEMPLATE = "TPL-WB-WATERPROOFING-3MM"
ITEM = "BS-WB-WATERPROOFING-3MM"
BOQ_TITLE = "Waterproofing Consumption Sheet — Workbook Estimate"
WP_CODE = "WP-WATERPROOFING"
SELECTED = (
	("WB-PRI-SF-PRIMER", Decimal("0.25")),
	("WB-FIL-FUMED-SILICA", Decimal("0.2")),
	("WB-POL-AQUALINE-AL", Decimal("3") / Decimal("1.1")),
	("WB-LAB-SUPERVISOR", Decimal("0.1")),
	("WB-LAB-SPRAYER", Decimal("0.1")),
	("WB-LAB-WALL-PAINTER", Decimal("0.1")),
	("WB-LAB-HELPER", Decimal("0.2")),
)


def create_project(data):
	return frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": PROJECT_NAME,
			"custom_project_id": PROJECT_ID,
			"company": COMPANY,
			"customer": CUSTOMER,
			"project_status": "New",
			"status": "Open",
			"project_type": "External",
			"project_category": "Other",
			"location": data.location,
			"expected_start_date": data.start_date,
			"estimated_costing": float(data.values["cost"]),
			"custom_seed_default_stages": 0,
			"custom_seed_default_tasks": 0,
			"custom_seed_default_work_packages": 0,
			"notes": (
				f"Workbook estimate: {data.values['area']} m², {data.values['thickness']} mm, "
				f"{data.values['man_days']} man-days. Source customer {data.customer!r} mapped to {CUSTOMER}. "
				f"Workbook SHA-256: {data.checksum}."
			),
		}
	).insert(ignore_permissions=True)


def create_work_package(project, data):
	return frappe.get_doc(
		{
			"doctype": "Work Package",
			"project": project,
			"code": WP_CODE,
			"work_package_name": "Waterproofing Works",
			"status": "Planned",
			"start_date": data.start_date,
			"budget": float(data.values["cost"]),
			"description": f"Planning package imported from workbook {data.checksum}.",
		}
	).insert(ignore_permissions=True)


def create_rates(data, rows=None):
	created = []
	for row in rows or data.rates:
		note = f"Workbook row {row.source_row}. {row.source_notes}. Coverage/input: {row.coverage}. SHA-256: {data.checksum}."
		doc = frappe.get_doc(
			{
				"doctype": "Construction Rate Master",
				"rate_code": row.code,
				"rate_name": row.name,
				"category": row.category,
				"uom": row.uom,
				"current_rate": float(row.rate),
				"supply_method": "Non-stock",
				"notes": note,
			}
		).insert(ignore_permissions=True)
		created.append(doc.name)
	return created


def create_assembly(data):
	doc = frappe.get_doc(
		{
			"doctype": "Assembly",
			"assembly_code": ASSEMBLY,
			"assembly_name": "Workbook Aqualine AL Waterproofing — 3 mm",
			"category": "General" if frappe.db.exists("Assembly Category", "General") else None,
			"uom": "Square Meter",
			"notes": f"Exact reciprocal Aqualine calculation from workbook {data.checksum}.",
		}
	)
	for resource, coefficient in SELECTED:
		doc.append(
			"components",
			{
				"resource": resource,
				"coefficient": float(coefficient),
				"remarks": "Workbook-selected direct cost",
			},
		)
	return doc.insert(ignore_permissions=True)


def create_template(data):
	return frappe.get_doc(
		{
			"doctype": "Estimate Template",
			"template_code": TEMPLATE,
			"template_name": "Workbook Waterproofing Estimate — 3 mm",
			"description": f"Workbook-specific template; SHA-256 {data.checksum}.",
			"project_category": "Other",
			"enabled": 1,
			"groups": [{"group_name": "Direct Waterproofing"}],
			"rows": [
				{
					"group_name": "Direct Waterproofing",
					"line_type": "Assembly",
					"assembly": ASSEMBLY,
					"description": "Seven workbook-selected direct-cost resources",
					"placeholder_qty": float(data.values["area"]),
					"cost_head": "Material",
				}
			],
		}
	).insert(ignore_permissions=True)


def create_service_item():
	group = frappe.db.get_value("Item Group", {"name": "Services", "is_group": 0}, "name")
	if not group:
		group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	return frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": ITEM,
			"item_name": "Waterproofing Service — 3 mm",
			"item_group": group,
			"stock_uom": "Square Meter",
			"is_stock_item": 0,
			"is_sales_item": 1,
			"is_purchase_item": 0,
		}
	).insert(ignore_permissions=True)


def create_boq(project, work_package, data):
	margin = (data.values["selling"] - data.values["cost"]) / data.values["cost"] * 100
	boq = frappe.get_doc(
		{
			"doctype": "BOQ",
			"project": project,
			"title": BOQ_TITLE,
			"margin_rate": float(margin),
			"tax_rate": 0,
		}
	).insert(ignore_permissions=True)
	direct = frappe.get_doc(
		{
			"doctype": "BOQ Group",
			"boq": boq.name,
			"code": "A",
			"group_name": "Direct Waterproofing",
			"idx_order": 1,
		}
	).insert(ignore_permissions=True)
	item = frappe.get_doc(
		{
			"doctype": "BOQ Item",
			"boq": boq.name,
			"boq_group": direct.name,
			"code": "A1",
			"description": "Aqualine AL waterproofing system at 3 mm",
			"unit": "Square Meter",
			"planned_qty": float(data.values["area"]),
			"quantity_source": "Assembly",
			"assembly": ASSEMBLY,
			"work_package": work_package,
			"cost_head": "Material",
		}
	).insert(ignore_permissions=True)
	boq_api.explode_item(item.name)
	allowances = frappe.get_doc(
		{"doctype": "BOQ Group", "boq": boq.name, "code": "B", "group_name": "Allowances", "idx_order": 2}
	).insert(ignore_permissions=True)
	for code, description, key, cost_head in (
		("B1", "Indirect cost allowance (18% of direct cost)", "indirect", "Preliminaries"),
		("B2", "Consumables allowance (6% of direct cost)", "consumables", "Other"),
		("B3", "Warranty 15 Years (10% of material cost)", "warranty", "Other"),
	):
		frappe.get_doc(
			{
				"doctype": "BOQ Item",
				"boq": boq.name,
				"boq_group": allowances.name,
				"code": code,
				"description": description,
				"unit": "Nos",
				"planned_qty": 1,
				"rate": float(data.values[key]),
				"quantity_source": "Manual",
				"work_package": work_package,
				"cost_head": cost_head,
			}
		).insert(ignore_permissions=True)
	boq.reload()
	boq.save(ignore_permissions=True)
	return boq


def create_sales_order(project, boq, data):
	so = frappe.new_doc("Sales Order")
	so.company = COMPANY
	so.customer = CUSTOMER
	so.project = project
	so.custom_buildsuite_boq = boq
	so.transaction_date = data.start_date
	so.delivery_date = data.start_date
	so.currency = "AED"
	so.append(
		"items",
		{
			"item_code": ITEM,
			"description": "Aqualine AL waterproofing system at 3 mm",
			"qty": float(data.values["area"]),
			"uom": "Square Meter",
			"rate": 272,
			"project": project,
		},
	)
	so.flags.ignore_permissions = True
	so.set_missing_values()
	so.calculate_taxes_and_totals()
	so.insert()
	frappe.db.set_value("BOQ", boq, "sales_order", so.name, update_modified=False)
	return so


def close_enough(actual, expected, tolerance=0.02):
	return abs(flt(actual) - flt(expected)) <= tolerance

"""Idempotent Waterproofing Consumption Sheet masters and guarded UAT lifecycle.

The workbook is intentionally normalised into one named scenario.  This is not a generic
spreadsheet importer and never deletes or rebuilds submitted business documents.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import frappe
from frappe import _
from frappe.utils import flt

from buildsuite_core.api import boq as boq_api

COMPANY = "Deltachem Middle East LLC"
CUSTOMER = "Desert Leisure Swimming Pools LLC"
PROJECT_NAME = "Sobha Hartland II Mansion Lagoon"
PROJECT_CODE = "BS-WP-UAT-001"
PRODUCTION_PROJECT_CODE = "BS-WP-001"
START_DATE = "2026-04-06"
AREA = 318.0
THICKNESS = 3.0
AQUALINE_QTY = 1049.4
PART_QTY = 524.7
SUBCONTRACT_ADVANCE = 693.20
SALES_TAX_TEMPLATE = "UAE VAT 5% - DCI"
PURCHASE_TAX_TEMPLATE = "UAE VAT 5% - DCI"
RETENTION_RECEIVABLE = "Project Retention - DCI"
RETENTION_PAYABLE = "Retention Payable - DCI"
BANK_ACCOUNT = "023471366196 - NBF Islamic (AED) - DCI"
SOURCE_WAREHOUSE = "BuildSuite UAT Raw - DCI"
WIP_WAREHOUSE = "BuildSuite UAT WIP - DCI"
FINISHED_WAREHOUSE = "BuildSuite UAT Finished - DCI"
PROJECT_WAREHOUSE = "BuildSuite UAT Sobha Lagoon - DCI"
MATERIAL_SUPPLIER = "BuildSuite Waterproofing Materials UAT"
SUBCONTRACTOR = "BuildSuite Waterproofing Subcontractor UAT"
WORKBOOK = "/Users/samarthupare/pampa-bench/Waterproofing_Consumption Sheet.xlsx"

ITEMS = {
	"primer": "BS-WP-SF-PRIMER",
	"silica": "BS-WP-FUMED-SILICA",
	"part_a": "Part A - DELTAShield Aqualine AL",
	"part_b": "Part B - DELTAShield Aqualine AL",
	"aqualine": "BS-WP-AQUALINE-AL",
	"contract": "BS-WP-WATERPROOFING-3MM",
}

RATES = {
	"WP-SF-PRIMER": ("SF Primer", "Material", "Litre", 18.0, ITEMS["primer"], "Purchase", 0.25),
	"WP-FUMED-SILICA": ("Fumed Silica", "Material", "Kgs", 28.0, ITEMS["silica"], "Purchase", 0.20),
	"WP-AQUALINE-AL": ("Aqualine AL", "Material", "Kgs", 50.0, ITEMS["aqualine"], "Manufacture", 3.30),
	"WP-SUPERVISOR": ("Supervisor", "Labour", "Hour", 35.0, None, "Non-stock", 0.10),
	"WP-SPRAYER": ("Sprayer", "Labour", "Hour", 25.0, None, "Non-stock", 0.10),
	"WP-WALL-PAINTER": ("Wall Painter", "Labour", "Hour", 17.0, None, "Non-stock", 0.10),
	"WP-HELPER": ("Helper", "Labour", "Hour", 16.0, None, "Non-stock", 0.20),
}

EXPECTED = {
	"materials": 55681.80,
	"labour": 3466.20,
	"direct_cost": 59148.00,
	"indirect": 10646.64,
	"consumables": 3548.88,
	"warranty": 5568.18,
	"total_cost": 78911.70,
	"lpo_before_vat": 86496.00,
	"vat": 4324.80,
	"contract_total": 90820.80,
}


def _assert_close(label, actual, expected, tolerance=0.02):
	if abs(flt(actual) - flt(expected)) > tolerance:
		frappe.throw(_("{0}: expected {1}, got {2}").format(label, expected, actual))


def _ensure_uom(name):
	if not frappe.db.exists("UOM", name):
		frappe.get_doc({"doctype": "UOM", "uom_name": name}).insert(ignore_permissions=True)


def _ensure_item(code, name, uom, *, stock=True, item_group="Materials", manufactured=False):
	if frappe.db.exists("Item", code):
		existing = frappe.db.get_value("Item", code, ["stock_uom", "is_stock_item", "disabled"], as_dict=True)
		if existing.disabled or existing.stock_uom != uom or bool(existing.is_stock_item) != bool(stock):
			frappe.throw(_("Existing Item {0} is incompatible with the waterproofing scenario.").format(code))
		return code
	doc = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": code,
			"item_name": name,
			"item_group": item_group,
			"stock_uom": uom,
			"is_stock_item": 1 if stock else 0,
			"is_purchase_item": 0 if manufactured or not stock else 1,
			"is_sales_item": 0 if stock else 1,
			"is_manufactured_item": 1 if manufactured else 0,
		}
	)
	doc.insert(ignore_permissions=True)
	return code


def _ensure_supplier(name, supplier_group):
	if frappe.db.exists("Supplier", name):
		if (
			supplier_group == "Subcontractor"
			and frappe.db.get_value("Supplier", name, "supplier_type") != "Subcontractor"
		):
			frappe.db.set_value("Supplier", name, "supplier_type", "Subcontractor")
		return name
	return (
		frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": name,
				"supplier_group": supplier_group,
				"supplier_type": "Subcontractor" if supplier_group == "Subcontractor" else "Company",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_warehouse(warehouse_name, *, project=None):
	company_abbr = frappe.db.get_value("Company", COMPANY, "abbr")
	name = f"{warehouse_name} - {company_abbr}"
	if frappe.db.exists("Warehouse", name):
		doc = frappe.get_doc("Warehouse", name)
		if doc.disabled:
			frappe.throw(_("Scenario warehouse {0} is disabled.").format(name))
		if project and doc.project != project:
			doc.project = project
			doc.save(ignore_permissions=True)
		return doc.name
	doc = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": warehouse_name,
			"company": COMPANY,
			"parent_warehouse": f"All Warehouses - {company_abbr}",
			"is_group": 0,
			"project": project,
		}
	).insert(ignore_permissions=True)
	return doc.name


def _ensure_batch(item_code):
	"""Return the stable scenario batch when the selected component is batch-controlled."""
	if not frappe.db.get_value("Item", item_code, "has_batch_no"):
		return None
	batch_id = f"BS-WP-UAT-{frappe.scrub(item_code).upper().replace('_', '-')[:80]}"
	if not frappe.db.exists("Batch", batch_id):
		frappe.get_doc(
			{
				"doctype": "Batch",
				"batch_id": batch_id,
				"item": item_code,
				"manufacturing_date": START_DATE,
				"description": "BuildSuite waterproofing UAT lifecycle batch",
			}
		).insert(ignore_permissions=True)
	return batch_id


def _set_component_batches(doc):
	"""Populate ERPNext's standard legacy batch input before it builds bundle records."""
	for row in doc.items:
		batch_no = _ensure_batch(row.item_code)
		if batch_no:
			row.batch_no = batch_no
			row.use_serial_batch_fields = 1


def _ensure_tax_template(doctype, child_doctype, name):
	if frappe.db.exists(doctype, name):
		if frappe.db.get_value(doctype, name, "company") != COMPANY:
			frappe.throw(_("Tax template {0} belongs to another company.").format(name))
		return name
	doc = frappe.get_doc(
		{
			"doctype": doctype,
			"title": "UAE VAT 5%",
			"company": COMPANY,
			"disabled": 0,
			"taxes": [
				{
					"doctype": child_doctype,
					"charge_type": "On Net Total",
					"account_head": "VAT 5% - DCI",
					"description": "UAE VAT 5%",
					"rate": 5,
				}
			],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_rate(code, values):
	name, category, uom, rate, item_code, supply_method, _coefficient = values
	if frappe.db.exists("Construction Rate Master", code):
		doc = frappe.get_doc("Construction Rate Master", code)
	else:
		doc = frappe.new_doc("Construction Rate Master")
		doc.rate_code = code
	doc.rate_name = name
	doc.category = category
	doc.uom = uom
	doc.current_rate = rate
	doc.item_code = item_code
	doc.supply_method = supply_method
	doc.save(ignore_permissions=True)
	return doc.name


def _ensure_assembly():
	code = "ASM-WATERPROOFING-3MM"
	if frappe.db.exists("Assembly", code):
		return frappe.get_doc("Assembly", code)
	doc = frappe.get_doc(
		{
			"doctype": "Assembly",
			"assembly_code": code,
			"assembly_name": "Waterproofing Assembly — Aqualine AL 3 mm",
			"category": "General" if frappe.db.exists("Assembly Category", "General") else None,
			"uom": "Square Meter",
			"notes": "Normalised from the Waterproofing Consumption Sheet for 318 m² at 3 mm.",
		}
	)
	for rate_code, values in RATES.items():
		doc.append(
			"components",
			{
				"resource": rate_code,
				"resource_name": values[0],
				"coefficient": values[6],
				"uom": values[2],
			},
		)
	doc.insert(ignore_permissions=True)
	_assert_close("Waterproofing assembly rate", doc.rate_per_unit, 186.0)
	return doc


def _ensure_estimate_template():
	code = "TPL-WATERPROOFING-AQUALINE-3MM"
	if frappe.db.exists("Estimate Template", code):
		return code
	doc = frappe.get_doc(
		{
			"doctype": "Estimate Template",
			"template_code": code,
			"template_name": "Aqualine AL Waterproofing — 3 mm",
			"description": "318 m² waterproofing lifecycle normalised from the supplied workbook.",
			"enabled": 1,
			"rows": [
				{
					"group_name": "Direct Waterproofing",
					"line_type": "Assembly",
					"assembly": "ASM-WATERPROOFING-3MM",
					"description": "Aqualine AL waterproofing system at 3 mm",
					"placeholder_qty": AREA,
					"uom": "Square Meter",
					"cost_head": "Material",
				}
			],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_bom():
	existing = frappe.db.get_value("BOM", {"item": ITEMS["aqualine"], "docstatus": 1, "is_active": 1}, "name")
	if existing:
		bom = frappe.get_doc("BOM", existing)
		parts = {row.item_code: flt(row.qty) for row in bom.items}
		_assert_close("Aqualine BOM Part A", parts.get(ITEMS["part_a"]), 0.5, 0.0001)
		_assert_close("Aqualine BOM Part B", parts.get(ITEMS["part_b"]), 0.5, 0.0001)
		return bom
	bom = frappe.get_doc(
		{
			"doctype": "BOM",
			"company": COMPANY,
			"item": ITEMS["aqualine"],
			"quantity": 1,
			"is_active": 1,
			"is_default": 1,
			"items": [
				{"item_code": ITEMS["part_a"], "qty": 0.5, "uom": "Kgs"},
				{"item_code": ITEMS["part_b"], "qty": 0.5, "uom": "Kgs"},
			],
		}
	)
	bom.insert(ignore_permissions=True)
	bom.submit()
	return bom


def _workbook_checksum():
	path = Path(WORKBOOK)
	return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@frappe.whitelist()
def setup_waterproofing_masters():
	"""Create reusable non-transactional masters and company finance defaults."""
	frappe.only_for("System Manager")
	if not frappe.db.exists("Company", COMPANY):
		frappe.throw(_("Company {0} does not exist").format(COMPANY))
	if not frappe.db.exists("Customer", CUSTOMER):
		frappe.throw(_("Customer {0} does not exist").format(CUSTOMER))
	for account in (RETENTION_RECEIVABLE, RETENTION_PAYABLE, BANK_ACCOUNT, "VAT 5% - DCI"):
		account_details = frappe.db.get_value(
			"Account", account, ["company", "is_group", "disabled"], as_dict=True
		)
		if (
			not account_details
			or account_details.company != COMPANY
			or account_details.is_group
			or account_details.disabled
		):
			frappe.throw(_("Account {0} is not an active ledger for {1}.").format(account, COMPANY))
	for uom in ("Litre", "Kgs", "Hour", "Square Meter", "Nos"):
		_ensure_uom(uom)

	frappe.db.set_value(
		"Company",
		COMPANY,
		{
			"default_retention_receivable_account": RETENTION_RECEIVABLE,
			"default_retention_payable_account": RETENTION_PAYABLE,
		},
	)
	_ensure_tax_template("Sales Taxes and Charges Template", "Sales Taxes and Charges", SALES_TAX_TEMPLATE)
	_ensure_tax_template(
		"Purchase Taxes and Charges Template", "Purchase Taxes and Charges", PURCHASE_TAX_TEMPLATE
	)

	_ensure_item(ITEMS["primer"], "SF Primer", "Litre")
	_ensure_item(ITEMS["silica"], "Fumed Silica", "Kgs")
	for component in (ITEMS["part_a"], ITEMS["part_b"]):
		if not frappe.db.exists("Item", component):
			_ensure_item(component, component, "Kgs")
	_ensure_item(
		ITEMS["aqualine"],
		"DELTAShield Aqualine AL",
		"Kgs",
		item_group="Finished Goods",
		manufactured=True,
	)
	_ensure_item(
		ITEMS["contract"],
		"Aqualine AL Waterproofing 3 mm",
		"Square Meter",
		stock=False,
		item_group="Services",
	)
	_ensure_supplier(MATERIAL_SUPPLIER, "Raw Material")
	_ensure_supplier(SUBCONTRACTOR, "Subcontractor")
	for code, values in RATES.items():
		_ensure_rate(code, values)
	assembly = _ensure_assembly()
	template = _ensure_estimate_template()
	bom = _ensure_bom()

	materials = AREA * sum(v[3] * v[6] for v in RATES.values() if v[1] == "Material")
	labour = AREA * sum(v[3] * v[6] for v in RATES.values() if v[1] == "Labour")
	_assert_close("Materials", materials, EXPECTED["materials"])
	_assert_close("Labour", labour, EXPECTED["labour"])
	_assert_close("Aqualine formula", AREA * THICKNESS * 1.1, AQUALINE_QTY, 0.0001)

	return {
		"company": COMPANY,
		"customer": CUSTOMER,
		"assembly": assembly.name,
		"assembly_rate": flt(assembly.rate_per_unit),
		"estimate_template": template,
		"bom": bom.name,
		"items": ITEMS,
		"workbook_sha256": _workbook_checksum(),
		"expected": EXPECTED,
	}


def _project_status(*, uat):
	return "Ongoing" if uat else "New"


def _ensure_project(*, uat=True):
	project_code = PROJECT_CODE if uat else PRODUCTION_PROJECT_CODE
	name = frappe.db.get_value("Project", {"custom_project_id": project_code}, "name")
	if not name:
		name = frappe.db.get_value("Project", {"project_name": PROJECT_NAME}, "name")
	if name:
		doc = frappe.get_doc("Project", name)
		if doc.company != COMPANY or (doc.customer and doc.customer != CUSTOMER):
			frappe.throw(
				_("Existing Project {0} does not match the waterproofing company/customer.").format(name)
			)
		return doc
	doc = frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": PROJECT_NAME,
			"custom_project_id": project_code,
			"company": COMPANY,
			"customer": CUSTOMER,
			"project_status": _project_status(uat=uat),
			"status": "Open",
			"expected_start_date": START_DATE,
			"expected_end_date": "2026-08-31",
			"estimated_costing": EXPECTED["total_cost"],
			"enable_retention": 1,
			"retention_percentage": 10,
			"retention_release_after_days": 90,
			"enable_advance_recovery": 1,
			"advance_recovery_percentage": 20,
			"notes": (
				"UAT lifecycle generated from the Waterproofing Consumption Sheet."
				if uat
				else "Draft project generated from the Waterproofing Consumption Sheet; transactions require business approval."
			),
		}
	)
	doc.insert(ignore_permissions=True)
	if uat:
		_ensure_warehouse("BuildSuite UAT Sobha Lagoon", project=doc.name)
	return doc


def _ensure_boq(project, *, approve=True):
	name = frappe.db.get_value(
		"BOQ", {"project": project.name, "title": "Waterproofing Consumption Sheet — 3 mm"}, "name"
	)
	if name:
		doc = frappe.get_doc("BOQ", name)
		_assert_boq(doc)
		if approve and doc.status == "Draft":
			boq_api.submit_boq(doc.name)
			boq_api.approve_boq(doc.name)
		return frappe.get_doc("BOQ", name)
	margin_rate = (EXPECTED["lpo_before_vat"] - EXPECTED["total_cost"]) / EXPECTED["total_cost"] * 100
	doc = frappe.get_doc(
		{
			"doctype": "BOQ",
			"project": project.name,
			"company": COMPANY,
			"title": "Waterproofing Consumption Sheet — 3 mm",
			"margin_rate": margin_rate,
			"tax_rate": 5,
		}
	).insert(ignore_permissions=True)
	boq_api.import_template(doc.name, "TPL-WATERPROOFING-AQUALINE-3MM")
	allowances = [
		("A2", "Indirect cost allowance (18% of direct cost)", EXPECTED["indirect"], "Preliminaries"),
		("A3", "Consumables allowance (6% of direct cost)", EXPECTED["consumables"], "Other"),
		("A4", "Material warranty provision (10% of material cost)", EXPECTED["warranty"], "Other"),
	]
	group = frappe.db.get_value("BOQ Group", {"boq": doc.name, "group_name": "Allowances"}, "name")
	if not group:
		group = (
			frappe.get_doc(
				{
					"doctype": "BOQ Group",
					"boq": doc.name,
					"code": "B",
					"group_name": "Allowances",
					"idx_order": 2,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	for code, description, amount, cost_head in allowances:
		frappe.get_doc(
			{
				"doctype": "BOQ Item",
				"boq": doc.name,
				"boq_group": group,
				"code": code,
				"description": description,
				"unit": "Nos",
				"planned_qty": 1,
				"rate": amount,
				"quantity_source": "Manual",
				"cost_head": cost_head,
			}
		).insert(ignore_permissions=True)
	doc.reload()
	doc.save(ignore_permissions=True)
	_assert_boq(doc)
	if approve:
		boq_api.submit_boq(doc.name)
		boq_api.approve_boq(doc.name)
	return frappe.get_doc("BOQ", doc.name)


def _assert_boq(doc):
	_assert_close("Direct cost", EXPECTED["direct_cost"], EXPECTED["materials"] + EXPECTED["labour"])
	_assert_close("BOQ total cost", doc.planned_amount, EXPECTED["total_cost"])
	_assert_close("BOQ margin", doc.planned_amount + doc.margin_amount, EXPECTED["lpo_before_vat"])
	_assert_close("BOQ VAT", doc.tax_amount, EXPECTED["vat"])
	_assert_close("BOQ contract total", doc.total, EXPECTED["contract_total"])


def _ensure_sales_order(boq, project):
	from buildsuite_core.api.contract import boq_to_sales_order

	result = boq_to_sales_order(
		boq.name,
		frappe.as_json(
			{
				"customer": CUSTOMER,
				"transaction_date": START_DATE,
				"delivery_date": "2026-08-31",
				"taxes_and_charges": SALES_TAX_TEMPLATE,
				"items": [
					{
						"item_code": ITEMS["contract"],
						"description": "Aqualine AL waterproofing system at 3 mm",
						"qty": AREA,
						"uom": "Square Meter",
						"rate": 272,
					}
				],
			}
		),
	)
	so = frappe.get_doc("Sales Order", result["sales_order"])
	if so.docstatus == 0:
		so.submit()
	_assert_close("Sales Order total", so.grand_total, EXPECTED["contract_total"])
	return so


def _ensure_draft_sales_order(boq, project):
	name = frappe.db.get_value("Sales Order", {"custom_buildsuite_boq": boq.name, "docstatus": 0}, "name")
	if name:
		return frappe.get_doc("Sales Order", name)

	so = frappe.new_doc("Sales Order")
	so.company = COMPANY
	so.customer = CUSTOMER
	so.project = project.name
	so.custom_buildsuite_boq = boq.name
	so.transaction_date = START_DATE
	so.delivery_date = "2026-08-31"
	so.currency = frappe.db.get_value("Company", COMPANY, "default_currency")
	so.append(
		"items",
		{
			"item_code": ITEMS["contract"],
			"description": "Aqualine AL waterproofing system at 3 mm",
			"qty": AREA,
			"uom": "Square Meter",
			"rate": 272,
			"project": project.name,
		},
	)
	_set_tax_template(so, SALES_TAX_TEMPLATE)
	so.flags.ignore_permissions = True
	so.set_missing_values()
	so.calculate_taxes_and_totals()
	so.insert()
	frappe.db.set_value("BOQ", boq.name, "sales_order", so.name, update_modified=False)
	_assert_close("Draft Sales Order total", so.grand_total, EXPECTED["contract_total"])
	return so


def _ensure_material_requests(boq):
	from buildsuite_core.api.material_planning import create_material_request, get_material_requirements

	plan = get_material_requirements(boq.name)
	by_item = {row["item_code"]: row for row in plan["requirements"]}
	for item, qty in (
		(ITEMS["primer"], 79.5),
		(ITEMS["silica"], 63.6),
		(ITEMS["part_a"], PART_QTY),
		(ITEMS["part_b"], PART_QTY),
		(ITEMS["aqualine"], AQUALINE_QTY),
	):
		_assert_close(f"Material requirement {item}", by_item[item]["qty"], qty, 0.001)
	out = {}
	for method in ("Purchase", "Manufacture"):
		result = create_material_request(boq.name, method, START_DATE, SOURCE_WAREHOUSE)
		doc = frappe.get_doc("Material Request", result["material_request"])
		if doc.docstatus == 0:
			doc.submit()
		out[method.lower()] = doc
	return out


def _set_tax_template(doc, template):
	doc.taxes_and_charges = template
	doc.set("taxes", [])
	template_doc = frappe.get_doc(doc.meta.get_field("taxes_and_charges").options, template)
	for row in template_doc.taxes:
		doc.append(
			"taxes",
			{
				"charge_type": row.charge_type,
				"account_head": row.account_head,
				"description": row.description,
				"rate": row.rate,
				"category": row.get("category") or "Total",
				"add_deduct_tax": row.get("add_deduct_tax") or "Add",
			},
		)


def _ensure_procurement(purchase_mr, project):
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
	from erpnext.stock.doctype.material_request.material_request import make_purchase_order
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

	from buildsuite_core.api.supplier_bill import record_payment

	po_name = frappe.db.get_value(
		"Purchase Order Item", {"material_request": purchase_mr.name, "docstatus": ["<", 2]}, "parent"
	)
	if po_name:
		po = frappe.get_doc("Purchase Order", po_name)
	else:
		po = make_purchase_order(purchase_mr.name)
		po.supplier = MATERIAL_SUPPLIER
		po.project = project.name
		po.transaction_date = START_DATE
		po.schedule_date = START_DATE
		rates = {ITEMS["primer"]: 18, ITEMS["silica"]: 28, ITEMS["part_a"]: 27.75, ITEMS["part_b"]: 16.82}
		for row in po.items:
			row.rate = rates[row.item_code]
			row.warehouse = SOURCE_WAREHOUSE
			row.project = project.name
		_set_tax_template(po, PURCHASE_TAX_TEMPLATE)
		po.set_missing_values()
		po.calculate_taxes_and_totals()
		po.insert(ignore_permissions=True)
	if po.docstatus == 0:
		po.submit()

	pr_name = frappe.db.get_value(
		"Purchase Receipt Item", {"purchase_order": po.name, "docstatus": ["<", 2]}, "parent"
	)
	if pr_name:
		pr = frappe.get_doc("Purchase Receipt", pr_name)
	else:
		pr = make_purchase_receipt(po.name)
		pr.posting_date = START_DATE
		pr.project = project.name
		_set_component_batches(pr)
		pr.insert(ignore_permissions=True)
	if pr.docstatus == 0:
		pr.submit()

	pi_name = frappe.db.get_value(
		"Purchase Invoice Item", {"purchase_receipt": pr.name, "docstatus": ["<", 2]}, "parent"
	)
	if pi_name:
		pi = frappe.get_doc("Purchase Invoice", pi_name)
	else:
		pi = make_purchase_invoice(pr.name)
		pi.posting_date = START_DATE
		pi.bill_no = "BS-WP-UAT-MAT-001"
		pi.bill_date = START_DATE
		# Material procurement is project-traceable through its PO/PR/item rows, but
		# it is not a subcontract progress bill and must not inherit contract retention.
		pi.project = None
		pi.insert(ignore_permissions=True)
	if pi.docstatus == 0:
		pi.submit()
	if flt(pi.outstanding_amount) > 0.01:
		record_payment(
			pi.name, pi.outstanding_amount, START_DATE, "Wire Transfer", BANK_ACCOUNT, "BS-WP-UAT-MATERIALS"
		)
	pi.reload()
	if flt(pi.retention_outstanding_amount) > 0.01:
		# Correct an earlier idempotent seed without cancelling or rebuilding its
		# submitted invoice. New seeds never enter this branch.
		_ensure_retention_release("Purchase Invoice", pi.name)
		_pay_invoice("Purchase Invoice", pi.name, "BS-WP-UAT-MAT-RET")
	return {
		"material_request": purchase_mr.name,
		"purchase_order": po.name,
		"purchase_receipt": pr.name,
		"purchase_invoice": pi.name,
	}


def _ensure_manufacturing(bom, project):
	from buildsuite_core.api.manufacturing import (
		create_project_transfer,
		create_work_order,
		create_work_order_stock_entry,
	)

	work_order = frappe.db.get_value(
		"Work Order", {"project": project.name, "bom_no": bom.name, "docstatus": ["<", 2]}, "name"
	)
	if work_order:
		wo = frappe.get_doc("Work Order", work_order)
	else:
		result = create_work_order(
			bom.name, AQUALINE_QTY, project.name, COMPANY, SOURCE_WAREHOUSE, WIP_WAREHOUSE, FINISHED_WAREHOUSE
		)
		wo = frappe.get_doc("Work Order", result["work_order"])
		for row in wo.required_items:
			row.source_warehouse = SOURCE_WAREHOUSE
		wo.save(ignore_permissions=True)
	if wo.docstatus == 0:
		wo.submit()

	transfer = frappe.db.get_value(
		"Stock Entry",
		{"work_order": wo.name, "purpose": "Material Transfer for Manufacture", "docstatus": ["<", 2]},
		"name",
	)
	if not transfer:
		transfer = create_work_order_stock_entry(wo.name, "Material Transfer for Manufacture", AQUALINE_QTY)[
			"stock_entry"
		]
	transfer_doc = frappe.get_doc("Stock Entry", transfer)
	if transfer_doc.docstatus == 0:
		_set_component_batches(transfer_doc)
		transfer_doc.save(ignore_permissions=True)
		transfer_doc.submit()

	manufacture = frappe.db.get_value(
		"Stock Entry", {"work_order": wo.name, "purpose": "Manufacture", "docstatus": ["<", 2]}, "name"
	)
	if not manufacture:
		manufacture = create_work_order_stock_entry(wo.name, "Manufacture", AQUALINE_QTY)["stock_entry"]
	manufacture_doc = frappe.get_doc("Stock Entry", manufacture)
	if manufacture_doc.docstatus == 0:
		_set_component_batches(manufacture_doc)
		manufacture_doc.save(ignore_permissions=True)
		manufacture_doc.submit()

	project_warehouse = frappe.db.get_value("Warehouse", {"project": project.name, "is_group": 0}, "name")
	for source, items, marker in (
		(
			SOURCE_WAREHOUSE,
			[{"item_code": ITEMS["primer"], "qty": 79.5}, {"item_code": ITEMS["silica"], "qty": 63.6}],
			"BS-WP-UAT-DIRECT-TRANSFER",
		),
		(
			FINISHED_WAREHOUSE,
			[{"item_code": ITEMS["aqualine"], "qty": AQUALINE_QTY}],
			"BS-WP-UAT-FG-TRANSFER",
		),
	):
		name = frappe.db.get_value(
			"Stock Entry",
			{
				"project": project.name,
				"purpose": "Material Transfer",
				"remarks": marker,
				"docstatus": ["<", 2],
			},
			"name",
		)
		if not name:
			name = create_project_transfer(project.name, source, items)["stock_entry"]
			frappe.db.set_value("Stock Entry", name, "remarks", marker)
		doc = frappe.get_doc("Stock Entry", name)
		if doc.docstatus == 0:
			doc.submit()

	issue = frappe.db.get_value(
		"Stock Entry",
		{
			"project": project.name,
			"purpose": "Material Issue",
			"remarks": "BS-WP-UAT-CONSUMPTION",
			"docstatus": ["<", 2],
		},
		"name",
	)
	if not issue:
		from buildsuite_core.api.material_consumption import save_material_consumption

		result = save_material_consumption(
			project=project.name,
			items=frappe.as_json(
				[
					{"item_code": ITEMS["primer"], "qty": 79.5},
					{"item_code": ITEMS["silica"], "qty": 63.6},
					{"item_code": ITEMS["aqualine"], "qty": AQUALINE_QTY},
				]
			),
			cost_code=frappe.as_json(
				{"type": "item", "group_code": "A", "item_code": "1", "label": "A / 1 Waterproofing"}
			),
		)
		issue = result["name"]
		frappe.db.set_value("Stock Entry", issue, "remarks", "BS-WP-UAT-CONSUMPTION")
	issue_doc = frappe.get_doc("Stock Entry", issue)
	if issue_doc.docstatus == 0:
		issue_doc.submit()
	return {
		"work_order": wo.name,
		"transfer_for_manufacture": transfer,
		"manufacture": manufacture,
		"project_warehouse": project_warehouse,
		"material_consumption": issue,
	}


def _ensure_advance(party_type, party, amount, reference):
	existing = frappe.db.get_value(
		"Payment Entry",
		{
			"company": COMPANY,
			"party_type": party_type,
			"party": party,
			"reference_no": reference,
			"docstatus": 1,
		},
		"name",
	)
	if existing:
		return existing
	if party_type == "Customer":
		from buildsuite_core.api.invoice import record_advance

		return record_advance(party, amount, START_DATE, BANK_ACCOUNT, "Wire Transfer", reference)[
			"payment_entry"
		]
	from buildsuite_core.api.supplier_bill import record_advance

	return record_advance(party, amount, START_DATE, BANK_ACCOUNT, "Wire Transfer", reference)[
		"payment_entry"
	]


def _ensure_sales_invoices(sales_order):
	from buildsuite_core.api.contract import sales_order_to_progress_invoice

	invoices = frappe.get_all(
		"Sales Invoice",
		{"project": sales_order.project, "docstatus": ["<", 2]},
		["name", "docstatus"],
		order_by="creation",
	)
	while len(invoices) < 2:
		result = sales_order_to_progress_invoice(sales_order.name, 50, START_DATE)
		invoices.append(frappe._dict(name=result["sales_invoice"], docstatus=0))
	out = []
	for row in invoices[:2]:
		doc = frappe.get_doc("Sales Invoice", row.name)
		if doc.docstatus == 0:
			doc.submit()
		_assert_close(f"{doc.name} gross", doc.grand_total, 45410.40)
		_assert_close(f"{doc.name} retention", doc.retention_amount, 4541.04)
		_assert_close(f"{doc.name} advance", doc.total_advance, 9082.08)
		_assert_close(
			f"{doc.name} initially collectible",
			flt(doc.grand_total) - flt(doc.retention_amount) - flt(doc.total_advance),
			31787.28,
		)
		out.append(doc)
	return out


def _ensure_pdc(reference_no, payment_type, party, project, invoice, amount, *, bounce=False):
	from buildsuite_core.api.pdc import bounce_pdc, clear_pdc, present_pdc, save_pdc, submit_pdc

	name = frappe.db.get_value(
		"Post Dated Cheques", {"reference_no": reference_no, "company": COMPANY}, "name"
	)
	if name:
		doc = frappe.get_doc("Post Dated Cheques", name)
	else:
		doc_data = save_pdc(
			frappe.as_json(
				{
					"payment_type": payment_type,
					"company": COMPANY,
					"project": project,
					"party": party,
					"posting_date": START_DATE,
					"mode_of_payment": "Cheque",
					"reference_no": reference_no,
					"reference_date": START_DATE,
					"bank_account": BANK_ACCOUNT,
					"notes": "BuildSuite waterproofing UAT lifecycle",
					"invoice_references": [
						{
							"reference_doctype": "Sales Invoice"
							if payment_type == "Receive"
							else "Purchase Invoice",
							"reference_name": invoice,
							"allocated_amount": amount,
						}
					],
				}
			)
		)
		doc = frappe.get_doc("Post Dated Cheques", doc_data["name"])
	if doc.docstatus == 0:
		submit_pdc(doc.name)
		doc.reload()
	if doc.payment_entry:
		payment_entry_status = frappe.db.get_value("Payment Entry", doc.payment_entry, "docstatus")
		if payment_entry_status == 1 and doc.status != "Cleared":
			clear_pdc(doc.name, BANK_ACCOUNT, START_DATE)
			doc.reload()
		elif payment_entry_status == 2 and bounce and doc.status != "Bounced":
			bounce_pdc(doc.name)
			doc.reload()
	if doc.status == "Pending":
		present_pdc(doc.name)
		doc.reload()
	if doc.status == "Presented":
		clear_pdc(doc.name, BANK_ACCOUNT, START_DATE)
		doc.reload()
	if bounce and doc.status == "Cleared":
		bounce_pdc(doc.name)
		doc.reload()
	return doc


def _ensure_retention_release(invoice_type, invoice_name):
	from buildsuite_core.api.retention import create_retention_release

	doc = frappe.get_doc(invoice_type, invoice_name)
	if flt(doc.retention_outstanding_amount) <= 0.01:
		return frappe.db.get_value(
			"Retention Release Entry",
			{"reference_doctype": invoice_type, "reference_name": invoice_name, "docstatus": 1},
			"name",
		)
	return create_retention_release(
		invoice_type,
		invoice_name,
		doc.retention_outstanding_amount,
		START_DATE,
		"BuildSuite waterproofing UAT closeout",
		1,
	)["release"]["name"]


def _pay_invoice(invoice_type, name, reference):
	doc = frappe.get_doc(invoice_type, name)
	amount = flt(doc.outstanding_amount)
	if amount <= 0.01:
		return None
	if invoice_type == "Sales Invoice":
		from buildsuite_core.api.invoice import record_receipt

		return record_receipt(name, amount, START_DATE, "Wire Transfer", BANK_ACCOUNT, reference)[
			"payment_entry"
		]
	from buildsuite_core.api.supplier_bill import record_payment

	return record_payment(name, amount, START_DATE, "Wire Transfer", BANK_ACCOUNT, reference)["payment_entry"]


def _ensure_subcontract(project):
	from buildsuite_core.api.subcontract import certify_measurement_book, save_measurement_book
	from buildsuite_core.api.subcontractor_bill import save_bill, submit_bill

	swo_name = frappe.db.get_value(
		"Subcontractor Work Order",
		{"project": project.name, "subcontractor": SUBCONTRACTOR, "docstatus": ["<", 2]},
		"name",
	)
	if swo_name:
		swo = frappe.get_doc("Subcontractor Work Order", swo_name)
	else:
		swo = frappe.get_doc(
			{
				"doctype": "Subcontractor Work Order",
				"subcontractor": SUBCONTRACTOR,
				"project": project.name,
				"date": START_DATE,
				"retention_percent": 10,
				"lines": [
					{
						"scope": "Waterproofing application labour — two certified stages",
						"cost_code_type": "Item",
						"cost_code_group": "A",
						"cost_code_item": "1",
						"cost_code_label": "A / 1 Waterproofing",
						"uom": "Nos",
						"qty": 2,
						"rate": EXPECTED["labour"] / 1.05 / 2,
					}
				],
			}
		).insert(ignore_permissions=True)
	if swo.docstatus == 0:
		swo.submit()
	line = swo.lines[0]
	# ERPNext rounds each AED 1,733.10 certificate to AED 1,733.00 before applying
	# the native 20% recovery cap, so the two-stage advance is AED 693.20.
	advance = _ensure_advance("Supplier", SUBCONTRACTOR, SUBCONTRACT_ADVANCE, "BS-WP-UAT-SUB-ADVANCE")
	bills = []
	for stage in (1, 2):
		marker = f"BS-WP-UAT-MB-{stage}"
		mb_name = frappe.db.get_value("Measurement Book", {"work_order": swo.name, "remarks": marker}, "name")
		if not mb_name:
			mb = save_measurement_book(
				work_order=swo.name,
				project=project.name,
				date=START_DATE,
				measured_by="Administrator",
				remarks=marker,
				entries=frappe.as_json(
					[
						{
							"description": f"Certified waterproofing labour stage {stage}",
							"work_order_line": line.name,
							"uom": "Nos",
							"quantity": 1,
						}
					]
				),
			)
			mb_name = mb["name"]
		certify_measurement_book(mb_name)
		bill_name = frappe.db.get_value(
			"Subcontractor Bill", {"work_order": swo.name, "ra_no": stage, "docstatus": ["<", 2]}, "name"
		)
		if not bill_name:
			bill_data = save_bill(
				frappe.as_json(
					{
						"is_direct": 0,
						"work_order": swo.name,
						"date": START_DATE,
						"supplier_invoice_no": f"BS-WP-UAT-SUB-{stage}",
						"supplier_invoice_date": START_DATE,
						"retention_percent": 10,
						"advance_recovery_percent": 20,
						"taxes_and_charges": PURCHASE_TAX_TEMPLATE,
					}
				)
			)
			bill_name = bill_data["name"]
		bill = frappe.get_doc("Subcontractor Bill", bill_name)
		if bill.docstatus == 0:
			submit_bill(bill.name)
		bill.reload()
		bills.append(bill)

	first_pi = frappe.get_doc("Purchase Invoice", bills[0].purchase_invoice)
	first_due = flt(first_pi.outstanding_amount)
	bounced = _ensure_pdc(
		"BS-WP-UAT-OUT-BOUNCE", "Pay", SUBCONTRACTOR, project.name, first_pi.name, first_due, bounce=True
	)
	if bounced.status != "Bounced":
		frappe.throw(_("Outgoing PDC bounce demonstration did not reach Bounced"))
	_ensure_pdc("BS-WP-UAT-OUT-REISSUE", "Pay", SUBCONTRACTOR, project.name, first_pi.name, first_due)
	_pay_invoice("Purchase Invoice", bills[1].purchase_invoice, "BS-WP-UAT-SUB-CASH-2")
	for index, bill in enumerate(bills, start=1):
		_ensure_retention_release("Purchase Invoice", bill.purchase_invoice)
		_pay_invoice("Purchase Invoice", bill.purchase_invoice, f"BS-WP-UAT-SUB-RET-{index}")
	return {
		"work_order": swo.name,
		"advance": advance,
		"measurement_books": frappe.get_all("Measurement Book", {"work_order": swo.name}, pluck="name"),
		"bills": [bill.name for bill in bills],
		"purchase_invoices": [bill.purchase_invoice for bill in bills],
		"bounced_pdc": bounced.name,
	}


def _reconcile(project, boq, sales_order, sales_invoices, procurement, manufacturing, subcontract):
	_assert_boq(frappe.get_doc("BOQ", boq.name))
	for invoice in sales_invoices:
		doc = frappe.get_doc("Sales Invoice", invoice.name)
		_assert_close(f"{doc.name} outstanding", doc.outstanding_amount, 0)
		_assert_close(f"{doc.name} retention outstanding", doc.retention_outstanding_amount, 0)
	for name in subcontract["purchase_invoices"]:
		doc = frappe.get_doc("Purchase Invoice", name)
		_assert_close(f"{doc.name} outstanding", doc.outstanding_amount, 0)
		_assert_close(f"{doc.name} retention outstanding", doc.retention_outstanding_amount, 0)
	material_pi = frappe.get_doc("Purchase Invoice", procurement["purchase_invoice"])
	_assert_close("Material supplier invoice outstanding", material_pi.outstanding_amount, 0)
	_assert_close("Material supplier retention outstanding", material_pi.retention_outstanding_amount, 0)
	for reference in ("BS-WP-UAT-CUSTOMER-ADVANCE", "BS-WP-UAT-SUB-ADVANCE"):
		pe = frappe.db.get_value(
			"Payment Entry",
			{"reference_no": reference, "docstatus": 1},
			["name", "unallocated_amount"],
			as_dict=True,
		)
		_assert_close(f"{reference} unallocated", pe.unallocated_amount, 0)
	return {
		"project": project.name,
		"boq": boq.name,
		"sales_order": sales_order.name,
		"sales_invoices": [doc.name for doc in sales_invoices],
		"procurement": procurement,
		"manufacturing": manufacturing,
		"subcontract": subcontract,
		"retention_releases": frappe.get_all(
			"Retention Release Entry", {"project": project.name, "docstatus": 1}, pluck="name"
		),
		"pdcs": frappe.get_all(
			"Post Dated Cheques",
			{"project": project.name},
			["name", "payment_type", "status", "payment_entry"],
			order_by="creation",
		),
		"zero_open_balances": True,
		"expected": EXPECTED,
	}


@frappe.whitelist()
def create_waterproofing_production_drafts():
	"""Create only planning documents on production; never submit a transaction."""
	frappe.only_for("System Manager")
	if "uat" in frappe.local.site.lower():
		frappe.throw(_("Production draft setup cannot run on a UAT site."))
	setup_waterproofing_masters()
	project = _ensure_project(uat=False)
	boq = _ensure_boq(project, approve=False)
	if boq.status != "Draft":
		frappe.throw(_("Existing waterproofing BOQ {0} is not a draft.").format(boq.name))
	sales_order = _ensure_draft_sales_order(boq, project)
	return {
		"project": project.name,
		"boq": boq.name,
		"boq_status": boq.status,
		"sales_order": sales_order.name,
		"sales_order_docstatus": sales_order.docstatus,
		"submitted_transactions": 0,
		"expected": EXPECTED,
	}


@frappe.whitelist()
def create_waterproofing_uat_transactions():
	"""Run the end-to-end scenario only on a site whose name clearly identifies it as UAT."""
	frappe.only_for("System Manager")
	if "uat" not in frappe.local.site.lower():
		frappe.throw(_("Waterproofing transactions may only be created on a UAT site."))
	setup_waterproofing_masters()
	_ensure_warehouse("BuildSuite UAT Raw")
	_ensure_warehouse("BuildSuite UAT WIP")
	_ensure_warehouse("BuildSuite UAT Finished")
	project = _ensure_project()
	boq = _ensure_boq(project)
	sales_order = _ensure_sales_order(boq, project)
	mrs = _ensure_material_requests(boq)
	procurement = _ensure_procurement(mrs["purchase"], project)
	bom = frappe.get_doc(
		"BOM", frappe.db.get_value("BOM", {"item": ITEMS["aqualine"], "docstatus": 1, "is_active": 1}, "name")
	)
	manufacturing = _ensure_manufacturing(bom, project)
	_ensure_advance("Customer", CUSTOMER, EXPECTED["contract_total"] * 0.20, "BS-WP-UAT-CUSTOMER-ADVANCE")
	sales_invoices = _ensure_sales_invoices(sales_order)
	_ensure_pdc(
		"BS-WP-UAT-IN-01",
		"Receive",
		CUSTOMER,
		project.name,
		sales_invoices[0].name,
		sales_invoices[0].outstanding_amount,
	)
	_pay_invoice("Sales Invoice", sales_invoices[1].name, "BS-WP-UAT-CUSTOMER-CASH-2")
	for index, invoice in enumerate(sales_invoices, start=1):
		_ensure_retention_release("Sales Invoice", invoice.name)
		_pay_invoice("Sales Invoice", invoice.name, f"BS-WP-UAT-CUSTOMER-RET-{index}")
	subcontract = _ensure_subcontract(project)
	project.reload()
	project.project_status = "Completed"
	project.status = "Completed"
	project.save(ignore_permissions=True)
	result = _reconcile(project, boq, sales_order, sales_invoices, procurement, manufacturing, subcontract)
	print(frappe.as_json(result))
	return result

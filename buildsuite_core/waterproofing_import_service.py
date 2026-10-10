"""Transactional orchestration for the exact workbook waterproofing import."""

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import frappe
from frappe.utils import flt, getdate

from buildsuite_core.waterproofing_import import (
	COMPANY,
	CUSTOMER,
	EXPECTED,
	PROJECT_ID,
	PROJECT_NAME,
	R1_PROFILE,
	parse_workbook,
)
from buildsuite_core.waterproofing_import_audit import attach_source, remove_physical_file, write_audit
from buildsuite_core.waterproofing_import_documents import (
	ASSEMBLY,
	BOQ_TITLE,
	ITEM,
	SELECTED,
	TEMPLATE,
	WP_CODE,
	close_enough,
	create_assembly,
	create_boq,
	create_project,
	create_rates,
	create_sales_order,
	create_service_item,
	create_template,
	create_work_package,
)


def _project_name():
	return frappe.db.get_value("Project", {"custom_project_id": PROJECT_ID}, "name")


def _work_package(project):
	return (
		frappe.db.get_value("Work Package", {"project": project, "code": WP_CODE}, "name")
		if project
		else None
	)


def _boq(project, profile):
	return frappe.db.get_value("BOQ", {"project": project, "title": profile.boq_title}, "name") if project else None


def _sales_order(boq):
	return frappe.db.get_value("Sales Order", {"custom_buildsuite_boq": boq}, "name") if boq else None


def _check_project(project, data, errors):
	if not project:
		if not data.profile.creates_project_context:
			errors.append("R2 requires the existing BS-WP-001 project")
			return
		collision = frappe.db.get_value("Project", {"project_name": PROJECT_NAME}, "name")
		if collision:
			errors.append(f"Project name is already used by {collision}")
		return
	doc = frappe.get_doc("Project", project)
	checks = {
		"name": PROJECT_ID,
		"project_name": PROJECT_NAME,
		"company": COMPANY,
		"customer": CUSTOMER,
		"project_type": "External",
		"project_category": "Other",
		"location": "Dubai",
	}
	for field, expected in checks.items():
		if str(doc.get(field) or "") != expected:
			errors.append(f"Existing Project {project} has conflicting {field}")
	if getdate(doc.expected_start_date) != data.start_date or doc.expected_end_date:
		errors.append(f"Existing Project {project} has conflicting dates")
	if not close_enough(doc.estimated_costing, EXPECTED["cost"]):
		errors.append(f"Existing Project {project} has conflicting estimated cost")


def _check_rates(data, errors):
	for row in data.rates:
		if not frappe.db.exists("Construction Rate Master", row.code):
			if not data.profile.creates_project_context:
				errors.append(f"R2 requires existing Construction Rate Master: {row.code}")
			continue
		doc = frappe.get_doc("Construction Rate Master", row.code)
		if (
			doc.rate_name != row.name
			or doc.category != row.category
			or doc.uom != row.uom
			or doc.supply_method != "Non-stock"
			or doc.item_code
			or not close_enough(doc.current_rate, row.rate, 0.0001)
			or (data.profile.creates_project_context and data.checksum not in (doc.notes or ""))
		):
			errors.append(f"Existing Construction Rate Master conflicts with workbook: {row.code}")


def _check_assembly(data, errors):
	assembly = data.profile.assembly
	if not frappe.db.exists("Assembly", assembly):
		return
	doc = frappe.get_doc("Assembly", assembly)
	actual = [(row.resource, flt(row.coefficient)) for row in doc.components]
	expected = [(row.resource, float(row.coefficient)) for row in data.profile.selected]
	if (
		doc.uom != "Square Meter"
		or len(actual) != 7
		or any(
			a[0] != e[0] or not close_enough(a[1], e[1], 0.000001)
			for a, e in zip(actual, expected, strict=True)
		)
		or data.checksum not in (doc.notes or "")
	):
		errors.append(f"Existing Assembly conflicts with workbook: {assembly}")


def _check_template(data, errors):
	if not data.profile.creates_project_context:
		return
	if not frappe.db.exists("Estimate Template", TEMPLATE):
		return
	doc = frappe.get_doc("Estimate Template", TEMPLATE)
	if (
		len(doc.rows) != 1
		or doc.rows[0].assembly != ASSEMBLY
		or not close_enough(doc.rows[0].placeholder_qty, data.values["area"], 0.0001)
		or data.checksum not in (doc.description or "")
	):
		errors.append(f"Existing Estimate Template conflicts with workbook: {TEMPLATE}")


def _check_item(data, errors):
	if not data.profile.creates_project_context:
		return
	if not frappe.db.exists("Item", ITEM):
		return
	doc = frappe.get_doc("Item", ITEM)
	if doc.is_stock_item or not doc.is_sales_item or doc.stock_uom != "Square Meter":
		errors.append(f"Existing Item conflicts with workbook import: {ITEM}")


def _check_r2_boq(boq, work_package, data, errors):
	direct = frappe.db.get_value(
		"BOQ Item",
		{"boq": boq, "code": "A1"},
		["planned_qty", "rate", "assembly", "work_package"],
		as_dict=True,
	)
	if not direct or (
		not close_enough(direct.planned_qty, data.values["area"], 0.0001)
		or not close_enough(direct.rate, data.values["direct"] / data.values["area"], 0.000001)
		or direct.assembly != data.profile.assembly
		or direct.work_package != work_package
	):
		errors.append(f"Existing R2 direct waterproofing line conflicts with workbook: {boq}")
		return
	expected_qty = {
		component.resource: component.coefficient * data.values["area"]
		for component in data.profile.selected
	}
	actual_qty = {
		row.rate_master: row.qty
		for row in frappe.get_all(
			"BOQ Sub Item", filters={"boq": boq}, fields=["rate_master", "qty"]
		)
	}
	if set(actual_qty) != set(expected_qty) or any(
		not close_enough(actual_qty[resource], quantity, 0.0001)
		for resource, quantity in expected_qty.items()
	):
		errors.append(f"Existing R2 exploded quantities conflict with workbook: {boq}")


def _check_business_docs(project, work_package, boq, sales_order, data, errors):
	if work_package:
		doc = frappe.get_doc("Work Package", work_package)
		if (
			doc.work_package_name != "Waterproofing Works"
			or doc.end_date
			or not close_enough(doc.budget, EXPECTED["cost"])
		):
			errors.append(f"Existing Work Package conflicts with workbook: {work_package}")
	elif not data.profile.creates_project_context:
		errors.append("R2 requires the existing Waterproofing Works work package")
	if boq:
		doc = frappe.get_doc("BOQ", boq)
		if (
			doc.status != "Draft"
			or not close_enough(doc.planned_amount, data.values["cost"])
			or not close_enough(doc.total, data.values["selling"])
			or flt(doc.tax_rate) != 0
			or frappe.db.count("BOQ Item", {"boq": boq}) != 4
			or frappe.db.count("BOQ Sub Item", {"boq": boq}) != 7
			or (
				not data.profile.creates_project_context
				and (doc.base_revision != "BOQ-00001" or doc.revision != 2)
			)
		):
			errors.append(f"Existing BOQ conflicts with workbook: {boq}")
		elif not data.profile.creates_project_context:
			_check_r2_boq(boq, work_package, data, errors)
	if sales_order and data.profile.creates_project_context:
		doc = frappe.get_doc("Sales Order", sales_order)
		if (
			doc.docstatus != 0
			or doc.customer != CUSTOMER
			or len(doc.items) != 1
			or doc.items[0].item_code != ITEM
			or not close_enough(doc.items[0].qty, data.values["area"])
			or not close_enough(doc.grand_total, data.values["selling"])
		):
			errors.append(f"Existing Sales Order conflicts with workbook: {sales_order}")
	if not data.profile.creates_project_context:
		r1_boq = _boq(project, R1_PROFILE)
		if r1_boq != "BOQ-00001":
			errors.append("R2 requires BOQ-00001 as the existing R1 source revision")
		elif frappe.db.get_value("BOQ", r1_boq, "revision") != 1:
			errors.append("BOQ-00001 must remain revision 1")


def get_import_plan(workbook_path):
	data = parse_workbook(workbook_path)
	errors = []
	for doctype, name in (
		("Company", COMPANY),
		("Customer", CUSTOMER),
		("Project Type", "External"),
		("Project Category", "Other"),
		("UOM", "Square Meter"),
		("UOM", "Hour"),
		("UOM", "Kg"),
		("UOM", "Litre"),
		("UOM", "Nos"),
	):
		if not frappe.db.exists(doctype, name):
			errors.append(f"Required {doctype} is missing: {name}")
	project = _project_name()
	work_package = _work_package(project)
	boq = _boq(project, data.profile)
	sales_order = _sales_order(boq)
	_check_project(project, data, errors)
	_check_rates(data, errors)
	_check_assembly(data, errors)
	_check_template(data, errors)
	_check_item(data, errors)
	_check_business_docs(project, work_package, boq, sales_order, data, errors)
	states = {
		"project": project,
		"work_package": work_package,
		"rate_masters": [
			row.code for row in data.rates if frappe.db.exists("Construction Rate Master", row.code)
		],
		"assembly": data.profile.assembly if frappe.db.exists("Assembly", data.profile.assembly) else None,
		"estimate_template": TEMPLATE if data.profile.creates_project_context and frappe.db.exists("Estimate Template", TEMPLATE) else None,
		"item": ITEM if data.profile.creates_project_context and frappe.db.exists("Item", ITEM) else None,
		"boq": boq,
		"sales_order": sales_order if data.profile.creates_project_context else None,
		"source_boq": _boq(project, R1_PROFILE) if not data.profile.creates_project_context else None,
	}
	return {
		"operation": "Waterproofing workbook planning and draft import",
		"profile": data.profile.key,
		"site": frappe.local.site,
		"workbook": str(Path(workbook_path).expanduser().resolve()),
		"workbook_sha256": data.checksum,
		"customer_mapping": {data.customer: CUSTOMER},
		"project": {
			"id": PROJECT_ID,
			"name": data.project_name,
			"location": data.location,
			"start_date": str(data.start_date),
		},
		"rates": [
			{**asdict(row), "rate": str(row.rate), "coverage": str(row.coverage)} for row in data.rates
		],
		"values": {key: str(value) for key, value in data.values.items()},
		"existing": states,
		"validation_errors": errors,
		"ready_to_apply": not errors,
	}


def apply_import(workbook_path, allow_production=False):
	if "uat" not in frappe.local.site and not allow_production:
		frappe.throw("Use --allow-production to apply the waterproofing import outside a UAT site")
	plan = get_import_plan(workbook_path)
	if plan["validation_errors"]:
		frappe.throw("Waterproofing import preflight failed:\n" + "\n".join(plan["validation_errors"]))
	data = parse_workbook(workbook_path)
	created = {
		"project": [],
		"work_package": [],
		"rate_masters": [],
		"assembly": [],
		"estimate_template": [],
		"item": [],
		"boq": [],
		"sales_order": [],
		"attachments": [],
	}
	unchanged = []
	physical_files = []
	try:
		project = _project_name()
		if not project:
			project = create_project(data).name
			created["project"].append(project)
		else:
			unchanged.append(project)
		work_package = _work_package(project)
		if not work_package and data.profile.creates_project_context:
			work_package = create_work_package(project, data).name
			created["work_package"].append(work_package)
		missing_rates = [
			row for row in data.rates if not frappe.db.exists("Construction Rate Master", row.code)
		]
		if missing_rates and data.profile.creates_project_context:
			created["rate_masters"].extend(create_rates(data, missing_rates))
		unchanged.extend(row.code for row in data.rates if row.code not in created["rate_masters"])
		if not frappe.db.exists("Assembly", data.profile.assembly):
			created["assembly"].append(create_assembly(data).name)
		else:
			unchanged.append(data.profile.assembly)
		if data.profile.creates_project_context and not frappe.db.exists("Estimate Template", TEMPLATE):
			created["estimate_template"].append(create_template(data).name)
		elif data.profile.creates_project_context:
			unchanged.append(TEMPLATE)
		if data.profile.creates_project_context and not frappe.db.exists("Item", ITEM):
			created["item"].append(create_service_item().name)
		elif data.profile.creates_project_context:
			unchanged.append(ITEM)
		boq = _boq(project, data.profile)
		if not boq:
			base_boq = _boq(project, R1_PROFILE) if not data.profile.creates_project_context else None
			boq = create_boq(project, work_package, data, base_boq=base_boq).name
			created["boq"].append(boq)
		else:
			unchanged.append(boq)
		sales_order = _sales_order(boq) if data.profile.creates_project_context else None
		if data.profile.creates_project_context and not sales_order:
			sales_order = create_sales_order(project, boq, data).name
			created["sales_order"].append(sales_order)
		elif data.profile.creates_project_context:
			unchanged.append(sales_order)
		attachment, was_created, physical_created = attach_source(workbook_path, project, data.checksum)
		if was_created:
			created["attachments"].append(attachment)
			if physical_created:
				physical_files.append(frappe.db.get_value("File", attachment, "file_url"))
		else:
			unchanged.append(attachment)
		result = {
			**plan,
			"created": created,
			"unchanged": unchanged,
			"documents": {
				"project": project,
				"work_package": work_package,
				"boq": boq,
				"sales_order": sales_order,
			},
			"applied_at": datetime.now().astimezone().isoformat(),
			"import_complete": True,
		}
		result["audit"] = write_audit(result, project)
		if result["audit"]["created"]:
			physical_files.append(result["audit"]["file_url"])
		return result
	except Exception:
		for file_url in physical_files:
			remove_physical_file(file_url)
		raise

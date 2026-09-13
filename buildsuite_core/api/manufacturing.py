"""Project-filtered manufacturing workspace and thin ERPNext orchestration wrappers."""

import frappe
from frappe import _
from frappe.utils import cint, flt


@frappe.whitelist()
def get_manufacturing_workspace(project=None, company=None):
	work_order_filters = {}
	stock_entry_filters = {}
	warehouse_filters = {"is_group": 0}
	if project:
		project_doc = frappe.get_doc("Project", project)
		project_doc.check_permission("read")
		if company and project_doc.company != company:
			frappe.throw(_("Company must match the selected Project."))
		company = company or project_doc.company
		work_order_filters["project"] = project
		stock_entry_filters["project"] = project
		warehouse_filters["project"] = project
	if company:
		work_order_filters["company"] = company
		stock_entry_filters["company"] = company
		warehouse_filters["company"] = company

	work_orders = frappe.get_list(
		"Work Order",
		filters=work_order_filters,
		fields=[
			"name",
			"production_item",
			"bom_no",
			"qty",
			"produced_qty",
			"status",
			"project",
			"source_warehouse",
			"wip_warehouse",
			"fg_warehouse",
			"docstatus",
		],
		order_by="creation desc",
		limit_page_length=0,
	)
	stock_entries = frappe.get_list(
		"Stock Entry",
		filters=stock_entry_filters,
		fields=[
			"name",
			"stock_entry_type",
			"purpose",
			"work_order",
			"project",
			"posting_date",
			"total_amount",
			"docstatus",
		],
		order_by="posting_date desc, creation desc",
		limit_page_length=0,
	)
	bom_items = list({row.production_item for row in work_orders if row.production_item})
	boms = frappe.get_list(
		"BOM",
		filters={"item": ["in", bom_items]} if bom_items else {"name": ["in", []]},
		fields=["name", "item", "quantity", "total_cost", "is_active", "is_default", "docstatus"],
		order_by="modified desc",
		limit_page_length=0,
	)
	return {
		"project": project,
		"stock_entry_types": frappe.get_list(
			"Stock Entry Type",
			fields=["name", "purpose", "is_standard"],
			order_by="is_standard desc, name",
			limit_page_length=0,
		),
		"work_orders": work_orders,
		"stock_entries": stock_entries,
		"warehouses": frappe.get_list(
			"Warehouse",
			filters=warehouse_filters,
			fields=["name", "warehouse_name", "company", "project"],
			order_by="warehouse_name",
			limit_page_length=0,
		),
		"boms": boms,
		"material_consumption": [row for row in stock_entries if row.purpose == "Material Issue"],
	}


@frappe.whitelist()
def create_work_order(
	bom,
	qty,
	project,
	company=None,
	source_warehouse=None,
	wip_warehouse=None,
	fg_warehouse=None,
	submit=0,
):
	from erpnext.manufacturing.doctype.work_order.work_order import make_work_order

	if not frappe.has_permission("Work Order", "create"):
		frappe.throw(_("You are not permitted to create a Work Order."), frappe.PermissionError)
	bom_doc = frappe.get_doc("BOM", bom)
	if bom_doc.docstatus != 1 or not bom_doc.is_active:
		frappe.throw(_("Use an active submitted BOM."))
	project_company = frappe.db.get_value("Project", project, "company")
	company = company or project_company
	if project_company and company != project_company:
		frappe.throw(_("Work Order company must match the Project company."))

	doc = make_work_order(
		bom_no=bom_doc.name,
		item=bom_doc.item,
		qty=flt(qty),
		company=company,
		project=project,
	)
	doc.source_warehouse = source_warehouse or doc.source_warehouse
	doc.wip_warehouse = wip_warehouse or doc.wip_warehouse
	doc.fg_warehouse = fg_warehouse or doc.fg_warehouse
	doc.project = project
	doc.flags.ignore_permissions = True
	doc.insert()
	if cint(submit):
		doc.submit()
	return {"work_order": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def submit_work_order(name):
	doc = frappe.get_doc("Work Order", name)
	doc.check_permission("submit")
	doc.submit()
	return {"work_order": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def create_work_order_stock_entry(work_order, purpose, qty=None, submit=0):
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

	if purpose not in ("Material Transfer for Manufacture", "Manufacture"):
		frappe.throw(_("Purpose must be Material Transfer for Manufacture or Manufacture."))
	if not frappe.has_permission("Stock Entry", "create"):
		frappe.throw(_("You are not permitted to create a Stock Entry."), frappe.PermissionError)

	values = make_stock_entry(work_order, purpose, flt(qty) if qty is not None else None)
	doc = frappe.get_doc(values)
	doc.project = frappe.db.get_value("Work Order", work_order, "project")
	doc.flags.ignore_permissions = True
	doc.insert()
	if cint(submit):
		doc.submit()
	return {"stock_entry": doc.name, "docstatus": doc.docstatus, "purpose": doc.purpose}


@frappe.whitelist()
def submit_stock_entry(name):
	doc = frappe.get_doc("Stock Entry", name)
	doc.check_permission("submit")
	doc.submit()
	return {"stock_entry": doc.name, "docstatus": doc.docstatus, "purpose": doc.purpose}


@frappe.whitelist()
def create_project_transfer(project, source_warehouse, items, submit=0):
	if isinstance(items, str):
		items = frappe.parse_json(items)
	if not frappe.has_permission("Stock Entry", "create"):
		frappe.throw(_("You are not permitted to create a Stock Entry."), frappe.PermissionError)
	project_company = frappe.db.get_value("Project", project, "company")
	if not project_company:
		frappe.throw(_("Project {0} does not have a Company.").format(project))
	source_company = frappe.db.get_value("Warehouse", source_warehouse, "company")
	if source_company != project_company:
		frappe.throw(_("Source Warehouse must belong to the Project company."))
	target_warehouse = frappe.db.get_value(
		"Warehouse",
		{"project": project, "company": project_company, "is_group": 0},
		"name",
		order_by="creation desc",
	)
	if not target_warehouse:
		frappe.throw(_("No project warehouse is linked to {0}.").format(project))

	doc = frappe.new_doc("Stock Entry")
	doc.company = project_company
	doc.stock_entry_type = "Material Transfer"
	doc.purpose = "Material Transfer"
	doc.project = project
	for row in items or []:
		doc.append(
			"items",
			{
				"item_code": row.get("item_code"),
				"qty": flt(row.get("qty")),
				"s_warehouse": source_warehouse,
				"t_warehouse": target_warehouse,
				"project": project,
			},
		)
	doc.flags.ignore_permissions = True
	doc.insert()
	if cint(submit):
		doc.submit()
	return {"stock_entry": doc.name, "target_warehouse": target_warehouse, "docstatus": doc.docstatus}

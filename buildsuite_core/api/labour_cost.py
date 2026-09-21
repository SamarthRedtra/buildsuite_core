"""Labour Cost Sheet endpoints for Workforce and Project Finance."""

import frappe
from frappe import _
from frappe.utils import flt, today

from buildsuite_core.buildsuite_core.doctype.labour_cost_sheet.labour_cost_sheet import (
	aggregate_sources,
	get_available_sources,
)

DOCTYPE = "Labour Cost Sheet"
APPROVER_ROLES = {
	"BuildSuite Administrator",
	"BuildSuite Director",
	"BuildSuite PM",
	"BuildSuite Accountant",
	"System Manager",
}


def _can_submit():
	return frappe.session.user == "Administrator" or bool(APPROVER_ROLES & set(frappe.get_roles()))


def _project_company(project):
	project_doc = frappe.get_doc("Project", project)
	project_doc.check_permission("read")
	if not project_doc.company:
		frappe.throw(_("Project {0} does not have a company.").format(frappe.bold(project)))
	return project_doc.company


def _cost_code_fields(cost_code):
	if not cost_code or not isinstance(cost_code, dict):
		return {
			"cost_code_type": "",
			"cost_code_group": "",
			"cost_code_item": "",
			"cost_code_label": "",
		}
	return {
		"cost_code_type": "Item"
		if (cost_code.get("type") or "").lower() == "item"
		else "Group",
		"cost_code_group": cost_code.get("group_code") or "",
		"cost_code_item": cost_code.get("item_code") or "",
		"cost_code_label": cost_code.get("label") or "",
	}


def _serialize(doc):
	return {
		"name": doc.name,
		"project": doc.project,
		"company": doc.company,
		"from_date": str(doc.from_date),
		"to_date": str(doc.to_date),
		"posting_date": str(doc.posting_date),
		"expense_account": doc.expense_account,
		"credit_account": doc.credit_account,
		"cost_center": doc.cost_center,
		"journal_entry": doc.journal_entry,
		"cost_code": {
			"type": (doc.cost_code_type or "").lower(),
			"group_code": doc.cost_code_group or "",
			"item_code": doc.cost_code_item or "",
			"label": doc.cost_code_label or "",
		},
		"regular_cost": flt(doc.regular_cost),
		"overtime_cost": flt(doc.overtime_cost),
		"total_cost": flt(doc.total_cost),
		"docstatus": doc.docstatus,
		"employees": [row.as_dict() for row in doc.employees],
		"source_count": len(doc.sources),
		"can_submit": _can_submit(),
	}


@frappe.whitelist()
def preview(project: str, from_date: str, to_date: str):
	frappe.has_permission(DOCTYPE, "read", throw=True)
	_project_company(project)
	sources = get_available_sources(project, from_date, to_date)
	employees = aggregate_sources(sources)
	return {
		"employees": employees,
		"source_count": len(sources),
		"regular_cost": sum(flt(row.get("regular_cost")) for row in sources),
		"overtime_cost": sum(flt(row.get("overtime_cost")) for row in sources),
		"total_cost": sum(flt(row.get("total_cost")) for row in sources),
	}


@frappe.whitelist()
def list_sheets(project: str | None = None):
	filters = {"project": project} if project else {}
	rows = frappe.get_list(
		DOCTYPE,
		filters=filters,
		fields=[
			"name",
			"project",
			"company",
			"from_date",
			"to_date",
			"posting_date",
			"regular_cost",
			"overtime_cost",
			"total_cost",
			"docstatus",
			"journal_entry",
			"cost_code_label",
		],
		order_by="posting_date desc, creation desc",
		limit_page_length=0,
	)
	for row in rows:
		for field in ("from_date", "to_date", "posting_date"):
			row[field] = str(row[field]) if row.get(field) else None
		for field in ("regular_cost", "overtime_cost", "total_cost"):
			row[field] = flt(row.get(field))
	return {"rows": rows, "can_submit": _can_submit()}


@frappe.whitelist()
def get_sheet(name: str):
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	return _serialize(doc)


@frappe.whitelist()
def save_sheet(payload: str):
	data = frappe.parse_json(payload)
	project = data.get("project")
	if not project:
		frappe.throw(_("A project is required."))
	company = _project_company(project)

	name = data.get("name")
	if name and frappe.db.exists(DOCTYPE, name):
		doc = frappe.get_doc(DOCTYPE, name)
		doc.check_permission("write")
		if doc.docstatus != 0:
			frappe.throw(_("Only a draft Labour Cost Sheet can be edited."))
	else:
		doc = frappe.new_doc(DOCTYPE)

	doc.update(
		{
			"project": project,
			"company": company,
			"from_date": data.get("from_date"),
			"to_date": data.get("to_date"),
			"posting_date": data.get("posting_date") or today(),
			"expense_account": data.get("expense_account"),
			"credit_account": data.get("credit_account"),
			"cost_center": data.get("cost_center"),
			**_cost_code_fields(data.get("cost_code")),
		}
	)
	doc.save()
	return _serialize(doc)


@frappe.whitelist()
def submit_sheet(name: str):
	if not _can_submit():
		frappe.throw(_("You are not authorised to submit labour costs."), frappe.PermissionError)
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.docstatus != 0:
		frappe.throw(_("Only a draft Labour Cost Sheet can be submitted."))
	doc.check_permission("submit")
	doc.submit()
	return _serialize(doc)


@frappe.whitelist()
def cancel_sheet(name: str):
	if not _can_submit():
		frappe.throw(_("You are not authorised to cancel labour costs."), frappe.PermissionError)
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted Labour Cost Sheet can be cancelled."))
	doc.check_permission("cancel")
	doc.cancel()
	return _serialize(doc)


@frappe.whitelist()
def delete_sheet(name: str):
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("delete")
	if doc.docstatus != 0:
		frappe.throw(_("Only a draft Labour Cost Sheet can be deleted."))
	frappe.delete_doc(DOCTYPE, name)
	return {"name": name, "deleted": True}


@frappe.whitelist()
def list_accounts(project: str):
	frappe.has_permission(DOCTYPE, "create", throw=True)
	company = _project_company(project)
	accounts = frappe.get_list(
		"Account",
		filters={"company": company, "is_group": 0},
		fields=["name", "root_type", "account_type"],
		order_by="name",
		limit_page_length=0,
	)
	return {
		"company": company,
		"expense_accounts": [row for row in accounts if row.root_type == "Expense"],
		"credit_accounts": [row for row in accounts if row.root_type in ("Asset", "Liability")],
	}

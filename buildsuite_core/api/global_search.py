"""Permission-aware command-palette search for Redtra Suite and ERPNext records."""

from urllib.parse import quote

import frappe

LIMIT = 5
DOCUMENT_CANDIDATE_LIMIT = 30

INTERNAL_ROUTES = {
	"Project": "/projects",
	"Task": "/tasks",
	"Work Package": "/work-packages",
	"Material Request": "/procurement/material-requests",
	"Purchase Order": "/procurement/purchase-orders",
	"Purchase Receipt": "/procurement/purchase-receipts",
	"Sales Invoice": "/project-finance/invoices",
	"Purchase Invoice": "/project-finance/supplier-bills",
}


def _like(query):
	return f"%{query}%"


def _projects(query):
	if not frappe.has_permission("Project", "read"):
		return []
	rows = frappe.get_list(
		"Project",
		fields=["name", "custom_project_id", "project_name", "customer", "location"],
		or_filters={
			"name": ["like", _like(query)],
			"custom_project_id": ["like", _like(query)],
			"project_name": ["like", _like(query)],
			"customer": ["like", _like(query)],
			"location": ["like", _like(query)],
		},
		order_by="modified desc",
		limit_page_length=LIMIT,
	)
	return [
		{
			"type": "Project",
			"id": row.name,
			"title": row.project_name or row.name,
			"subtitle": " · ".join(
				filter(None, [row.custom_project_id or row.name, row.customer, row.location])
			),
			"route": _document_route("Project", row.name),
		}
		for row in rows
	]


def _tasks(query):
	if not frappe.has_permission("Task", "read"):
		return []
	rows = frappe.get_list(
		"Task",
		fields=["name", "subject", "project", "status"],
		filters={"project": ["is", "set"]},
		or_filters={"name": ["like", _like(query)], "subject": ["like", _like(query)]},
		order_by="modified desc",
		limit_page_length=LIMIT,
	)
	return [
		{
			"type": "Task",
			"id": row.name,
			"title": row.subject or row.name,
			"subtitle": " · ".join(filter(None, [row.name, row.project, row.status])),
			"route": _document_route("Task", row.name),
		}
		for row in rows
	]


def _work_packages(query):
	if not frappe.has_permission("Work Package", "read"):
		return []
	rows = frappe.get_list(
		"Work Package",
		fields=["name", "work_package_name", "code", "project", "status"],
		or_filters={
			"name": ["like", _like(query)],
			"work_package_name": ["like", _like(query)],
			"code": ["like", _like(query)],
		},
		order_by="modified desc",
		limit_page_length=LIMIT,
	)
	return [
		{
			"type": "Work Package",
			"id": row.name,
			"title": row.work_package_name or row.name,
			"subtitle": " · ".join(filter(None, [row.code, row.project, row.status])),
			"route": _document_route("Work Package", row.name),
		}
		for row in rows
	]


def _doctype_results(query):
	allowed = set(frappe.get_user().get_can_read())
	if not allowed:
		return []
	rows = frappe.get_all(
		"DocType",
		filters={"name": ["in", sorted(allowed)], "istable": 0, "issingle": 0},
		or_filters={"name": ["like", _like(query)], "module": ["like", _like(query)]},
		fields=["name", "module"],
		order_by="name asc",
		limit_page_length=LIMIT,
	)
	return [
		{
			"type": "DocType",
			"id": row.name,
			"title": row.name,
			"subtitle": f"{row.module or 'ERPNext'} · DocType",
			"route": _doctype_route(row.name),
			"external": row.name not in INTERNAL_ROUTES,
		}
		for row in rows
	]


def _document_results(query):
	allowed = set(frappe.get_user().get_can_read())
	results = []
	seen = set()
	for row in _document_candidates(query):
		key = (row.doctype, row.name)
		if key in seen or row.doctype not in allowed:
			continue
		seen.add(key)
		if row.doctype in {"DocType", "Project", "Task", "Work Package"}:
			continue
		try:
			doc = frappe.get_doc(row.doctype, row.name)
			if not doc.has_permission("read"):
				continue
		except (frappe.DoesNotExistError, frappe.PermissionError):
			continue
		meta = frappe.get_meta(row.doctype)
		title = doc.get(meta.title_field) if meta.title_field else None
		results.append(
			{
				"type": row.doctype,
				"id": row.name,
				"title": title or row.name,
				"subtitle": f"{row.doctype} · {row.name}",
				"route": _document_route(row.doctype, row.name),
				"external": row.doctype not in INTERNAL_ROUTES,
			}
		)
		if len(results) >= LIMIT:
			break
	return results


def _document_candidates(query):
	"""Use the Desk global index, with LIKE matching for punctuation-heavy IDs."""
	pattern = _like(query)
	indexed = frappe.db.sql(
		"""SELECT doctype, name, content
		FROM `__global_search`
		WHERE name LIKE %(pattern)s OR content LIKE %(pattern)s
		ORDER BY CASE
			WHEN name = %(query)s THEN 0
			WHEN name LIKE %(prefix)s THEN 1
			ELSE 2
		END, name
		LIMIT %(limit)s""",
		{
			"pattern": pattern,
			"prefix": f"{query}%",
			"query": query,
			"limit": DOCUMENT_CANDIDATE_LIMIT,
		},
		as_dict=True,
	)
	if not any(character.isdigit() for character in query):
		return indexed
	exact = [
		frappe._dict(doctype=doctype, name=query, content="")
		for doctype in INTERNAL_ROUTES
		if frappe.db.exists(doctype, query)
	]
	return exact + indexed


def _doctype_route(doctype):
	if doctype in INTERNAL_ROUTES:
		return INTERNAL_ROUTES[doctype]
	return f"/app/{frappe.scrub(doctype).replace('_', '-')}"


def _document_route(doctype, name):
	base = INTERNAL_ROUTES.get(doctype)
	if base:
		return f"{base}/{quote(name, safe='')}"
	return f"{_doctype_route(doctype)}/{quote(name, safe='')}"


@frappe.whitelist(methods=["GET"])
def global_search(query: str):
	query = (query or "").strip()
	if len(query) < 2:
		return {"groups": []}
	return {
		"groups": [
			{"label": "DocTypes", "results": _doctype_results(query)},
			{"label": "Projects", "results": _projects(query)},
			{"label": "Tasks", "results": _tasks(query)},
			{"label": "Work Packages", "results": _work_packages(query)},
			{"label": "Documents", "results": _document_results(query)},
		]
	}

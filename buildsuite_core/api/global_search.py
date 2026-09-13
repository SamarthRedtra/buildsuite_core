"""Permission-aware search used by the BuildSuite command palette."""

import frappe

LIMIT = 5


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
			"route": f"/projects/{row.name}",
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
			"route": f"/tasks/{row.name}",
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
			"route": f"/work-packages/{row.name}",
		}
		for row in rows
	]


@frappe.whitelist(methods=["GET"])
def global_search(query: str):
	query = (query or "").strip()
	if len(query) < 2:
		return {"groups": []}
	return {
		"groups": [
			{"label": "Projects", "results": _projects(query)},
			{"label": "Tasks", "results": _tasks(query)},
			{"label": "Work Packages", "results": _work_packages(query)},
		]
	}

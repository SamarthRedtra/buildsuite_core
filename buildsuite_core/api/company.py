# Copyright (c) 2026, Infraholic Innovations Pvt. Ltd and contributors
# For license information, please see license.txt

"""Company scope for the SPA. Single-company for now — see the single-company seam."""

import frappe

from buildsuite_core.utils.project import default_company


@frappe.whitelist()
def active_company():
	"""The company finance transactions (and their pickers) are scoped to right now.

	Same resolver the server-side company guards use, so the frontend picker filters agree
	with them. `window.sysdefaults.company` is not reliably present (e.g. the standalone Vite
	dev server), so the SPA fetches this instead. Multi-company later: derive from context.
	"""
	return default_company()


@frappe.whitelist(methods=["GET"])
def active_company_context():
	"""Return the one company BuildSuite currently supports in its UI."""
	company = default_company()
	if not frappe.has_permission("Company", "read", company):
		frappe.throw(frappe._("Not permitted to read Company {0}").format(company), frappe.PermissionError)
	row = frappe.db.get_value(
		"Company", company, ["name", "abbr", "company_name", "default_currency", "country"], as_dict=True
	)
	return {
		"id": row.name,
		"name": row.company_name or row.name,
		"shortName": row.abbr,
		"currency": row.default_currency,
		"country": row.country,
	}


@frappe.whitelist(methods=["GET"])
def list_companies():
	"""List real ERPNext companies the current user is allowed to read."""
	active = default_company()
	rows = frappe.get_list(
		"Company",
		fields=["name", "abbr", "company_name", "default_currency", "country", "disabled"],
		order_by="company_name asc",
		limit_page_length=0,
	)
	counts = {
		row.name: len(
			frappe.get_list("Project", filters={"company": row.name}, pluck="name", limit_page_length=0)
		)
		for row in rows
	}
	return [
		{
			"id": row.name,
			"name": row.company_name or row.name,
			"shortName": row.abbr,
			"currency": row.default_currency,
			"country": row.country,
			"disabled": bool(row.disabled),
			"projectCount": counts.get(row.name, 0),
			"active": row.name == active,
		}
		for row in rows
	]

# Copyright (c) 2026, Infraholic Innovations Pvt. Ltd and contributors
# For license information, please see license.txt

"""Whitelisted helpers for Task Progress Entry forms."""

import frappe
from frappe import _

from buildsuite_core.utils.task_progress_quantity import get_quantity_floor, get_task_scope_from_boq


@frappe.whitelist()
def get_task_progress_scope(task: str):
	"""BOQ-derived scope for quantity-based progress entry."""
	if not task or not frappe.db.exists("Task", task):
		frappe.throw(_("Task {0} was not found.").format(task))

	if not frappe.has_permission("Task", "read", doc=task):
		frappe.throw(_("You are not permitted to read this task."), frappe.PermissionError)

	scope = get_task_scope_from_boq(task)
	return {
		"scope_qty": scope["scope_qty"],
		"uom": scope["uom"],
		"boq_names": scope["boq_names"],
		"progress_floor_qty": get_quantity_floor(task),
	}

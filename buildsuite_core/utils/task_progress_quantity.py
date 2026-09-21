# Copyright (c) 2026, Infraholic Innovations Pvt. Ltd and contributors
# For license information, please see license.txt

"""BOQ-scoped quantity input for Task Progress Entry — scope and % conversion."""

import frappe
from frappe import _
from frappe.utils import flt


def get_task_scope_from_boq(task):
	"""Sum planned_qty on BOQ Item rows linked to this task."""
	rows = frappe.get_all(
		"BOQ Item",
		filters={"task": task},
		fields=["planned_qty", "unit", "boq"],
	)
	if not rows:
		return {"scope_qty": 0, "uom": None, "boq_names": []}

	by_uom = {}
	boq_names = set()
	for row in rows:
		qty = flt(row.planned_qty)
		if qty <= 0:
			continue
		uom = (row.unit or "").strip()
		by_uom[uom] = by_uom.get(uom, 0) + qty
		if row.boq:
			boq_names.add(row.boq)

	if not by_uom:
		return {"scope_qty": 0, "uom": None, "boq_names": sorted(boq_names)}

	if len(by_uom) > 1:
		units = ", ".join(sorted(u for u in by_uom if u) or by_uom.keys())
		frappe.throw(
			_(
				"Linked BOQ lines use multiple units ({0}). "
				"Align BOQ units on this task before logging quantity progress."
			).format(units)
		)

	uom = next(iter(by_uom))
	return {
		"scope_qty": flt(by_uom[uom]),
		"uom": uom or None,
		"boq_names": sorted(boq_names),
	}


def get_tasks_scope_from_boq(task_ids):
	"""Batch planned/actual qty per task. Mixed-UOM tasks are omitted (no throw)."""
	ids = [t for t in (task_ids or []) if t and t != "__none__"]
	if not ids:
		return {}

	rows = frappe.get_all(
		"BOQ Item",
		filters={"task": ["in", ids]},
		fields=["task", "planned_qty", "actual_qty", "unit"],
	)
	by_task = {}
	for row in rows:
		planned = flt(row.planned_qty)
		if planned <= 0:
			continue
		bucket = by_task.setdefault(row.task, {})
		uom = (row.unit or "").strip()
		slot = bucket.setdefault(uom, {"scope_qty": 0.0, "actual_qty": 0.0})
		slot["scope_qty"] += planned
		slot["actual_qty"] += flt(row.actual_qty)

	out = {}
	for task, by_uom in by_task.items():
		if len(by_uom) != 1:
			continue
		uom, slot = next(iter(by_uom.items()))
		out[task] = {
			"scope_qty": flt(slot["scope_qty"]),
			"actual_qty": flt(slot["actual_qty"]),
			"uom": uom or None,
		}
	return out


def quantity_from_progress(scope_qty, progress):
	if not flt(scope_qty):
		return 0.0
	return flt(scope_qty) * flt(progress) / 100.0


def quantity_to_progress(task, cumulative_quantity):
	scope = get_task_scope_from_boq(task)
	if not scope["scope_qty"]:
		frappe.throw(
			_(
				"This task has no BOQ quantity scope — link BOQ lines with planned quantity "
				"or log progress as a percentage instead."
			)
		)
	return min(100.0, flt(cumulative_quantity) / scope["scope_qty"] * 100.0)


def get_quantity_floor(task):
	scope = get_task_scope_from_boq(task)
	if not scope["scope_qty"]:
		return 0.0
	progress = flt(frappe.db.get_value("Task", task, "progress"))
	return flt(scope["scope_qty"]) * progress / 100.0


def sync_quantity_fields_from_progress(doc):
	"""When logging by %, optionally persist equivalent quantity for audit."""
	if doc.get("progress_input_mode") != "Percent":
		return
	scope = get_task_scope_from_boq(doc.task)
	if not scope["scope_qty"]:
		return
	doc.quantity_uom = scope["uom"]
	doc.cumulative_quantity = flt(scope["scope_qty"]) * flt(doc.cumulative_progress or 0) / 100.0


def apply_quantity_input_mode(doc):
	"""Derive cumulative_progress (and UOM) when the user entered cumulative quantity."""
	if doc.get("progress_input_mode") != "Quantity":
		sync_quantity_fields_from_progress(doc)
		return

	if doc.cumulative_quantity is None or flt(doc.cumulative_quantity) <= 0:
		frappe.throw(_("Enter the cumulative quantity completed — it must be greater than zero."))

	scope = get_task_scope_from_boq(doc.task)
	if not scope["scope_qty"]:
		frappe.throw(
			_(
				"This task has no BOQ quantity scope — link BOQ lines with planned quantity "
				"or switch to percentage progress."
			)
		)

	doc.quantity_uom = scope["uom"]
	doc.cumulative_progress = quantity_to_progress(doc.task, doc.cumulative_quantity)


def recalculate_boq_actuals_for_task(task):
	"""Refresh BOQ Item actual_qty from Task.progress after a progress entry."""
	from buildsuite_core.api.boq import recalculate_actuals_internal

	boq_names = frappe.db.sql(
		"""
		SELECT DISTINCT boq
		FROM `tabBOQ Item`
		WHERE task = %s AND boq IS NOT NULL AND boq != ''
		""",
		task,
	)
	for (boq,) in boq_names:
		try:
			recalculate_actuals_internal(boq)
		except Exception:
			frappe.log_error(title=f"BOQ actuals sync failed for {boq} (task {task})")

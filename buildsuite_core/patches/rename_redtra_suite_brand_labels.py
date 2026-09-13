"""Apply the Redtra Suite display brand without renaming technical records."""

import frappe

from buildsuite_core.buildsuite_core.doctype.subcontractor.seed_print_assets import (
	_LETTER_HEAD_HTML,
	LETTER_HEAD,
)

OLD_LETTER_HEAD = "BuildSuite Standard"


def execute():
	_rename_letter_head()
	_update_display_labels()


def _rename_letter_head():
	if frappe.db.exists("Letter Head", OLD_LETTER_HEAD) and not frappe.db.exists(
		"Letter Head", LETTER_HEAD
	):
		frappe.rename_doc("Letter Head", OLD_LETTER_HEAD, LETTER_HEAD, force=True)
	if frappe.db.exists("Letter Head", LETTER_HEAD):
		frappe.db.set_value(
			"Letter Head",
			LETTER_HEAD,
			{"letter_head_name": LETTER_HEAD, "content": _LETTER_HEAD_HTML},
			update_modified=False,
		)


def _update_display_labels():
	labels = (
		("Workspace", "BuildSuite", {"label": "Redtra Suite", "title": "Redtra Suite"}),
		("Workspace Sidebar", "BuildSuite", {"title": "Redtra Suite"}),
		("Desktop Icon", "BuildSuite", {"label": "Redtra Suite"}),
		("Module Onboarding", "BuildSuite Onboarding", {"title": "Redtra Suite Onboarding"}),
	)
	for doctype, name, values in labels:
		if frappe.db.exists(doctype, name):
			frappe.db.set_value(doctype, name, values, update_modified=False)

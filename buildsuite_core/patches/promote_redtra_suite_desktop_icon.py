"""Promote Redtra Suite to a top-level app launcher icon."""

import frappe


DESKTOP_ICON = "BuildSuite"
APP_NAME = "buildsuite_core"
APP_LABEL = "Redtra Suite"
APP_ROUTE = "/core"
APP_LOGO = "/assets/buildsuite_core/images/bs-icon.svg"


def execute():
	if not frappe.db.exists("Desktop Icon", DESKTOP_ICON):
		return

	frappe.db.set_value(
		"Desktop Icon",
		DESKTOP_ICON,
		{
			"app": APP_NAME,
			"hidden": 0,
			"icon_type": "App",
			"label": APP_LABEL,
			"link": APP_ROUTE,
			"link_to": None,
			"link_type": "External",
			"logo_url": APP_LOGO,
			"parent_icon": None,
			"sidebar": None,
		},
		update_modified=False,
	)

	# Desktop icons are cached as a hash keyed by user. Delete the entire hash so
	# every user sees the corrected app icon on their next launcher request.
	frappe.cache.delete_key("desktop_icons")
	frappe.cache.delete_key("bootinfo")

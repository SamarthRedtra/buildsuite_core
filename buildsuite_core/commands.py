"""Custom bench CLI commands for buildsuite_core.

Discovered by bench via the module-level `commands` list. Usage:

    bench change-app-route core
"""

import click


@click.command("change-app-route")
@click.argument("new_route")
def change_app_route(new_route):
	"""Rename the BuildSuite frontend route (e.g. `bench change-app-route core`).

	Rewrites the single route token in hooks.py + frontend/src/utils/appRoute.js
	and renames the www/<route>.{py,html} page, then prints the follow-up build/
	restart steps.
	"""
	from buildsuite_core.route import rename_app_route

	click.echo(rename_app_route(new_route))


@click.command("buildsuite-retire-legacy-apps")
@click.option("--site", required=True, help="Site to inspect or prepare")
@click.option("--apply", "apply_changes", is_flag=True, help="Archive and apply the retirement preparation")
@click.option(
	"--allow-production",
	is_flag=True,
	help="Allow --apply outside a site whose name contains 'uat'",
)
def retire_legacy_apps(site, apply_changes=False, allow_production=False):
	"""Dry-run or apply the audited Redtra/Construction retirement preparation."""
	import json

	import frappe

	from buildsuite_core.legacy_retirement import apply_retirement_preparation, get_retirement_plan

	frappe.init(site=site)
	frappe.connect()
	try:
		result = (
			apply_retirement_preparation(allow_production=allow_production)
			if apply_changes
			else get_retirement_plan()
		)
		if apply_changes:
			frappe.db.commit()
		click.echo(json.dumps(result, indent=2, default=str))
	except Exception:
		frappe.db.rollback()
		raise
	finally:
		frappe.destroy()


commands = [change_app_route, retire_legacy_apps]

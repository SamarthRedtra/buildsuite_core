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


@click.command("buildsuite-import-salary-sheet")
@click.option("--site", required=True, help="Site to inspect or import into")
@click.option("--file", "workbook_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--apply", "apply_changes", is_flag=True, help="Apply the validated import atomically")
@click.option("--allow-production", is_flag=True, help="Allow --apply outside a UAT site")
def import_salary_sheet(site, workbook_path, apply_changes=False, allow_production=False):
	"""Dry-run or apply the audited DME 2026 employee salary import."""
	import json

	import frappe

	from buildsuite_core.salary_import_service import apply_salary_import, get_import_plan

	frappe.init(site=site)
	frappe.connect()
	frappe.set_user("Administrator")
	result = None
	try:
		result = (
			apply_salary_import(workbook_path, allow_production=allow_production)
			if apply_changes
			else get_import_plan(workbook_path)
		)
		if apply_changes:
			frappe.db.commit()
		click.echo(json.dumps(result, indent=2, default=str))
	except Exception:
		frappe.db.rollback()
		if result and result.get("audit_path"):
			from buildsuite_core.salary_import_audit import remove_audit

			remove_audit(result["audit_path"])
		raise
	finally:
		frappe.destroy()


commands = [change_app_route, retire_legacy_apps, import_salary_sheet]

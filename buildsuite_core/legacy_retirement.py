"""Archive and prepare legacy construction apps for safe site-level retirement."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import frappe
from frappe.database.schema import add_column
from frappe.utils import cint, get_bench_path, now_datetime

LEGACY_APPS = ("redtra_customisation", "construction_management")
PDC_DOCTYPES = (
	"Post Dated Cheques",
	"PDC Invoice Reference",
	"Post Dated Cheques Tool",
	"Post Dated Cheques Tool Detail",
)
BUILDSUITE_BOQ_DOCTYPES = ("BOQ", "BOQ Item", "BOQ Group", "BOQ Sub Item")
ORPHANED_OPERATIONAL_DOCTYPES = (
	"Project BOQ",
	"BOQ Bill",
	"BOQ Advance Payment",
	"Task Progress Log",
	"BOQ Item",
)
EXPECTED_ORPHAN_COUNTS = {
	"Project BOQ": 6,
	"BOQ Bill": 4,
	"BOQ Advance Payment": 4,
	"Task Progress Log": 7,
	"BOQ Item": 4,
}
CUSTOM_FIELD_ALLOWLIST = (
	("Project", "retention_percentage"),
	("Project", "consultant"),
	("Purchase Invoice", "bill_no"),
	("Purchase Invoice", "boq_item"),
	("Purchase Invoice Item", "bill_no"),
	("Purchase Invoice Item", "boq_item"),
	("Purchase Invoice Item", "from_project_sites"),
	("Purchase Invoice Item", "from_site"),
	("Purchase Invoice Item", "project_sites"),
	("Purchase Invoice Item", "rejected_project_sites"),
	("Purchase Invoice Item", "rejected_site"),
	("Purchase Invoice Item", "site"),
	("Purchase Order", "bill_no"),
	("Purchase Order", "boq_item"),
	("Purchase Order Item", "bill_no"),
	("Purchase Order Item", "boq_item"),
	("Purchase Receipt", "custom_bill_no"),
	("Purchase Receipt", "custom_boq_item"),
	("Purchase Receipt Item Supplied", "project_sites"),
	("Purchase Receipt Item Supplied", "site"),
	("Landed Cost Taxes and Charges", "bill_no"),
	("Landed Cost Taxes and Charges", "boq_item"),
	("Purchase Taxes and Charges", "bill_no"),
	("Purchase Taxes and Charges", "boq_item"),
	("Sales Invoice", "bill_no"),
	("Sales Invoice", "boq_item"),
	("Sales Invoice", "custom_payment_certificate"),
	("Sales Invoice", "custom_proforma_invoice"),
	("Sales Invoice Item", "bill_no"),
	("Sales Invoice Item", "boq_item"),
	("Sales Invoice Item", "project_sites"),
	("Sales Invoice Item", "to_project_sites"),
	("Sales Order", "bill_no"),
	("Sales Order", "boq_item"),
	("Sales Order", "custom_payment_certificate"),
	("Sales Order Item", "bill_no"),
	("Sales Order Item", "boq_item"),
	("Sales Taxes and Charges", "bill_no"),
	("Sales Taxes and Charges", "boq_item"),
	("Stock Entry", "bill_no"),
	("Stock Entry", "boq_item"),
	("Stock Entry Detail", "bill_no"),
	("Stock Entry Detail", "boq_item"),
	("Journal Entry", "custom_cash_bank_entry"),
	("Journal Entry Account", "bill_no"),
	("Journal Entry Account", "boq_item"),
	("Advance Taxes and Charges", "bill_no"),
	("Advance Taxes and Charges", "boq_item"),
	("Attendance", "overtime_request"),
	("Payment Entry", "custom_is_pdc_entry"),
	("Payment Entry", "bill_no"),
	("Payment Entry", "boq_item"),
	("Payment Entry", "custom_cash_bank_entry"),
	("Payment Entry", "custom_security_instrument"),
	("Payment Entry", "pdc_section"),
	("Payment Entry", "pdc_cheque_number"),
	("Payment Entry", "pdc_cheque_date"),
	("Payment Entry", "pdc_bank_account"),
	("Payment Entry", "pdc_cheque_status"),
	("Payment Entry", "pdc_cheque_details_section"),
	("Payment Entry", "pdc_cheque_details"),
	("Payment Entry Deduction", "bill_no"),
	("Payment Entry Deduction", "boq_item"),
	("Packed Item", "project_sites"),
)
PROPERTY_SETTER_ALLOWLIST = ("Stock Entry-project-reqd",)
PDC_STATUS_MAP = {
	"Issued": "Pending",
	"Under Collection": "Presented",
	"Collected": "Cleared",
	"Paid": "Cleared",
	"Converted": "Cleared",
	"Bounced": "Bounced",
	"Cancelled": "Cancelled",
	"Pending": "Pending",
	"Presented": "Presented",
	"Cleared": "Cleared",
}


def get_retirement_plan():
	installed_legacy_apps = [app for app in LEGACY_APPS if app in frappe.get_installed_apps()]
	runtime_registry_legacy_apps = get_runtime_registry_legacy_apps()
	legacy_modules = frappe.get_all(
		"Module Def", filters={"app_name": ["in", LEGACY_APPS]}, pluck="name", order_by="name"
	)
	legacy_doctypes = []
	if legacy_modules:
		legacy_doctypes = frappe.get_all(
			"DocType",
			filters={"module": ["in", legacy_modules], "is_virtual": 0},
			pluck="name",
			order_by="name",
		)

	orphaned_doctypes = ORPHANED_OPERATIONAL_DOCTYPES if installed_legacy_apps else ()
	archive_doctypes = list(dict.fromkeys([*legacy_doctypes, *orphaned_doctypes]))
	archive_doctypes = [doctype for doctype in archive_doctypes if frappe.db.exists("DocType", doctype)]
	counts = {doctype: get_record_count(doctype) for doctype in archive_doctypes}
	ownership = get_shared_doctype_ownership()
	custom_fields = get_allowlisted_custom_fields()
	property_setters = get_allowlisted_property_setters()
	orphan_count_differences = {}
	if installed_legacy_apps:
		orphan_count_differences = {
			doctype: {"expected": expected, "actual": counts.get(doctype, 0)}
			for doctype, expected in EXPECTED_ORPHAN_COUNTS.items()
			if counts.get(doctype, 0) != expected
		}

	return {
		"site": frappe.local.site,
		"legacy_apps": list(LEGACY_APPS),
		"installed_legacy_apps": installed_legacy_apps,
		"runtime_registry_legacy_apps": runtime_registry_legacy_apps,
		"retirement_complete": not installed_legacy_apps and not runtime_registry_legacy_apps,
		"legacy_modules": legacy_modules,
		"archive_doctypes": archive_doctypes,
		"record_counts": counts,
		"expected_orphan_counts": EXPECTED_ORPHAN_COUNTS,
		"orphan_count_differences": orphan_count_differences,
		"shared_doctype_ownership": ownership,
		"allowlisted_custom_fields": custom_fields,
		"allowlisted_property_setters": property_setters,
		"payment_entries_to_migrate": (count_legacy_pdc_payment_entries() if installed_legacy_apps else 0),
	}


def get_runtime_registry_legacy_apps():
	apps_file = Path(get_bench_path(), "sites", "apps.txt")
	if not apps_file.exists():
		return []
	registered_apps = {
		line.strip() for line in apps_file.read_text(encoding="utf-8").splitlines() if line.strip()
	}
	return [app for app in LEGACY_APPS if app in registered_apps]


def apply_retirement_preparation(allow_production=False):
	if "uat" not in frappe.local.site.lower() and not allow_production:
		frappe.throw("Retirement apply is restricted to a UAT site unless --allow-production is explicit.")

	plan = get_retirement_plan()
	validate_buildsuite_boq_ownership(plan["shared_doctype_ownership"])
	archive_path, manifest = create_private_archive(plan)

	ensure_pdc_module_ownership()
	ensure_native_payment_entry_pdc_columns()
	payment_entry_result = migrate_legacy_payment_entry_pdc_fields()
	pdc_status_result = migrate_pdc_statuses()
	removed_custom_fields = remove_allowlisted_custom_field_definitions()
	removed_property_setters = remove_allowlisted_property_setters()
	frappe.clear_cache()

	result = {
		**plan,
		"archive_path": str(archive_path),
		"archive_manifest_checksum": manifest["manifest_checksum"],
		"payment_entry_migration": payment_entry_result,
		"pdc_status_migration": pdc_status_result,
		"removed_custom_field_definitions": removed_custom_fields,
		"removed_property_setters": removed_property_setters,
		"shared_doctype_ownership_after": get_shared_doctype_ownership(),
	}
	validate_pdc_ownership(result["shared_doctype_ownership_after"])
	validate_buildsuite_boq_ownership(result["shared_doctype_ownership_after"])
	return result


def verify_retirement_ownership():
	ownership = get_shared_doctype_ownership()
	validate_pdc_ownership(ownership)
	validate_buildsuite_boq_ownership(ownership)
	return ownership


def get_record_count(doctype):
	meta = frappe.get_meta(doctype)
	if meta.issingle:
		return 1
	return frappe.db.count(doctype)


def get_shared_doctype_ownership():
	names = [*PDC_DOCTYPES, *BUILDSUITE_BOQ_DOCTYPES]
	rows = frappe.get_all(
		"DocType", filters={"name": ["in", names]}, fields=["name", "module"], order_by="name"
	)
	module_apps = {
		row.name.lower(): row.app_name
		for row in frappe.get_all(
			"Module Def", fields=["name", "app_name"], filters={"name": ["in", [r.module for r in rows]]}
		)
	}
	return {row.name: {"module": row.module, "app": module_apps.get(row.module.lower())} for row in rows}


def validate_buildsuite_boq_ownership(ownership):
	wrong = {
		doctype: ownership.get(doctype)
		for doctype in BUILDSUITE_BOQ_DOCTYPES
		if (ownership.get(doctype) or {}).get("module", "").lower() != "buildsuite core"
	}
	if wrong:
		frappe.throw(f"BuildSuite BOQ ownership is incorrect; aborting retirement: {wrong}")


def validate_pdc_ownership(ownership):
	wrong = {
		doctype: ownership.get(doctype)
		for doctype in PDC_DOCTYPES
		if (ownership.get(doctype) or {}).get("module") != "PDC"
		or (ownership.get(doctype) or {}).get("app") != "erpnext"
	}
	if wrong:
		frappe.throw(f"ERPNext PDC ownership is incorrect; aborting retirement: {wrong}")


def get_allowlisted_custom_fields():
	return frappe.get_all(
		"Custom Field",
		filters={"name": ["in", [f"{doctype}-{fieldname}" for doctype, fieldname in CUSTOM_FIELD_ALLOWLIST]]},
		fields=["name", "dt", "fieldname", "fieldtype", "options"],
		order_by="name",
	)


def get_allowlisted_property_setters():
	return frappe.get_all(
		"Property Setter",
		filters={"name": ["in", PROPERTY_SETTER_ALLOWLIST]},
		fields=["name", "doc_type", "field_name", "property", "value", "property_type"],
		order_by="name",
	)


def count_legacy_pdc_payment_entries():
	columns = set(frappe.db.get_table_columns("Payment Entry"))
	legacy_fields = [
		field
		for field in ("custom_is_pdc_entry", "pdc_cheque_number", "pdc_cheque_date", "pdc_cheque_status")
		if field in columns
	]
	if not legacy_fields:
		return 0
	conditions = [f"IFNULL(`{field}`, '') != ''" for field in legacy_fields]
	return cint(
		frappe.db.sql(f"SELECT COUNT(*) FROM `tabPayment Entry` WHERE {' OR '.join(conditions)}")[0][0]
	)


def create_private_archive(plan):
	timestamp = now_datetime().strftime("%Y%m%d_%H%M%S")
	archive_path = Path(frappe.get_site_path("private", "files", "buildsuite_retirement", timestamp))
	archive_path.mkdir(parents=True, exist_ok=False)

	exports = []
	for doctype in plan["archive_doctypes"]:
		exports.append(export_doctype(doctype, archive_path))

	custom_field_rows = frappe.get_all(
		"Custom Field",
		filters={"name": ["in", [row.name for row in plan["allowlisted_custom_fields"]]]},
		fields=["*"],
		order_by="name",
	)
	exports.append(
		export_rows("Custom Field Allowlist", custom_field_rows, archive_path, source_module="Custom")
	)
	exports.extend(export_custom_field_values(plan["allowlisted_custom_fields"], archive_path))

	property_setter_rows = frappe.get_all(
		"Property Setter",
		filters={"name": ["in", [row.name for row in plan["allowlisted_property_setters"]]]},
		fields=["*"],
		order_by="name",
	)
	exports.append(
		export_rows(
			"Property Setter Allowlist",
			property_setter_rows,
			archive_path,
			source_module="Custom",
		)
	)

	manifest = {
		"site": frappe.local.site,
		"created_at": now_datetime(),
		"legacy_apps": plan["legacy_apps"],
		"installed_legacy_apps": plan["installed_legacy_apps"],
		"runtime_registry_legacy_apps": plan["runtime_registry_legacy_apps"],
		"legacy_modules": plan["legacy_modules"],
		"record_counts": plan["record_counts"],
		"expected_orphan_counts": plan["expected_orphan_counts"],
		"orphan_count_differences": plan["orphan_count_differences"],
		"shared_doctype_ownership": plan["shared_doctype_ownership"],
		"exports": exports,
	}
	manifest_bytes = canonical_json_bytes(manifest)
	manifest["manifest_checksum"] = hashlib.sha256(manifest_bytes).hexdigest()
	(archive_path / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
	return archive_path, manifest


def export_custom_field_values(custom_fields, archive_path):
	fields_by_doctype = {}
	for custom_field in custom_fields:
		fields_by_doctype.setdefault(custom_field.dt, []).append(custom_field.fieldname)

	exports = []
	for doctype, fieldnames in sorted(fields_by_doctype.items()):
		columns = set(frappe.db.get_table_columns(doctype))
		tracked_fields = sorted(set(fieldnames) & columns)
		if not tracked_fields:
			continue

		identity_fields = [
			fieldname
			for fieldname in ("name", "parent", "parenttype", "parentfield", "idx", "docstatus", "modified")
			if fieldname in columns
		]
		records = frappe.get_all(
			doctype,
			fields=[*identity_fields, *tracked_fields],
			order_by="name",
			limit_page_length=0,
		)
		populated_records = [
			record for record in records if any(has_legacy_value(record.get(field)) for field in tracked_fields)
		]
		if populated_records:
			exports.append(
				export_rows(
					f"{doctype} Legacy Custom Field Values",
					populated_records,
					archive_path,
					source_module="Custom",
				)
			)
	return exports


def has_legacy_value(value):
	return value not in (None, "", 0, False)


def export_doctype(doctype, archive_path):
	meta = frappe.get_meta(doctype)
	if meta.issingle:
		records = [frappe.get_single(doctype).as_dict(no_nulls=False)]
	else:
		records = frappe.get_all(doctype, fields=["*"], order_by="name")
	module = frappe.db.get_value("DocType", doctype, "module")
	links = extract_links(meta, records)
	return export_rows(doctype, records, archive_path, source_module=module, links=links)


def export_rows(label, records, archive_path, source_module=None, links=None):
	serializable_records = [dict(record) for record in records]
	payload = {
		"doctype": label,
		"source_module": source_module,
		"count": len(serializable_records),
		"links": links or [],
		"records": serializable_records,
	}
	checksum = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
	filename = frappe.scrub(label).replace("_", "-")
	json_file = archive_path / f"{filename}.json"
	csv_file = archive_path / f"{filename}.csv"
	json_file.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
	write_csv(csv_file, serializable_records)
	return {
		"doctype": label,
		"source_module": source_module,
		"count": len(serializable_records),
		"json": json_file.name,
		"csv": csv_file.name,
		"checksum": checksum,
	}


def write_csv(path, records):
	fieldnames = sorted({field for record in records for field in record}) or ["name"]
	with path.open("w", encoding="utf-8", newline="") as stream:
		writer = csv.DictWriter(stream, fieldnames=fieldnames)
		writer.writeheader()
		for record in records:
			writer.writerow({field: csv_value(record.get(field)) for field in fieldnames})


def csv_value(value):
	if isinstance(value, (dict, list, tuple)):
		return json.dumps(value, default=str, sort_keys=True)
	return value


def extract_links(meta, records):
	links = []
	for record in records:
		for field in meta.fields:
			if field.fieldtype == "Link" and record.get(field.fieldname):
				links.append(
					{
						"record": record.get("name"),
						"field": field.fieldname,
						"doctype": field.options,
						"name": record[field.fieldname],
					}
				)
			elif field.fieldtype == "Dynamic Link" and record.get(field.fieldname):
				links.append(
					{
						"record": record.get("name"),
						"field": field.fieldname,
						"doctype": record.get(field.options),
						"name": record[field.fieldname],
					}
				)
	return links


def canonical_json_bytes(value):
	return json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()


def ensure_pdc_module_ownership():
	if not frappe.db.exists("Module Def", "PDC"):
		frappe.get_doc(
			{"doctype": "Module Def", "module_name": "PDC", "app_name": "erpnext", "custom": 0}
		).insert(ignore_permissions=True)
	else:
		frappe.db.set_value("Module Def", "PDC", {"app_name": "erpnext", "custom": 0}, update_modified=False)

	for doctype in PDC_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			frappe.throw(f"Required shared PDC DocType {doctype} is missing.")
		frappe.db.set_value("DocType", doctype, "module", "PDC", update_modified=False)


def ensure_native_payment_entry_pdc_columns():
	add_column("Payment Entry", "is_pdc_entry", "Check", default=0, not_null=True)
	add_column("Payment Entry", "post_dated_cheque", "Link", length=140)


def migrate_legacy_payment_entry_pdc_fields():
	columns = set(frappe.db.get_table_columns("Payment Entry"))
	legacy_fields = [
		field
		for field in (
			"custom_is_pdc_entry",
			"pdc_cheque_number",
			"pdc_cheque_date",
			"pdc_cheque_status",
			"pdc_bank_account",
		)
		if field in columns
	]
	if not legacy_fields:
		return {"matched": 0, "updated": 0, "unlinked": []}

	fields = [
		"name",
		"company",
		"party_type",
		"party",
		"reference_no",
		"reference_date",
		"is_pdc_entry",
		"post_dated_cheque",
		*legacy_fields,
	]
	conditions = [f"IFNULL(`{field}`, '') != ''" for field in legacy_fields]
	rows = frappe.db.sql(
		f"SELECT {', '.join(f'`{field}`' for field in fields)} FROM `tabPayment Entry` WHERE {' OR '.join(conditions)}",
		as_dict=True,
	)
	updated = 0
	unlinked = []
	for row in rows:
		pdc_name = row.post_dated_cheque or find_matching_pdc(row)
		values = {
			"is_pdc_entry": cint(row.get("custom_is_pdc_entry") or row.is_pdc_entry or bool(pdc_name)),
			"post_dated_cheque": pdc_name,
			"reference_no": row.reference_no or row.get("pdc_cheque_number"),
			"reference_date": row.reference_date or row.get("pdc_cheque_date"),
		}
		frappe.db.set_value("Payment Entry", row.name, values, update_modified=False)
		if pdc_name and row.get("pdc_cheque_status"):
			status = PDC_STATUS_MAP.get(row.pdc_cheque_status)
			if status:
				frappe.db.set_value("Post Dated Cheques", pdc_name, "status", status, update_modified=False)
		if values["is_pdc_entry"] and not pdc_name:
			unlinked.append(row.name)
		updated += 1
	return {"matched": len(rows), "updated": updated, "unlinked": unlinked}


def find_matching_pdc(payment_entry):
	by_link = frappe.db.get_value("Post Dated Cheques", {"payment_entry": payment_entry.name}, "name")
	if by_link:
		return by_link

	filters = {
		"company": payment_entry.company,
		"party_type": payment_entry.party_type,
		"party": payment_entry.party,
		"reference_no": payment_entry.get("pdc_cheque_number") or payment_entry.reference_no,
	}
	if payment_entry.get("pdc_cheque_date") or payment_entry.reference_date:
		filters["reference_date"] = payment_entry.get("pdc_cheque_date") or payment_entry.reference_date
	if not filters["reference_no"]:
		return None
	return frappe.db.get_value("Post Dated Cheques", filters, "name", order_by="modified desc")


def migrate_pdc_statuses():
	updated = {}
	for source, target in PDC_STATUS_MAP.items():
		if source == target:
			continue
		count = frappe.db.count("Post Dated Cheques", {"status": source})
		if count:
			frappe.db.set_value(
				"Post Dated Cheques", {"status": source}, "status", target, update_modified=False
			)
			updated[f"{source} -> {target}"] = count
	return updated


def remove_allowlisted_custom_field_definitions():
	removed = []
	for doctype, fieldname in CUSTOM_FIELD_ALLOWLIST:
		name = f"{doctype}-{fieldname}"
		if frappe.db.exists("Custom Field", name):
			# Delete only metadata. Exact standard-field collisions must retain their physical
			# columns and values for the subsequent ERPNext schema sync.
			frappe.db.delete("Custom Field", {"name": name})
			removed.append(name)
	return removed


def remove_allowlisted_property_setters():
	removed = []
	for name in PROPERTY_SETTER_ALLOWLIST:
		if frappe.db.exists("Property Setter", name):
			frappe.db.delete("Property Setter", {"name": name})
			removed.append(name)
	return removed

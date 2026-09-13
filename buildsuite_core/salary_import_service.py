"""Transactional site operations for the approved DME 2026 salary import."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import frappe
from frappe.utils import getdate

from buildsuite_core.salary_import import (
	COMPANY,
	EFFECTIVE_DATE,
	EXPECTED_MISSING,
	EXPECTED_TOTALS,
	EmployeeRecord,
	calculate_totals,
	match_rows,
	normalize,
	parse_workbook,
	serialise_row,
)
from buildsuite_core.salary_import_audit import employee_master_sha256, write_audit

PAYROLL_PAYABLE = "456 - Payroll payable - DCI"
BANK_ACCOUNT = "Banks Current Accounts - DCI"
EXPENSE_ACCOUNTS = {
	"Basic": "Basic Salary - DCI",
	"HRA": "Housing/Rent Allowance - DCI",
	"Allowance": "Other Allowance - DCI",
}
NEW_EXPENSE_ACCOUNT_NAMES = {
	"HRA": "Housing/Rent Allowance",
	"Allowance": "Other Allowance",
}
LEGACY_ASSIGNMENTS = {
	"HR-SSA-26-07-00002",
	"HR-SSA-26-07-00003",
	"HR-SSA-26-07-00004",
	"HR-SSA-26-07-00005",
}
LEGACY_STRUCTURES = {"Abdul Khader", "Abdul Majeed", "Mhizty Xienne", "Moh. Rasool"}


def get_import_plan(workbook_path):
	rows, workbook_checksum = parse_workbook(workbook_path)
	employees = _get_employees()
	matches, missing, errors = match_rows(rows, employees)
	totals = calculate_totals(matches)
	errors.extend(_validate_expected(matches, missing, totals))
	errors.extend(_validate_site(matches))
	employee_by_name = {employee.name: employee for employee in employees}
	mapping = []
	for row, employee_id in matches:
		employee = employee_by_name[employee_id]
		mapping.append(
			{
				**serialise_row(row),
				"employee": employee_id,
				"erp_employee_name": employee.employee_name,
				"effective_date": str(max(EFFECTIVE_DATE, getdate(employee.joining_date or EFFECTIVE_DATE))),
				"structure": structure_name(employee_id),
			}
		)
	return {
		"operation": "DME 2026 employee salary import",
		"site": frappe.local.site,
		"workbook": str(Path(workbook_path).expanduser().resolve()),
		"workbook_sha256": workbook_checksum,
		"employee_master_sha256": employee_master_sha256(),
		"mapping": mapping,
		"missing_employee_masters": [serialise_row(row) for row in missing],
		"skipped_rows": [serialise_row(row) for row in missing],
		"matched_wps_missing_erp_iban": [
			{"row": row.row, "employee": employee_id, "employee_name": employee_by_name[employee_id].employee_name}
			for row, employee_id in matches
			if row.mode == "WPS" and not employee_by_name[employee_id].iban
		],
		"totals": _serialise_totals(totals),
		"planned_setup": {
			"expense_accounts": EXPENSE_ACCOUNTS,
			"payroll_payable_account": PAYROLL_PAYABLE,
			"WPS_payment_account": BANK_ACCOUNT,
		},
		"validation_errors": errors,
		"ready_to_apply": not errors,
	}


def apply_salary_import(workbook_path, allow_production=False):
	if "uat" not in frappe.local.site and not allow_production:
		frappe.throw("Use --allow-production to apply the salary import outside a UAT site")
	plan = get_import_plan(workbook_path)
	if plan["validation_errors"]:
		frappe.throw("Salary import preflight failed:\n" + "\n".join(plan["validation_errors"]))
	employee_snapshot = plan["employee_master_sha256"]
	result = {"created": {"accounts": [], "modes_of_payment": [], "structures": [], "assignments": []}, "cancelled": {"structures": [], "assignments": []}, "unchanged": []}
	_ensure_accounts(result)
	_ensure_modes_of_payment(result)
	_configure_salary_component_accounts()
	_cancel_legacy_documents(result)
	for mapping in plan["mapping"]:
		_ensure_salary_structure(mapping, result)
		_ensure_assignment(mapping, result)
	_verify_applied_state(plan)
	if employee_master_sha256() != employee_snapshot:
		frappe.throw("Employee master data changed during the payroll import")
	plan.update(result)
	plan["applied_at"] = datetime.now().astimezone().isoformat()
	plan["import_complete"] = True
	plan["audit_path"] = write_audit(plan)
	return plan


def structure_name(employee_id):
	return f"DME Salary 2026 - {employee_id}"


def _get_employees():
	rows = frappe.get_all(
		"Employee",
		filters={"company": COMPANY, "status": "Active"},
		fields=["name", "employee_name", "iban", "custom_labour_card_no_", "date_of_joining"],
	)
	return [
		EmployeeRecord(
			name=row.name,
			employee_name=row.employee_name,
			iban=row.iban or "",
			labour_card=row.custom_labour_card_no_ or "",
			joining_date=getdate(row.date_of_joining) if row.date_of_joining else None,
		)
		for row in rows
	]


def _validate_expected(matches, missing, totals):
	errors = []
	missing_names = {normalize(row.name) for row in missing}
	if missing_names != EXPECTED_MISSING:
		errors.append(f"Missing Employee masters changed: {sorted(missing_names)}")
	if len({employee for _, employee in matches}) != len(matches):
		errors.append("More than one workbook row maps to the same Employee")
	for key, expected in EXPECTED_TOTALS.items():
		if totals[key] != expected:
			errors.append(f"Expected {key}={expected}, found {totals[key]}")
	return errors


def _validate_site(matches):
	errors = []
	for doctype in ("Salary Slip", "Payroll Entry"):
		if frappe.db.count(doctype):
			errors.append(f"{doctype} records now exist; legacy payroll cancellation is unsafe")
	for name in (PAYROLL_PAYABLE, BANK_ACCOUNT, "Basic Salary - DCI", "Personnel Cost - DCI"):
		if not frappe.db.exists("Account", name):
			errors.append(f"Required Account is missing: {name}")
	for account in set(EXPENSE_ACCOUNTS.values()) & set(frappe.get_all("Account", pluck="name")):
		values = frappe.db.get_value("Account", account, ["root_type", "is_group", "parent_account"], as_dict=True)
		if values.root_type != "Expense" or values.is_group or values.parent_account != "Personnel Cost - DCI":
			errors.append(f"Expense Account has an unexpected chart position: {account}")
	for component in EXPENSE_ACCOUNTS:
		if not frappe.db.exists("Salary Component", component):
			errors.append(f"Required Salary Component is missing: {component}")
	if frappe.db.exists("Mode of Payment", "Cash"):
		cash = frappe.get_doc("Mode of Payment", "Cash")
		if not next((row.default_account for row in cash.accounts if row.company == COMPANY), None):
			errors.append(f"Cash Mode of Payment has no default account for {COMPANY}")
	else:
		errors.append("Existing Cash Mode of Payment is missing")
	allowed = LEGACY_ASSIGNMENTS | set()
	for _, employee in matches:
		target = structure_name(employee)
		joining_date = frappe.db.get_value("Employee", employee, "date_of_joining")
		expected_date = max(EFFECTIVE_DATE, getdate(joining_date or EFFECTIVE_DATE))
		for assignment in frappe.get_all("Salary Structure Assignment", {"employee": employee, "docstatus": 1}, ["name", "salary_structure", "from_date"]):
			is_target = assignment.salary_structure == target and getdate(assignment.from_date) == expected_date
			if assignment.name not in allowed and not is_target:
				errors.append(f"Unexpected submitted assignment {assignment.name} for {employee}")
	return errors


def _ensure_accounts(result):
	for component, account_name in NEW_EXPENSE_ACCOUNT_NAMES.items():
		expected = EXPENSE_ACCOUNTS[component]
		if frappe.db.exists("Account", expected):
			continue
		doc = frappe.get_doc({"doctype": "Account", "account_name": account_name, "parent_account": "Personnel Cost - DCI", "company": COMPANY, "is_group": 0, "root_type": "Expense"})
		doc.flags.ignore_permissions = True
		doc.insert()
		if doc.name != expected:
			frappe.throw(f"Created account {doc.name}, expected {expected}")
		result["created"]["accounts"].append(doc.name)


def _ensure_modes_of_payment(result):
	if not frappe.db.exists("Mode of Payment", "WPS"):
		doc = frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": "WPS", "type": "Bank", "enabled": 1, "accounts": [{"company": COMPANY, "default_account": BANK_ACCOUNT}]})
		doc.flags.ignore_permissions = True
		doc.insert()
		result["created"]["modes_of_payment"].append("WPS")
	else:
		doc = frappe.get_doc("Mode of Payment", "WPS")
		account = next((row.default_account for row in doc.accounts if row.company == COMPANY), None)
		if doc.type != "Bank" or not doc.enabled or account != BANK_ACCOUNT:
			frappe.throw("Existing WPS Mode of Payment does not match the approved configuration")
	if not frappe.db.exists("Mode of Payment", "Cash"):
		frappe.throw("Existing Cash Mode of Payment is missing")


def _configure_salary_component_accounts():
	for component, account in EXPENSE_ACCOUNTS.items():
		doc = frappe.get_doc("Salary Component", component)
		if [row.account for row in doc.accounts if row.company == COMPANY] == [account]:
			continue
		other_companies = [row.as_dict() for row in doc.accounts if row.company != COMPANY]
		doc.set("accounts", other_companies + [{"company": COMPANY, "account": account}])
		doc.flags.ignore_permissions = True
		doc.save()


def _cancel_legacy_documents(result):
	for name in sorted(LEGACY_ASSIGNMENTS):
		if frappe.db.exists("Salary Structure Assignment", name):
			doc = frappe.get_doc("Salary Structure Assignment", name)
			if doc.docstatus == 1:
				doc.flags.ignore_permissions = True
				doc.cancel()
				result["cancelled"]["assignments"].append(name)
	for name in sorted(LEGACY_STRUCTURES):
		if frappe.db.exists("Salary Structure", name):
			doc = frappe.get_doc("Salary Structure", name)
			if doc.docstatus == 1:
				doc.flags.ignore_permissions = True
				doc.cancel()
				result["cancelled"]["structures"].append(name)


def _ensure_salary_structure(mapping, result):
	name = mapping["structure"]
	if frappe.db.exists("Salary Structure", name):
		doc = frappe.get_doc("Salary Structure", name)
		_assert_structure(doc, mapping)
		result["unchanged"].append(name)
		return
	payment_account = BANK_ACCOUNT if mapping["mode"] == "WPS" else _mode_account("Cash")
	doc = frappe.get_doc({"doctype": "Salary Structure", "name": name, "company": COMPANY, "currency": "AED", "is_active": "Yes", "payroll_frequency": "Monthly", "mode_of_payment": mapping["mode"], "payment_account": payment_account, "earnings": [{"salary_component": "Basic", "amount": mapping["basic"]}, {"salary_component": "HRA", "amount": mapping["hra"]}, {"salary_component": "Allowance", "amount": mapping["allowance"]}]})
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()
	result["created"]["structures"].append(name)


def _assert_structure(doc, mapping):
	expected = {"Basic": Decimal(mapping["basic"]), "HRA": Decimal(mapping["hra"]), "Allowance": Decimal(mapping["allowance"])}
	actual = {row.salary_component: Decimal(str(row.amount)).quantize(Decimal("0.01")) for row in doc.earnings}
	expected_payment_account = BANK_ACCOUNT if mapping["mode"] == "WPS" else _mode_account("Cash")
	if doc.docstatus != 1 or doc.company != COMPANY or doc.currency != "AED" or doc.mode_of_payment != mapping["mode"] or doc.payment_account != expected_payment_account or actual != expected:
		frappe.throw(f"Existing Salary Structure conflicts with import: {doc.name}")


def _ensure_assignment(mapping, result):
	existing = frappe.get_all("Salary Structure Assignment", {"employee": mapping["employee"], "salary_structure": mapping["structure"], "from_date": mapping["effective_date"], "docstatus": 1}, pluck="name")
	if existing:
		doc = frappe.get_doc("Salary Structure Assignment", existing[0])
		if doc.company != COMPANY or doc.currency != "AED" or doc.payroll_payable_account != PAYROLL_PAYABLE:
			frappe.throw(f"Existing Salary Structure Assignment conflicts with import: {doc.name}")
		result["unchanged"].append(doc.name)
		return
	doc = frappe.get_doc({"doctype": "Salary Structure Assignment", "employee": mapping["employee"], "salary_structure": mapping["structure"], "from_date": mapping["effective_date"], "company": COMPANY, "currency": "AED", "payroll_payable_account": PAYROLL_PAYABLE})
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()
	result["created"]["assignments"].append(doc.name)


def _mode_account(mode):
	doc = frappe.get_doc("Mode of Payment", mode)
	account = next((row.default_account for row in doc.accounts if row.company == COMPANY), None)
	if not account:
		frappe.throw(f"{mode} has no default account for {COMPANY}")
	return account


def _verify_applied_state(plan):
	if frappe.db.count("Salary Structure", {"name": ["like", "DME Salary 2026 - HR-EMP-%"], "docstatus": 1}) != 67:
		frappe.throw("Post-import validation did not find 67 submitted Salary Structures")
	for mapping in plan["mapping"]:
		_assert_structure(frappe.get_doc("Salary Structure", mapping["structure"]), mapping)
		if not frappe.db.exists("Salary Structure Assignment", {"employee": mapping["employee"], "salary_structure": mapping["structure"], "from_date": mapping["effective_date"], "docstatus": 1}):
			frappe.throw(f"Submitted assignment validation failed for {mapping['employee']}")
	for component, account in EXPENSE_ACCOUNTS.items():
		doc = frappe.get_doc("Salary Component", component)
		if [row.account for row in doc.accounts if row.company == COMPANY] != [account]:
			frappe.throw(f"Salary Component account validation failed for {component}")


def _serialise_totals(totals):
	return {key: str(value) if isinstance(value, Decimal) else value for key, value in totals.items()}

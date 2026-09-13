"""Private, checksummed audit support for the DME salary import."""

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import frappe

from buildsuite_core.salary_import import COMPANY


def employee_master_sha256():
	fields = [
		"name", "modified", "employee_name", "iban", "bank_ac_no", "bank_name",
		"custom_labour_card_no_", "custom_labour_cr_no", "designation", "department",
		"branch", "date_of_joining",
	]
	rows = frappe.get_all("Employee", filters={"company": COMPANY}, fields=fields, order_by="name")
	payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode()
	return hashlib.sha256(payload).hexdigest()


def write_audit(payload):
	timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
	directory = Path(frappe.get_site_path("private", "files", "buildsuite_salary_import", timestamp))
	path = directory / "audit.json"
	try:
		directory.mkdir(parents=True, exist_ok=False)
		copy = dict(payload)
		copy.pop("audit_path", None)
		canonical = json.dumps(copy, sort_keys=True, separators=(",", ":"), default=str).encode()
		copy["audit_sha256"] = hashlib.sha256(canonical).hexdigest()
		path.write_text(json.dumps(copy, indent=2, sort_keys=True, default=str) + "\n")
		os.chmod(directory, 0o700)
		os.chmod(path, 0o600)
	except Exception:
		path.unlink(missing_ok=True)
		if directory.exists():
			directory.rmdir()
		raise
	return str(path)


def remove_audit(path):
	audit_path = Path(path)
	audit_path.unlink(missing_ok=True)
	if audit_path.parent.exists():
		audit_path.parent.rmdir()

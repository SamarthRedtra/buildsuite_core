"""Private source attachment and audit files for the waterproofing import."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import frappe
from frappe.utils.file_manager import save_file


def _sha256(path):
	return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def attach_source(workbook_path, project, checksum):
	file_name = Path(workbook_path).name
	content = Path(workbook_path).read_bytes()
	# Frappe stores an MD5 content_hash for file de-duplication; SHA-256 is verified below.
	content_hash = hashlib.md5(content).hexdigest()
	matching_content = frappe.get_all("File", filters={"content_hash": content_hash}, pluck="file_url")
	for row in frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Project",
			"attached_to_name": project,
			"content_hash": content_hash,
		},
		fields=["name", "file_url", "is_private"],
	):
		path = frappe.get_site_path(row.file_url.lstrip("/"))
		if Path(path).exists() and _sha256(path) == checksum and row.is_private:
			return row.name, False, False
		frappe.throw(f"Conflicting Project attachment exists: {row.name}")
	doc = save_file(file_name, content, "Project", project, is_private=1)
	return doc.name, True, not matching_content


def write_audit(payload, project):
	copy = dict(payload)
	canonical = json.dumps(copy, sort_keys=True, separators=(",", ":"), default=str).encode()
	copy["payload_sha256"] = hashlib.sha256(canonical).hexdigest()
	timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
	name = f"waterproofing-import-audit-{timestamp}.json"
	content = (json.dumps(copy, indent=2, sort_keys=True, default=str) + "\n").encode()
	doc = save_file(
		name,
		content,
		"Project",
		project,
		is_private=1,
	)
	return {"file": doc.name, "file_url": doc.file_url, "sha256": hashlib.sha256(content).hexdigest()}


def remove_physical_file(file_url):
	if not file_url:
		return
	Path(frappe.get_site_path(file_url.lstrip("/"))).unlink(missing_ok=True)

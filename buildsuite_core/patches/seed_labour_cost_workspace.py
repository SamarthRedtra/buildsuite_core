# Copyright (c) 2026, Infraholic Innovations Pvt. Ltd and contributors
# For license information, please see license.txt

"""Expose Labour Cost Sheets inside the Redtra Suite Workforce workspace."""

from buildsuite_core.buildsuite_core.doctype.workspace_setting.seed_workspace_reports import (
	seed_workspace_doctypes,
)


def execute():
	seed_workspace_doctypes()

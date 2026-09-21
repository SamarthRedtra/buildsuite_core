# Copyright (c) 2026, Infraholic Innovations Pvt. Ltd and contributors
# For license information, please see license.txt

"""Apply Labour Cost Sheet permissions to existing sites after its DocTypes are synced."""

from buildsuite_core.permissions.setup import (
	setup_child_table_read_access,
	setup_workforce_permissions,
)


def execute():
	setup_workforce_permissions()
	setup_child_table_read_access()

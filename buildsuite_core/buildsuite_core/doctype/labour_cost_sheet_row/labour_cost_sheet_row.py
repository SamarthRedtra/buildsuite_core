# Copyright (c) 2026, Infraholic Innovations Pvt. Ltd and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LabourCostSheetRow(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		employee: DF.Link
		employee_name: DF.Data | None
		overtime_cost: DF.Currency
		overtime_hours: DF.Float
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		regular_cost: DF.Currency
		regular_days: DF.Float
		total_cost: DF.Currency
	# end: auto-generated types

	pass

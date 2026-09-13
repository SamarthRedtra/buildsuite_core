"""Shared rules for the Item Conversion / Dismantling stock-entry type."""

import frappe
from frappe import _
from frappe.utils import flt

ITEM_CONVERSION_TYPE = "Item Conversion / Dismantling"
ITEM_CONVERSION_PURPOSE = "Material Transfer"
ITEM_CONVERSION_ROUNDING_TOLERANCE = 1.0


def ensure_item_conversion_stock_entry_type():
	"""Keep the custom type available after the legacy app is retired."""
	if frappe.db.exists("Stock Entry Type", ITEM_CONVERSION_TYPE):
		doc = frappe.get_doc("Stock Entry Type", ITEM_CONVERSION_TYPE)
		if doc.purpose != ITEM_CONVERSION_PURPOSE or doc.is_standard:
			doc.purpose = ITEM_CONVERSION_PURPOSE
			doc.is_standard = 0
			doc.save(ignore_permissions=True)
		return doc.name

	doc = frappe.get_doc(
		{
			"doctype": "Stock Entry Type",
			"name": ITEM_CONVERSION_TYPE,
			"purpose": ITEM_CONVERSION_PURPOSE,
			"is_standard": 0,
		}
	).insert(ignore_permissions=True)
	return doc.name


def is_item_conversion(doc):
	return doc.get("stock_entry_type") == ITEM_CONVERSION_TYPE


def prepare_item_conversion(doc):
	"""Use the standard Material Transfer ledger with manually split output values."""
	if not is_item_conversion(doc):
		return

	doc.purpose = ITEM_CONVERSION_PURPOSE
	for item in doc.get("items") or []:
		item.is_finished_item = 0
		item.set_basic_rate_manually = 1


def validate_item_conversion_balance(doc):
	"""Require the dismantled value to be fully allocated to output items."""
	if not is_item_conversion(doc):
		return

	precision = doc.precision("value_difference") or 2
	source_value, output_value = get_item_conversion_totals(doc)
	difference = flt(output_value - source_value, precision)
	if abs(difference) <= ITEM_CONVERSION_ROUNDING_TOLERANCE:
		return

	frappe.throw(
		_(
			"Total output valuation must equal total source valuation. "
			"Source: {0}, Output: {1}, Difference: {2}. "
			"Distribute the source value across output item Basic Rate fields."
		).format(source_value, output_value, difference)
	)


def get_item_conversion_totals(doc):
	source_value = 0.0
	output_value = 0.0
	for item in doc.get("items") or []:
		line_value = flt(item.basic_amount) or flt(item.amount)
		if item.s_warehouse and not item.t_warehouse:
			source_value += line_value
		elif item.t_warehouse and not item.s_warehouse:
			output_value += line_value

	return (
		flt(source_value, doc.precision("total_outgoing_value") or 2),
		flt(output_value, doc.precision("total_incoming_value") or 2),
	)

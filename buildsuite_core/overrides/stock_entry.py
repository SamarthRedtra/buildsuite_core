"""ERPNext Stock Entry extension for balanced item conversions."""

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry
from erpnext.stock.doctype.stock_entry.stock_entry_handler.base import BaseStockEntry
from erpnext.stock.utils import get_incoming_rate
from frappe import _
from frappe.utils import flt

from buildsuite_core.utils.item_conversion import (
	ITEM_CONVERSION_ROUNDING_TOLERANCE,
	is_item_conversion,
	prepare_item_conversion,
	validate_item_conversion_balance,
)


class ItemConversionStockEntry(BaseStockEntry):
	"""Validate split source/output rows without Material Transfer's row pairing."""

	def validate(self):
		source_rows = [item for item in self.doc.items if item.s_warehouse and not item.t_warehouse]
		output_rows = [item for item in self.doc.items if item.t_warehouse and not item.s_warehouse]
		if not source_rows:
			frappe.throw(_("Item Conversion / Dismantling requires at least one Source Warehouse row."))
		if not output_rows:
			frappe.throw(_("Item Conversion / Dismantling requires at least one Target Warehouse row."))

		for item in self.doc.items:
			if item.s_warehouse and item.t_warehouse:
				frappe.throw(
					_(
						"Row {0}: use Source Warehouse for the dismantled item or "
						"Target Warehouse for output items, not both."
					).format(item.idx)
				)
			if not item.s_warehouse and not item.t_warehouse:
				frappe.throw(_("Row {0}: select a Source Warehouse or Target Warehouse.").format(item.idx))


class BuildSuiteStockEntry(StockEntry):
	"""Run Item Conversion through native Stock Entry posting and ledger logic."""

	def _configure_purpose_class(self):
		super()._configure_purpose_class()
		if is_item_conversion(self):
			self.purpose_cls = ItemConversionStockEntry

	def before_validate(self):
		prepare_item_conversion(self)
		super().before_validate()

	def validate(self):
		super().validate()
		validate_item_conversion_balance(self)

	def set_basic_rate(self, reset_outgoing_rate=True, raise_error_if_no_rate=True):
		if not is_item_conversion(self):
			return super().set_basic_rate(reset_outgoing_rate, raise_error_if_no_rate)

		self.set_rate_for_outgoing_items(reset_outgoing_rate, raise_error_if_no_rate)
		self._sync_item_conversion_incoming_amounts()

	def set_rate_for_outgoing_items(self, reset_outgoing_rate=True, raise_error_if_no_rate=True):
		if not is_item_conversion(self):
			return super().set_rate_for_outgoing_items(reset_outgoing_rate, raise_error_if_no_rate)

		outgoing_items_cost = 0.0
		for item in self.items:
			if not item.s_warehouse:
				continue

			if reset_outgoing_rate and not item.set_basic_rate_manually:
				rate = get_incoming_rate(self.get_args_for_incoming_rate(item), raise_error_if_no_rate)
				if rate >= 0:
					item.basic_rate = rate

			item.basic_amount = flt(
				flt(item.transfer_qty) * flt(item.basic_rate), item.precision("basic_amount")
			)
			if not item.t_warehouse:
				outgoing_items_cost += flt(item.basic_amount)

		return outgoing_items_cost

	def _sync_item_conversion_incoming_amounts(self):
		output_rows = []
		source_value = 0.0
		amount_precision = self.precision("value_difference") or 2
		for item in self.items:
			if item.s_warehouse and not item.t_warehouse:
				source_value += flt(item.basic_amount)
				continue
			if not item.t_warehouse or item.s_warehouse:
				continue

			item.basic_amount = flt(
				flt(item.transfer_qty) * flt(item.basic_rate), item.precision("basic_amount")
			)
			output_rows.append(item)

		if not output_rows or not source_value:
			return

		output_value = sum(flt(item.basic_amount) for item in output_rows)
		difference = flt(source_value - output_value, amount_precision)
		if not difference or abs(difference) > ITEM_CONVERSION_ROUNDING_TOLERANCE:
			return

		last_row = output_rows[-1]
		last_row.basic_amount = flt(last_row.basic_amount + difference, last_row.precision("basic_amount"))
		if flt(last_row.transfer_qty):
			last_row.basic_rate = flt(
				last_row.basic_amount / flt(last_row.transfer_qty), last_row.precision("basic_rate")
			)

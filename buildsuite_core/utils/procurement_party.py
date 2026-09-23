# Copyright (c) 2026, Infraholic Innovations Pvt. Ltd and contributors
# For license information, please see license.txt

"""Party type / party / party name for procurement Stock Entry and Material Request."""

import frappe
from frappe import _

PARTY_TYPES = ("Supplier", "Customer", "Employee")

_NAME_FIELD = {
	"Supplier": "supplier_name",
	"Customer": "customer_name",
	"Employee": "employee_name",
}


def resolve_party_name(party_type, party):
	"""Display name for the selected party, or None when incomplete."""
	if not party_type or not party or party_type not in PARTY_TYPES:
		return None
	field = _NAME_FIELD[party_type]
	return frappe.db.get_value(party_type, party, field) or party


def apply_party_fields(doc, party_type=None, party=None):
	"""Validate and set custom_party_type / custom_party / custom_party_name.

	Both blank clears the party. Type without party (or vice versa) throws.
	"""
	party_type = (party_type or "").strip() or None
	party = (party or "").strip() or None

	if party_type and party_type not in PARTY_TYPES:
		frappe.throw(
			_("Party type must be one of: {0}.").format(", ".join(PARTY_TYPES))
		)
	if party_type and not party:
		frappe.throw(_("Pick a party when party type is set."))
	if party and not party_type:
		frappe.throw(_("Pick a party type when a party is set."))

	if party_type and party and not frappe.db.exists(party_type, party):
		frappe.throw(_("{0} {1} was not found.").format(party_type, party))

	doc.custom_party_type = party_type or ""
	doc.custom_party = party or ""
	doc.custom_party_name = resolve_party_name(party_type, party) or ""


@frappe.whitelist()
def get_party_name(party_type: str | None = None, party: str | None = None):
	"""Desk / SPA helper to fetch the display name for a party pick."""
	return resolve_party_name(party_type, party) or ""

frappe.provide("erpnext.stock");
frappe.provide("erpnext.accounts.dimensions");

const ITEM_CONVERSION_TYPE = "Item Conversion / Dismantling";

function isItemConversion(frm) {
	return frm.doc.stock_entry_type === ITEM_CONVERSION_TYPE;
}

function warehouseFilters(frm) {
	const filters = { is_group: 0 };
	if (frm.doc.company) filters.company = frm.doc.company;
	return filters;
}

function configureWarehouseQueries(frm) {
	frm.set_query("from_warehouse", () => ({ filters: warehouseFilters(frm) }));
	frm.set_query("to_warehouse", () => ({ filters: warehouseFilters(frm) }));
	frm.set_query("s_warehouse", "items", () => ({ filters: warehouseFilters(frm) }));
	frm.set_query("t_warehouse", "items", () => ({ filters: warehouseFilters(frm) }));
}

function configureItemConversionGrid(frm) {
	const grid = frm.fields_dict.items?.grid;
	if (!grid) return;

	const enabled = frm.doc.docstatus === 0 && isItemConversion(frm);
	grid.update_docfield_property("set_basic_rate_manually", "hidden", false);
	grid.update_docfield_property("set_basic_rate_manually", "in_list_view", enabled);
	grid.update_docfield_property("basic_rate", "in_list_view", true);
	grid.update_docfield_property(
		"basic_rate",
		"read_only",
		enabled ? false : frm.doc.purpose !== "Material Receipt"
	);
	grid.update_docfield_property("is_finished_item", "hidden", enabled);
}

function enableItemConversionRate(frm, cdt, cdn) {
	if (!isItemConversion(frm)) return;

	const row = locals[cdt]?.[cdn];
	if (!row?.item_code) return;

	frappe.model.set_value(cdt, cdn, "set_basic_rate_manually", 1);
	syncItemConversionLineAmount(frm, cdt, cdn);
}

function syncItemConversionLineAmount(frm, cdt, cdn) {
	if (!isItemConversion(frm)) return;

	const row = locals[cdt]?.[cdn];
	if (!row?.t_warehouse || row.s_warehouse) return;

	const basicAmount = flt(row.transfer_qty) * flt(row.basic_rate);
	frappe.model.set_value(cdt, cdn, "basic_amount", basicAmount);
	frappe.model.set_value(cdt, cdn, "amount", basicAmount);
}

function enableItemConversionRates(frm) {
	(frm.doc.items || []).forEach((row) => {
		enableItemConversionRate(frm, row.doctype, row.name);
	});
}

function validateItemConversionWarehouses(frm) {
	if (!isItemConversion(frm)) return;

	(frm.doc.items || []).forEach((row) => {
		if (row.s_warehouse && row.t_warehouse) {
			frappe.throw(
				__(
					"Row {0}: use Source Warehouse for the dismantled item or Target Warehouse for output items, not both.",
					[row.idx]
				)
			);
		}
	});
}

function syncPartyName(frm) {
	if (!frm.doc.custom_party_type || !frm.doc.custom_party) {
		frm.set_value("custom_party_name", "");
		return;
	}
	frappe.call({
		method: "buildsuite_core.utils.procurement_party.get_party_name",
		args: { party_type: frm.doc.custom_party_type, party: frm.doc.custom_party },
		callback(r) {
			frm.set_value("custom_party_name", r.message || "");
		},
	});
}

frappe.ui.form.on("Stock Entry", {
	refresh(frm) {
		configureWarehouseQueries(frm);
		configureItemConversionGrid(frm);
	},

	stock_entry_type(frm) {
		configureItemConversionGrid(frm);
		enableItemConversionRates(frm);
	},

	validate(frm) {
		validateItemConversionWarehouses(frm);
	},

	custom_party_type(frm) {
		frm.set_value("custom_party", "");
		frm.set_value("custom_party_name", "");
	},

	custom_party(frm) {
		syncPartyName(frm);
	},

	project(frm) {
		configureWarehouseQueries(frm);
		if (frm.doc.project) {
			(frm.doc.items || []).forEach((item) => {
				frappe.model.set_value(item.doctype, item.name, "project", frm.doc.project);
			});
			frm.refresh_field("items");

			frappe.call({
				method: "buildsuite_core.utils.stock_entry.get_warehouse_from_project",
				args: { project: frm.doc.project },
				callback(r) {
					if (!r.message) return;
					if (frm.doc.purpose === "Material Issue") {
						frm.set_value("from_warehouse", r.message);
						frm.set_value("to_warehouse", null);
					}
					if (frm.doc.purpose === "Material Receipt") {
						frm.set_value("to_warehouse", r.message);
						frm.set_value("from_warehouse", null);
					}
				},
			});
		} else {
			frm.set_value("from_warehouse", null);
			frm.set_value("to_warehouse", null);
		}
	},
});

frappe.ui.form.on("Stock Entry Detail", {
	item_code(frm, cdt, cdn) {
		enableItemConversionRate(frm, cdt, cdn);
	},

	s_warehouse(frm, cdt, cdn) {
		if (frm.doc.purpose === "Material Issue") {
			frappe.model.set_value(cdt, cdn, "t_warehouse", null);
		}
		frappe.model.set_value(cdt, cdn, "project", frm.doc.project);
		enableItemConversionRate(frm, cdt, cdn);
	},

	t_warehouse(frm, cdt, cdn) {
		if (frm.doc.purpose === "Material Receipt") {
			frappe.model.set_value(cdt, cdn, "s_warehouse", null);
		}
		frappe.model.set_value(cdt, cdn, "project", frm.doc.project);
		enableItemConversionRate(frm, cdt, cdn);
	},

	basic_rate(frm, cdt, cdn) {
		syncItemConversionLineAmount(frm, cdt, cdn);
	},

	qty(frm, cdt, cdn) {
		syncItemConversionLineAmount(frm, cdt, cdn);
	},

	transfer_qty(frm, cdt, cdn) {
		syncItemConversionLineAmount(frm, cdt, cdn);
	},

	project(frm, cdt, cdn) {
		erpnext.utils.copy_value_in_all_rows(frm.doc, cdt, cdn, "items", "project");
	},
});

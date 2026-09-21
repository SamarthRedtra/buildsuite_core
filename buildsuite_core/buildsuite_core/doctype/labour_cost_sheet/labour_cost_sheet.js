// Copyright (c) 2026, Infraholic Innovations Pvt. Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Labour Cost Sheet", {
	setup(frm) {
		frm.set_query("expense_account", () => ({
			filters: { company: frm.doc.company, is_group: 0, root_type: "Expense" },
		}));
		frm.set_query("credit_account", () => ({
			filters: { company: frm.doc.company, is_group: 0, root_type: ["in", ["Asset", "Liability"]] },
		}));
		frm.set_query("cost_center", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
	},

	refresh(frm) {
		if (frm.is_new()) {
			frm.dashboard.set_headline_alert(
				__("Choose a project, period and accounts. Saving collects all unprocessed submitted attendance in that period."),
				"blue"
			);
		} else if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Reload Attendance"), () => frm.save());
		}
		if (frm.doc.docstatus === 0 && frm.doc.project) {
			frm.add_custom_button(__("Choose BOQ Cost Code"), () => choose_cost_code(frm));
			if (frm.doc.cost_code_type) {
				frm.add_custom_button(__("Clear BOQ Cost Code"), () => {
					frm.set_value({
						cost_code_type: "",
						cost_code_group: "",
						cost_code_item: "",
						cost_code_label: "",
					});
				});
			}
		}

		if (frm.doc.journal_entry) {
			frm.add_custom_button(__("Open Journal Entry"), () => {
				frappe.set_route("Form", "Journal Entry", frm.doc.journal_entry);
			});
		}
	},

	project(frm) {
		if (!frm.doc.project) return;
		frappe.db.get_value("Project", frm.doc.project, "company").then(({ message }) => {
			frm.set_value("company", message?.company || "");
		});
	},
});

async function choose_cost_code(frm) {
	const { message: codes = [] } = await frappe.call({
		method: "buildsuite_core.api.subcontract.get_project_cost_codes",
		args: { project: frm.doc.project },
	});
	if (!codes.length) {
		frappe.msgprint(__("This project has no approved BOQ cost codes."));
		return;
	}

	const labels = codes.map((code, index) => `${index + 1}. ${code.label}`);
	const dialog = new frappe.ui.Dialog({
		title: __("Choose BOQ Cost Code"),
		fields: [
			{
				fieldname: "selection",
				fieldtype: "Select",
				label: __("Cost Code"),
				options: labels,
				reqd: 1,
			},
		],
		primary_action_label: __("Choose"),
		primary_action(values) {
			const index = labels.indexOf(values.selection);
			const code = codes[index];
			frm.set_value({
				cost_code_type: code.type,
				cost_code_group: code.group_code || "",
				cost_code_item: code.item_code || "",
				cost_code_label: code.label,
			});
			dialog.hide();
		},
	});
	dialog.show();
}

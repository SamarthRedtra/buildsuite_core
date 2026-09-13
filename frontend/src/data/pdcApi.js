import { frappeRequest } from "frappe-ui-frappe-request";
import { parseFrappeError } from "@/utils/frappeError";

async function call(method, args) {
	try {
		return await frappeRequest({
			url: `buildsuite_core.api.pdc.${method}`,
			params: args || {},
		});
	} catch (err) {
		throw new Error(parseFrappeError(err).summary || "Request failed.");
	}
}

export const listPdcs = (args = {}) => call("list_pdcs", args);
export const getPdc = (name) => call("get_pdc", { name });
export const savePdc = (payload) => call("save_pdc", { payload: JSON.stringify(payload) });
export const submitPdc = (name) => call("submit_pdc", { name });
export const availablePdcInvoices = (args) => call("available_invoice_balances", args);
export const presentPdc = (name) => call("present_pdc", { name });
export const clearPdc = (args) => call("clear_pdc", args);
export const bouncePdc = (name) => call("bounce_pdc", { name });
export const cancelPdc = (name) => call("cancel_pdc", { name });

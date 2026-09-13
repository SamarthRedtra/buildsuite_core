import { frappeRequest } from "frappe-ui-frappe-request";
import { parseFrappeError } from "@/utils/frappeError";

async function call(method, args) {
	try {
		return await frappeRequest({
			url: `buildsuite_core.api.manufacturing.${method}`,
			params: args || {},
		});
	} catch (err) {
		throw new Error(parseFrappeError(err).summary || "Request failed.");
	}
}

export const getManufacturingWorkspace = (args = {}) => call("get_manufacturing_workspace", args);
export const createWorkOrder = (args) => call("create_work_order", args);
export const submitWorkOrder = (name) => call("submit_work_order", { name });
export const createWorkOrderStockEntry = (args) => call("create_work_order_stock_entry", args);
export const submitStockEntry = (name) => call("submit_stock_entry", { name });
export const createProjectTransfer = (args) =>
	call("create_project_transfer", { ...args, items: JSON.stringify(args.items || []) });

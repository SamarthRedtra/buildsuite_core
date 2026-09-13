import { frappeRequest } from "frappe-ui-frappe-request";
import { parseFrappeError } from "@/utils/frappeError";

async function call(module, method, args) {
	try {
		return await frappeRequest({ url: `buildsuite_core.api.${module}.${method}`, params: args });
	} catch (err) {
		throw new Error(parseFrappeError(err).summary || "Request failed.");
	}
}

export const boqToSalesOrder = (boq, payload = {}) =>
	call("contract", "boq_to_sales_order", { boq, payload: JSON.stringify(payload) });
export const salesOrderToProgressInvoice = (salesOrder, billingPercentage, postingDate) =>
	call("contract", "sales_order_to_progress_invoice", {
		sales_order: salesOrder,
		billing_percentage: billingPercentage,
		posting_date: postingDate,
	});
export const getMaterialRequirements = (boq) =>
	call("material_planning", "get_material_requirements", { boq });
export const createBoqMaterialRequest = (boq, supplyMethod) =>
	call("material_planning", "create_material_request", { boq, supply_method: supplyMethod });

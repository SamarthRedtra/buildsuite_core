import { frappeRequest } from "frappe-ui-frappe-request";
import { parseFrappeError } from "@/utils/frappeError";

async function call(method, params = {}) {
	try {
		return await frappeRequest({
			url: `buildsuite_core.api.company.${method}`,
			method: "GET",
			params,
		});
	} catch (err) {
		throw new Error(parseFrappeError(err).summary || "Request failed.");
	}
}

// The logged-in user's default company (User → user default → site default).
export const getActiveCompany = () => call("active_company");
export const getActiveCompanyContext = () => call("active_company_context");
export const getCompanies = () => call("list_companies");

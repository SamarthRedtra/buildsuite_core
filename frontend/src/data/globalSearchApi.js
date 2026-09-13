import { frappeRequest } from "frappe-ui-frappe-request";
import { parseFrappeError } from "@/utils/frappeError";

export async function globalSearch(query) {
	try {
		return await frappeRequest({
			url: "buildsuite_core.api.global_search.global_search",
			method: "GET",
			params: { query },
		});
	} catch (error) {
		throw new Error(parseFrappeError(error).summary || "Search failed.");
	}
}

import { frappeRequest } from "frappe-ui-frappe-request";
import { parseFrappeError } from "@/utils/frappeError";

async function call(method, args) {
	try {
		return await frappeRequest({
			url: `buildsuite_core.api.retention.${method}`,
			params: args || {},
		});
	} catch (err) {
		throw new Error(parseFrappeError(err).summary || "Request failed.");
	}
}

export const listRetentionReleases = (args = {}) => call("list_retention_releases", args);
export const getRetentionRelease = (name) => call("get_retention_release", { name });
export const createRetentionRelease = (args) => call("create_retention_release", args);
export const submitRetentionRelease = (name) => call("submit_retention_release", { name });
export const cancelRetentionRelease = (name) => call("cancel_retention_release", { name });

// Whitelisted Task Progress Entry helpers (BOQ scope for quantity mode).

const BASE = "/api/method/buildsuite_core.api.task_progress.";

function serverMessage(payload, status) {
	try {
		const sm = payload?._server_messages;
		if (sm) {
			const first = JSON.parse(JSON.parse(sm)[0]);
			if (first?.message) return first.message;
		}
	} catch (_) {
		/* fall through */
	}
	return payload?.exception || `Request failed (${status})`;
}

async function request(method, body) {
	const res = await fetch(BASE + method, {
		method: "POST",
		credentials: "include",
		headers: {
			Accept: "application/json",
			"Content-Type": "application/json",
			"X-Frappe-CSRF-Token": window.csrf_token || "",
		},
		body: JSON.stringify(body || {}),
	});
	const payload = await res.json();
	if (!res.ok) throw new Error(serverMessage(payload, res.status));
	return payload.message;
}

export function getTaskProgressScope(task) {
	return request("get_task_progress_scope", { task });
}

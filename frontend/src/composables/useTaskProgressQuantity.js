import { ref, watch } from "vue";
import { getTaskProgressScope } from "@/utils/taskProgressApi";

/** BOQ scope + validation helpers for Percent vs Quantity progress entry. */
export function useTaskProgressQuantity(taskIdSource) {
	const progressInputMode = ref("Percent");
	const progressScope = ref(null);
	const scopeError = ref("");
	const scopeLoading = ref(false);

	function resolveTaskId() {
		const src = taskIdSource;
		return typeof src === "function" ? src() : src?.value;
	}

	async function loadScope() {
		const taskId = resolveTaskId();
		if (!taskId || progressInputMode.value !== "Quantity") {
			progressScope.value = null;
			scopeError.value = "";
			return;
		}
		scopeLoading.value = true;
		scopeError.value = "";
		try {
			progressScope.value = await getTaskProgressScope(taskId);
			if (!progressScope.value?.scope_qty) {
				scopeError.value = "No BOQ scope on this task — use percentage progress.";
			}
		} catch (err) {
			progressScope.value = null;
			scopeError.value = err.message || "Could not load BOQ scope.";
		} finally {
			scopeLoading.value = false;
		}
	}

	watch([() => resolveTaskId(), progressInputMode], loadScope, { immediate: true });

	const quantityFloor = () => Number(progressScope.value?.progress_floor_qty) || 0;

	const scopeHint = () => {
		const s = progressScope.value;
		if (!s?.scope_qty) return "";
		const uom = s.uom ? ` ${s.uom}` : "";
		return `Scope: ${s.scope_qty}${uom} from BOQ`;
	};

	return {
		progressInputMode,
		progressScope,
		scopeError,
		scopeLoading,
		quantityFloor,
		scopeHint,
		loadScope,
	};
}

export function progressEntryFieldErrors({
	mode,
	progressPct,
	cumulativeQty,
	progressFloor,
	quantityFloor,
	scopeQty,
	scopeError,
}) {
	const e = {};
	if (mode === "Quantity") {
		if (scopeError) {
			e.cumulativeQty = scopeError;
			return e;
		}
		if (!scopeQty) {
			e.cumulativeQty = "No BOQ scope — use percentage progress.";
			return e;
		}
		const q = Number(cumulativeQty);
		const floor = Number(quantityFloor) || 0;
		if (Number.isNaN(q) || q <= 0) {
			e.cumulativeQty = "Enter cumulative quantity greater than zero.";
		} else if (q <= floor) {
			e.cumulativeQty = `Quantity must increase — enter a value above ${floor}. Entries are cumulative.`;
		}
		return e;
	}

	const pct = Number(progressPct);
	const floorPct = Number(progressFloor) || 0;
	if (Number.isNaN(pct) || pct > 100) {
		e.progressPct = "Progress must be between 0 and 100";
	} else if (pct <= 0) {
		e.progressPct = "A progress entry can't be 0% — record the progress actually made.";
	} else if (pct <= floorPct) {
		e.progressPct = `Progress must increase — enter a value above the current ${floorPct}%. Entries are cumulative.`;
	}
	return e;
}

export function buildProgressEntryPayload(form) {
	const base = {
		task: form.taskId || form.task,
		entry_date: form.entryDate,
		progress_input_mode: form.progressInputMode || "Percent",
		narrative: form.narrative,
		skilled: Number(form.skilledLabour) || 0,
		unskilled: Number(form.unskilledLabour) || 0,
		weather: form.weather,
		blocker: form.blockerFlag ? 1 : 0,
		blocker_detail: form.blockerNote,
	};
	if (base.progress_input_mode === "Quantity") {
		base.cumulative_quantity = Number(form.cumulativeQty);
	} else {
		base.cumulative_progress = Number(form.progressPct);
	}
	return base;
}

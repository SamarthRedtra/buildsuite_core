<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { globalSearch } from "@/data/globalSearchApi";

const props = defineProps({ open: Boolean });
const emit = defineEmits(["update:open"]);
const router = useRouter();
const input = ref(null);
const query = ref("");
const groups = ref([]);
const loading = ref(false);
const error = ref("");
const selected = ref(0);
let timer;
let requestSequence = 0;

const results = computed(() => groups.value.flatMap((group) => group.results || []));
const hasSearched = computed(() => query.value.trim().length >= 2 && !loading.value);

function close() {
	emit("update:open", false);
}

function showPalette() {
	emit("update:open", true);
}

async function runSearch(term) {
	const sequence = ++requestSequence;
	loading.value = true;
	error.value = "";
	try {
		const response = await globalSearch(term);
		if (sequence !== requestSequence) return;
		groups.value = (response?.groups || []).filter((group) => group.results?.length);
		selected.value = 0;
	} catch (err) {
		if (sequence !== requestSequence) return;
		groups.value = [];
		error.value = err.message || "Search failed.";
	} finally {
		if (sequence === requestSequence) loading.value = false;
	}
}

watch(query, (value) => {
	clearTimeout(timer);
	const term = value.trim();
	if (term.length < 2) {
		requestSequence += 1;
		groups.value = [];
		loading.value = false;
		error.value = "";
		return;
	}
	timer = setTimeout(() => runSearch(term), 250);
});

watch(
	() => props.open,
	(value) => {
		if (value) nextTick(() => input.value?.focus());
		else query.value = "";
	},
);

function selectResult(result) {
	if (!result) return;
	close();
	router.push(result.route);
}

function onKeydown(event) {
	if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
		event.preventDefault();
		props.open ? close() : showPalette();
		return;
	}
	if (!props.open) return;
	if (
		event.key === "Escape" ||
		event.key === "Esc" ||
		event.code === "Escape" ||
		event.keyCode === 27
	) {
		event.preventDefault();
		close();
		return;
	}
	if (event.key === "ArrowDown" && results.value.length) {
		event.preventDefault();
		selected.value = (selected.value + 1) % results.value.length;
	}
	if (event.key === "ArrowUp" && results.value.length) {
		event.preventDefault();
		selected.value = (selected.value - 1 + results.value.length) % results.value.length;
	}
	if (event.key === "Enter") {
		event.preventDefault();
		selectResult(results.value[selected.value]);
	}
}

onMounted(() => window.addEventListener("keydown", onKeydown, true));
onBeforeUnmount(() => {
	clearTimeout(timer);
	window.removeEventListener("keydown", onKeydown, true);
});
</script>

<template>
	<div
		v-if="props.open"
		class="fixed inset-0 bg-ink-900/40 z-50 flex items-start justify-center pt-20"
		data-testid="global-search"
		@click="close"
	>
		<div
			class="bg-white rounded-lg shadow-fp-lg w-full max-w-lg border border-ink-200"
			@click.stop
		>
			<div class="p-3 border-b border-ink-200">
				<input
					ref="input"
					v-model="query"
					placeholder="Type to search projects, tasks, work packages..."
					class="w-full px-3 py-2 text-sm focus:outline-none"
					aria-label="Global search"
				/>
			</div>
			<div class="max-h-[60vh] overflow-y-auto p-2">
				<div v-if="query.trim().length < 2" class="p-3 text-xs text-ink-500">
					Enter at least two characters · ESC to close
				</div>
				<div v-else-if="loading" class="p-3 text-xs text-ink-500">Searching…</div>
				<div v-else-if="error" class="p-3 text-xs text-danger-600">{{ error }}</div>
				<div v-else-if="hasSearched && !results.length" class="p-3 text-xs text-ink-500">
					No matching projects, tasks, or work packages.
				</div>
				<div v-for="group in groups" :key="group.label" class="mb-2 last:mb-0">
					<div
						class="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-ink-400"
					>
						{{ group.label }}
					</div>
					<button
						v-for="result in group.results"
						:key="`${result.type}:${result.id}`"
						type="button"
						class="w-full px-3 py-2 text-left rounded hover:bg-ink-50"
						:class="results[selected] === result ? 'bg-brand-50' : ''"
						@click="selectResult(result)"
						@mouseenter="selected = results.indexOf(result)"
					>
						<div class="text-sm font-medium text-ink-900">{{ result.title }}</div>
						<div class="text-[11px] text-ink-500">{{ result.subtitle }}</div>
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

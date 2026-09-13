<script setup>
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import DeskPage from "@/components/desk/DeskPage.vue";
import DeskInput from "@/components/desk/DeskInput.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { listPdcs } from "@/data/pdcApi";
import { showToast } from "@/utils/appToast";
import { fmtDate, fmtINR } from "@/utils/format";

const rows = ref([]);
const loading = ref(true);
const direction = ref("");
const status = ref("");
const project = ref("");
const search = ref("");

const filtered = computed(() => {
	const needle = search.value.trim().toLowerCase();
	return rows.value.filter((row) => {
		if (direction.value && row.direction !== direction.value) return false;
		if (status.value && row.status !== status.value) return false;
		if (project.value && row.project !== project.value) return false;
		if (!needle) return true;
		return [row.name, row.party_name, row.party, row.reference_no, row.project]
			.filter(Boolean)
			.some((value) => String(value).toLowerCase().includes(needle));
	});
});
const projects = computed(() => [...new Set(rows.value.map((r) => r.project).filter(Boolean))]);

async function load() {
	loading.value = true;
	try {
		rows.value = await listPdcs();
	} catch (err) {
		showToast(err.message || "Failed to load PDC register", "error");
	} finally {
		loading.value = false;
	}
}
onMounted(load);
</script>

<template>
	<DeskPage
		title="Post-dated cheques"
		subtitle="Incoming and outgoing cheques. Pending and Presented rows are non-posting."
		:breadcrumbs="[{ label: 'Project Finance', to: '/project-finance' }, { label: 'PDC Register' }]"
	>
		<template #actions>
			<RouterLink to="/project-finance/pdc/new" class="desk-save-btn text-xs">New PDC</RouterLink>
		</template>
		<div class="flex flex-wrap gap-2 mb-4">
			<div class="w-56"><DeskInput v-model="search" placeholder="Search cheque or party…" /></div>
			<select v-model="direction" class="text-xs border border-ink-200 rounded-md px-2 py-1.5">
				<option value="">All directions</option><option>Incoming</option><option>Outgoing</option>
			</select>
			<select v-model="status" class="text-xs border border-ink-200 rounded-md px-2 py-1.5">
				<option value="">All statuses</option><option>Pending</option><option>Presented</option><option>Cleared</option><option>Bounced</option><option>Cancelled</option>
			</select>
			<select v-model="project" class="text-xs border border-ink-200 rounded-md px-2 py-1.5">
				<option value="">All projects</option><option v-for="p in projects" :key="p">{{ p }}</option>
			</select>
		</div>
		<div class="bg-white border border-ink-200 rounded-lg overflow-x-auto">
			<table class="w-full text-xs">
				<thead class="bg-ink-50 text-ink-500 uppercase tracking-wider text-[10px]"><tr><th class="text-left px-4 py-2">Cheque</th><th class="text-left px-4 py-2">Direction / party</th><th class="text-left px-4 py-2">Project</th><th class="text-left px-4 py-2">Date</th><th class="text-right px-4 py-2">Amount</th><th class="text-left px-4 py-2">Status</th></tr></thead>
				<tbody>
					<tr v-for="row in filtered" :key="row.name" class="border-t border-ink-100 hover:bg-ink-50">
						<td class="px-4 py-2"><RouterLink :to="`/project-finance/pdc/${row.name}`" class="font-mono text-brand-700 hover:underline">{{ row.reference_no || row.name }}</RouterLink><div class="text-[10px] text-ink-400">{{ row.name }}</div></td>
						<td class="px-4 py-2"><div class="font-medium text-ink-900">{{ row.direction }}</div><div class="text-ink-500">{{ row.party_name || row.party }}</div></td>
						<td class="px-4 py-2 text-ink-600">{{ row.project || "—" }}</td>
						<td class="px-4 py-2 text-ink-600">{{ fmtDate(row.reference_date) }}</td>
						<td class="px-4 py-2 text-right tabular-nums font-medium">{{ fmtINR(row.amount) }}</td>
						<td class="px-4 py-2"><StatusBadge :status="row.status" size="xs" /></td>
					</tr>
					<tr v-if="!loading && !filtered.length"><td colspan="6" class="px-4 py-10 text-center text-ink-400">No post-dated cheques match these filters.</td></tr>
				</tbody>
			</table>
			<div v-if="loading" class="px-4 py-10 text-center text-ink-400 text-sm">Loading…</div>
		</div>
	</DeskPage>
</template>

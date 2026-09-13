<script setup>
import { computed, onMounted, ref } from "vue";
import DeskPage from "@/components/desk/DeskPage.vue";
import DeskList from "@/components/desk/DeskList.vue";
import { getCompanies } from "@/data/companyApi";
import { getFrappeHost } from "@/utils/session";

const rows = ref([]);
const search = ref("");
const loading = ref(true);
const error = ref("");
const breadcrumbs = [
	{ label: "Redtra Suite", to: "/" },
	{ label: "Settings", to: "/settings" },
	{ label: "Companies" },
];
const columns = [
	{ key: "id", label: "Company" },
	{ key: "shortName", label: "Abbreviation" },
	{ key: "currency", label: "Currency" },
	{ key: "country", label: "Country" },
	{ key: "projects", label: "Projects", align: "right" },
	{ key: "active", label: "Status" },
];
const filtered = computed(() => {
	const term = search.value.trim().toLowerCase();
	return term
		? rows.value.filter((row) =>
				`${row.id} ${row.shortName} ${row.country}`.toLowerCase().includes(term),
			)
		: rows.value;
});

function deskUrl(path) {
	return `${getFrappeHost()}/app/${path}`;
}

function openCompany(row) {
	window.location.href = deskUrl(`company/${encodeURIComponent(row.id)}`);
}

onMounted(async () => {
	try {
		rows.value = await getCompanies();
	} catch (err) {
		error.value = err.message;
	} finally {
		loading.value = false;
	}
});
</script>

<template>
	<DeskPage title="Company" subtitle="Live ERPNext Company records" :breadcrumbs="breadcrumbs">
		<template #actions>
			<a :href="deskUrl('company/new-company')" class="desk-save-btn"
				>+ New Company in ERPNext</a
			>
		</template>
		<div v-if="loading" class="p-4 text-sm text-ink-500">Loading companies…</div>
		<div v-else-if="error" class="p-4 text-sm text-danger-600">{{ error }}</div>
		<DeskList
			v-else
			v-model="search"
			:rows="filtered"
			:columns="columns"
			row-key="id"
			search-placeholder="Search real ERPNext companies…"
			@row-click="openCompany"
		>
			<template #cell-id="{ row }"
				><span class="font-medium text-ink-900">{{ row.name }}</span></template
			>
			<template #cell-projects="{ row }"
				><span class="tabular-nums">{{ row.projectCount }}</span></template
			>
			<template #cell-active="{ row }">
				<span
					v-if="row.active"
					class="text-[10px] px-1.5 py-0.5 bg-brand-50 text-brand-700"
					>Active</span
				>
				<span v-else-if="row.disabled" class="text-[10px] text-danger-600">Disabled</span>
				<span v-else class="text-[10px] text-ink-500">ERPNext</span>
			</template>
		</DeskList>
	</DeskPage>
</template>

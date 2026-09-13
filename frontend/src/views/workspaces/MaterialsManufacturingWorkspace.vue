<script setup>
import { onMounted, ref, watch } from "vue";
import DeskPage from "@/components/desk/DeskPage.vue";
import DeskField from "@/components/desk/DeskField.vue";
import DeskInput from "@/components/desk/DeskInput.vue";
import DeskLinkPicker from "@/components/desk/DeskLinkPicker.vue";
import DeskLink from "@/components/desk/DeskLink.vue";
import { createWorkOrder, createWorkOrderStockEntry, getManufacturingWorkspace } from "@/data/manufacturingApi";
import { showToast } from "@/utils/appToast";
import { fmtDate, fmtINR } from "@/utils/format";

const project = ref("");
const data = ref({
	boms: [],
	work_orders: [],
	stock_entries: [],
	stock_entry_types: [],
	warehouses: [],
	material_consumption: [],
});
const loading = ref(false);
const form = ref({ bom: "", qty: null, source_warehouse: "", wip_warehouse: "", fg_warehouse: "" });

async function load() {
	loading.value = true;
	try {
		data.value = await getManufacturingWorkspace({ project: project.value || undefined });
	} catch (err) {
		showToast(err.message || "Failed to load materials workspace", "error");
	} finally {
		loading.value = false;
	}
}
watch(project, load);
onMounted(load);
async function makeWorkOrder() {
	if (!project.value || !form.value.bom || Number(form.value.qty) <= 0)
		return showToast("Select a project, BOM and quantity.", "error");
	try {
		const result = await createWorkOrder({ project: project.value, ...form.value });
		showToast(`Work Order ${result.work_order} created as draft.`);
		await load();
	} catch (err) {
		showToast(err.message || "Could not create Work Order", "error");
	}
}
async function makeStockEntry(workOrder, purpose) {
	try {
		const result = await createWorkOrderStockEntry({ work_order: workOrder, purpose });
		showToast(`${result.stock_entry} created through ERPNext's manufacturing mapper.`);
		await load();
	} catch (err) {
		showToast(err.message || "Could not create Stock Entry", "error");
	}
}
</script>

<template>
	<DeskPage title="Materials &amp; Manufacturing" subtitle="Project visibility over native BOMs, Work Orders, Stock Entries and warehouses." :breadcrumbs="[{ label: 'BuildSuite Core', to: '/' }, { label: 'Materials & Manufacturing' }]">
		<div class="space-y-5">
			<section class="bg-white border border-ink-200 rounded-lg p-4">
				<DeskField label="Project filter"><DeskLinkPicker v-model="project" doctype="Project" label-field="project_name" value-field="name" placeholder="All projects" /></DeskField>
			</section>
			<section class="bg-white border border-ink-200 rounded-lg p-4">
				<div class="flex flex-wrap items-start justify-between gap-3 mb-3">
					<div>
						<h2 class="text-sm font-semibold text-ink-900">Available Stock Entry Types</h2>
						<p class="text-xs text-ink-500 mt-1">All native ERPNext stock and manufacturing purposes remain available.</p>
					</div>
					<DeskLink href="/app/stock-entry">Open Stock Entries in ERPNext</DeskLink>
				</div>
				<div class="flex flex-wrap gap-2">
					<span v-for="entryType in data.stock_entry_types" :key="entryType.name" class="rounded-full border border-ink-200 bg-ink-50 px-3 py-1 text-xs text-ink-700" :title="`Ledger purpose: ${entryType.purpose}`">{{ entryType.name }}</span>
				</div>
			</section>
			<section v-if="project" class="bg-white border border-ink-200 rounded-lg p-4">
				<h2 class="text-sm font-semibold text-ink-900 mb-3">Create Work Order</h2>
				<div class="grid grid-cols-1 md:grid-cols-3 gap-3">
					<DeskField label="Submitted BOM"><DeskLinkPicker v-model="form.bom" doctype="BOM" label-field="name" value-field="name" :filters="[['docstatus', '=', 1], ['is_active', '=', 1]]" /></DeskField>
					<DeskField label="Quantity"><DeskInput v-model.number="form.qty" type="number" min="0" /></DeskField>
					<DeskField label="Finished goods warehouse"><DeskLinkPicker v-model="form.fg_warehouse" doctype="Warehouse" label-field="warehouse_name" value-field="name" /></DeskField>
					<DeskField label="Source warehouse"><DeskLinkPicker v-model="form.source_warehouse" doctype="Warehouse" label-field="warehouse_name" value-field="name" /></DeskField>
					<DeskField label="WIP warehouse"><DeskLinkPicker v-model="form.wip_warehouse" doctype="Warehouse" label-field="warehouse_name" value-field="name" /></DeskField>
				</div>
				<button class="desk-save-btn text-xs mt-3" type="button" @click="makeWorkOrder">Create draft with ERPNext</button>
			</section>
			<section class="bg-white border border-ink-200 rounded-lg overflow-x-auto">
				<div class="bg-ink-50 px-4 py-2 text-[11px] uppercase tracking-wider font-semibold">Work Orders</div>
				<table class="w-full text-xs"><thead><tr class="text-ink-500"><th class="text-left px-4 py-2">Work Order</th><th class="text-left px-4 py-2">Item</th><th class="text-right px-4 py-2">Qty</th><th class="text-left px-4 py-2">Status</th><th class="text-right px-4 py-2">Actions</th></tr></thead><tbody><tr v-for="wo in data.work_orders" :key="wo.name" class="border-t border-ink-100"><td class="px-4 py-2"><DeskLink :to="`/app/work-order/${wo.name}`">{{ wo.name }}</DeskLink></td><td class="px-4 py-2">{{ wo.production_item }}</td><td class="px-4 py-2 text-right">{{ wo.produced_qty }} / {{ wo.qty }}</td><td class="px-4 py-2">{{ wo.status }}</td><td class="px-4 py-2 text-right space-x-2"><button v-if="wo.docstatus === 1 && wo.produced_qty < wo.qty" class="text-brand-700 hover:underline" @click="makeStockEntry(wo.name, 'Material Transfer for Manufacture')">Transfer</button><button v-if="wo.docstatus === 1 && wo.produced_qty < wo.qty" class="text-brand-700 hover:underline" @click="makeStockEntry(wo.name, 'Manufacture')">Manufacture</button></td></tr><tr v-if="!loading && !data.work_orders.length"><td colspan="5" class="px-4 py-8 text-center text-ink-400">No Work Orders for this filter.</td></tr></tbody></table>
			</section>
			<section class="grid grid-cols-1 lg:grid-cols-2 gap-5">
				<div class="bg-white border border-ink-200 rounded-lg overflow-hidden"><div class="bg-ink-50 px-4 py-2 text-[11px] uppercase tracking-wider font-semibold">Stock Entries</div><div v-for="entry in data.stock_entries" :key="entry.name" class="grid grid-cols-[1fr_1fr_100px] px-4 py-2 border-t border-ink-100 text-xs"><DeskLink :to="`/app/stock-entry/${entry.name}`">{{ entry.name }}</DeskLink><span>{{ entry.purpose }}</span><span class="text-right">{{ fmtDate(entry.posting_date) }}</span></div></div>
				<div class="bg-white border border-ink-200 rounded-lg overflow-hidden"><div class="bg-ink-50 px-4 py-2 text-[11px] uppercase tracking-wider font-semibold">Project warehouses</div><div v-for="warehouse in data.warehouses" :key="warehouse.name" class="px-4 py-2 border-t border-ink-100 text-xs"><DeskLink :to="`/app/warehouse/${warehouse.name}`">{{ warehouse.warehouse_name || warehouse.name }}</DeskLink></div></div>
			</section>
			<section class="bg-white border border-ink-200 rounded-lg overflow-hidden"><div class="bg-ink-50 px-4 py-2 text-[11px] uppercase tracking-wider font-semibold">Active BOMs</div><div v-for="bom in data.boms" :key="bom.name" class="grid grid-cols-[1fr_1fr_120px] px-4 py-2 border-t border-ink-100 text-xs"><DeskLink :to="`/app/bom/${bom.name}`">{{ bom.name }}</DeskLink><span>{{ bom.item }}</span><span class="text-right">{{ fmtINR(bom.total_cost) }}</span></div></section>
		</div>
	</DeskPage>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import DeskPage from "@/components/desk/DeskPage.vue";
import DeskLink from "@/components/desk/DeskLink.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { bouncePdc, cancelPdc, clearPdc, getPdc, presentPdc, submitPdc } from "@/data/pdcApi";
import { showToast } from "@/utils/appToast";
import { fmtDate, fmtINR } from "@/utils/format";

const props = defineProps({ id: { type: String, required: true } });
const router = useRouter();
const doc = ref(null);
const loading = ref(true);
const busy = ref(false);
const isDraft = computed(() => doc.value?.docstatus === 0);

async function load() {
	loading.value = true;
	try {
		doc.value = await getPdc(props.id);
	} catch (err) {
		showToast(err.message || "Failed to load PDC", "error");
	} finally {
		loading.value = false;
	}
}
watch(() => props.id, load, { immediate: true });
async function act(fn, success) {
	busy.value = true;
	try {
		await fn();
		await load();
		showToast(success);
	} catch (err) {
		showToast(err.message || "PDC action failed", "error");
	} finally {
		busy.value = false;
	}
}
</script>

<template>
	<DeskPage :title="doc?.reference_no || id" subtitle="Post-dated cheque" :breadcrumbs="[{ label: 'Project Finance', to: '/project-finance' }, { label: 'PDC Register', to: '/project-finance/pdc' }, { label: id }]">
		<template v-if="doc" #actions>
			<div class="flex items-center gap-2">
				<StatusBadge :status="doc.status" size="xs" />
				<button v-if="isDraft" class="text-xs border border-ink-200 rounded-md px-3 py-1.5" @click="router.push(`/project-finance/pdc/${doc.name}/edit`)">Edit</button>
				<button v-if="isDraft" class="desk-save-btn text-xs" :disabled="busy" @click="act(() => submitPdc(doc.name), 'PDC submitted as Pending (non-posting).')">Submit</button>
				<button v-if="doc.status === 'Pending'" class="desk-save-btn text-xs" :disabled="busy" @click="act(() => presentPdc(doc.name), 'PDC marked Presented; no ledger entry was posted.')">Present</button>
				<button v-if="['Pending', 'Presented'].includes(doc.status)" class="desk-save-btn text-xs" :disabled="busy" @click="act(() => clearPdc({ name: doc.name, bank_account: doc.bank_account }), 'PDC cleared and one Payment Entry posted.')">Clear</button>
				<button v-if="doc.status === 'Cleared'" class="text-xs border border-danger-300 bg-danger-50 text-danger-700 rounded-md px-3 py-1.5" :disabled="busy" @click="act(() => bouncePdc(doc.name), 'PDC bounced; its Payment Entry was cancelled and invoice outstanding restored.')">Bounce</button>
				<button v-if="['Pending', 'Presented'].includes(doc.status)" class="text-xs border border-warning-300 bg-warning-50 text-warning-700 rounded-md px-3 py-1.5" :disabled="busy" @click="act(() => cancelPdc(doc.name), 'PDC cancelled.')">Cancel</button>
			</div>
		</template>
		<div v-if="loading" class="py-16 text-center text-ink-400">Loading…</div>
		<div v-else-if="doc" class="space-y-4">
			<div v-if="['Pending', 'Presented'].includes(doc.status)" class="px-4 py-2.5 bg-info-50 border border-info-200 rounded-lg text-sm text-info-700">Non-posting status — no General Ledger entry exists until this cheque is cleared.</div>
			<section class="grid grid-cols-1 md:grid-cols-3 gap-3">
				<div v-for="row in [{ label: 'Direction', value: doc.direction }, { label: doc.party_type, value: doc.party_name || doc.party }, { label: 'Amount', value: fmtINR(doc.amount) }, { label: 'Cheque date', value: fmtDate(doc.reference_date) }, { label: 'Presented', value: fmtDate(doc.presented_on) || '—' }, { label: 'Cleared', value: fmtDate(doc.actual_posting_date) || '—' }]" :key="row.label" class="border border-ink-200 rounded-lg p-3"><div class="text-[10px] uppercase tracking-wider text-ink-500">{{ row.label }}</div><div class="text-sm font-medium text-ink-900 mt-0.5">{{ row.value }}</div></div>
			</section>
			<section class="bg-white border border-ink-200 rounded-lg overflow-hidden">
				<div class="bg-ink-50 px-4 py-2 text-[11px] uppercase tracking-wider font-semibold text-ink-700">Invoice allocations</div>
				<div v-for="row in doc.invoice_references" :key="row.reference_name" class="grid grid-cols-[1fr_140px] gap-3 px-4 py-2.5 border-t border-ink-100 text-sm"><DeskLink :to="row.reference_doctype === 'Sales Invoice' ? { name: 'finance-invoice', params: { id: row.reference_name } } : `/project-finance/supplier-bills/${row.reference_name}`">{{ row.reference_name }}</DeskLink><span class="text-right tabular-nums font-medium">{{ fmtINR(row.allocated_amount) }}</span></div>
			</section>
			<div v-if="doc.payment_entry" class="text-sm">Payment Entry: <DeskLink :to="`/app/payment-entry/${doc.payment_entry}`">{{ doc.payment_entry }}</DeskLink></div>
		</div>
	</DeskPage>
</template>

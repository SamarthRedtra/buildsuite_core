<script setup>
import { computed, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import DeskPage from "@/components/desk/DeskPage.vue";
import DeskForm from "@/components/desk/DeskForm.vue";
import DeskActionBar from "@/components/desk/DeskActionBar.vue";
import DeskSection from "@/components/desk/DeskSection.vue";
import DeskField from "@/components/desk/DeskField.vue";
import DeskInput from "@/components/desk/DeskInput.vue";
import DeskLinkPicker from "@/components/desk/DeskLinkPicker.vue";
import { useActiveCompany } from "@/composables/useActiveCompany";
import { availablePdcInvoices, getPdc, savePdc, submitPdc } from "@/data/pdcApi";
import { showToast } from "@/utils/appToast";
import { fmtINR } from "@/utils/format";

const props = defineProps({ id: { type: String, default: "" } });
const router = useRouter();
const activeCompany = useActiveCompany();
const isEdit = computed(() => !!props.id);
const saving = ref(false);
const loading = ref(isEdit.value);
const invoices = ref([]);
const form = reactive({
	direction: "Incoming",
	company: activeCompany.value || "",
	project: "",
	party: "",
	posting_date: new Date().toISOString().slice(0, 10),
	mode_of_payment: "Cheque",
	reference_no: "",
	reference_date: "",
	bank_account: "",
	notes: "",
	invoice_references: [],
});
const partyType = computed(() => (form.direction === "Incoming" ? "Customer" : "Supplier"));
const invoiceType = computed(() =>
	form.direction === "Incoming" ? "Sales Invoice" : "Purchase Invoice"
);
const total = computed(() =>
	form.invoice_references.reduce((sum, row) => sum + (Number(row.allocated_amount) || 0), 0)
);

async function loadInvoices() {
	invoices.value = [];
	if (!form.company || !form.party) return;
	try {
		invoices.value = await availablePdcInvoices({
			reference_doctype: invoiceType.value,
			company: form.company,
			party: form.party,
			current_pdc: props.id || undefined,
		});
	} catch (err) {
		showToast(err.message || "Could not load invoice balances", "error");
	}
}
watch(() => [form.company, form.party, form.direction], loadInvoices);
watch(
	() => form.direction,
	() => {
		form.party = "";
		form.invoice_references = [];
	}
);
function addInvoice() {
	form.invoice_references.push({ reference_name: "", allocated_amount: null });
}
function removeInvoice(index) {
	form.invoice_references.splice(index, 1);
}
function invoiceAvailable(name) {
	return Number(invoices.value.find((row) => row.name === name)?.available_pdc_amount) || 0;
}

if (isEdit.value) {
	getPdc(props.id)
		.then((doc) => {
			if (doc.docstatus !== 0) return router.replace(`/project-finance/pdc/${props.id}`);
			Object.assign(form, {
				direction: doc.direction,
				company: doc.company,
				project: doc.project || "",
				party: doc.party,
				posting_date: doc.posting_date,
				mode_of_payment: doc.mode_of_payment,
				reference_no: doc.reference_no,
				reference_date: doc.reference_date,
				bank_account: doc.bank_account,
				notes: doc.notes || "",
				invoice_references: (doc.invoice_references || []).map((row) => ({
					reference_name: row.reference_name,
					allocated_amount: row.allocated_amount,
				})),
			});
			loadInvoices();
		})
		.catch((err) => showToast(err.message || "Failed to load PDC", "error"))
		.finally(() => (loading.value = false));
}

async function save(submit = false) {
	if (!form.party || !form.reference_no || !form.reference_date || !form.bank_account)
		return showToast("Party, cheque number, cheque date and bank account are required.", "error");
	if (!form.invoice_references.length || total.value <= 0)
		return showToast("Allocate the cheque to at least one submitted invoice.", "error");
	saving.value = true;
	try {
		const doc = await savePdc({
			...form,
			name: props.id || undefined,
			invoice_references: form.invoice_references.map((row) => ({
				reference_doctype: invoiceType.value,
				reference_name: row.reference_name,
				allocated_amount: Number(row.allocated_amount) || 0,
			})),
		});
		if (submit) await submitPdc(doc.name);
		showToast(submit ? "PDC submitted as Pending (non-posting)." : "PDC saved as draft.");
		router.push(`/project-finance/pdc/${doc.name}`);
	} catch (err) {
		showToast(err.message || "Failed to save PDC", "error");
	} finally {
		saving.value = false;
	}
}
</script>

<template>
	<DeskPage
		:title="isEdit ? `Edit ${id}` : 'New post-dated cheque'"
		subtitle="Submitting reserves invoice balance but does not post to the ledger."
		:breadcrumbs="[{ label: 'Project Finance', to: '/project-finance' }, { label: 'PDC Register', to: '/project-finance/pdc' }, { label: isEdit ? id : 'New' }]"
	>
		<DeskForm>
			<template #action-bar><DeskActionBar save-label="Save draft" :saving="saving" @save="save(false)" @cancel="router.back()"><template #actions><button type="button" class="desk-save-btn text-xs" :disabled="saving" @click="save(true)">Save &amp; submit</button></template></DeskActionBar></template>
			<div v-if="loading" class="py-16 text-center text-ink-400">Loading…</div>
			<template v-else>
				<DeskSection title="Cheque" :cols="3">
					<DeskField label="Direction" required><select v-model="form.direction" class="w-full text-sm border border-ink-200 rounded-md px-2 py-2"><option>Incoming</option><option>Outgoing</option></select></DeskField>
					<DeskField label="Company" required><DeskLinkPicker v-model="form.company" doctype="Company" label-field="company_name" value-field="name" /></DeskField>
					<DeskField label="Project"><DeskLinkPicker v-model="form.project" doctype="Project" label-field="project_name" value-field="name" :filters="form.company ? [['company', '=', form.company]] : []" placeholder="Optional" /></DeskField>
					<DeskField :label="partyType" required><DeskLinkPicker v-model="form.party" :doctype="partyType" :label-field="partyType === 'Customer' ? 'customer_name' : 'supplier_name'" value-field="name" /></DeskField>
					<DeskField label="Cheque no." required><DeskInput v-model="form.reference_no" /></DeskField>
					<DeskField label="Cheque date" required><DeskInput v-model="form.reference_date" type="date" /></DeskField>
					<DeskField label="Posting date" required><DeskInput v-model="form.posting_date" type="date" /></DeskField>
					<DeskField label="Mode of payment" required><DeskLinkPicker v-model="form.mode_of_payment" doctype="Mode of Payment" label-field="name" value-field="name" /></DeskField>
					<DeskField label="Bank account" required hint="Used only on clearance."><DeskLinkPicker v-model="form.bank_account" doctype="Account" label-field="name" value-field="name" :filters="[['company', '=', form.company], ['is_group', '=', 0], ['account_type', 'in', ['Bank', 'Cash']]]" /></DeskField>
				</DeskSection>
				<DeskSection title="Invoice allocations" :cols="1">
					<div v-for="(row, index) in form.invoice_references" :key="index" class="grid grid-cols-[1fr_180px_32px] gap-2 mb-2 items-center">
						<select v-model="row.reference_name" class="text-xs border border-ink-200 rounded-md px-2 py-2"><option value="">Select {{ invoiceType }}</option><option v-for="invoice in invoices" :key="invoice.name" :value="invoice.name">{{ invoice.name }} · available {{ fmtINR(invoice.available_pdc_amount) }}</option></select>
						<DeskInput v-model.number="row.allocated_amount" type="number" min="0" :max="invoiceAvailable(row.reference_name)" placeholder="Allocated amount" />
						<button type="button" class="text-danger-600" @click="removeInvoice(index)">✕</button>
					</div>
					<div class="flex items-center justify-between"><button type="button" class="text-xs text-brand-700 hover:underline" @click="addInvoice">+ Add invoice</button><span class="text-sm font-semibold">Total {{ fmtINR(total) }}</span></div>
				</DeskSection>
				<DeskSection title="Notes" :cols="1"><textarea v-model="form.notes" rows="3" class="w-full text-sm border border-ink-200 rounded-md px-3 py-2" /></DeskSection>
			</template>
		</DeskForm>
	</DeskPage>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { getActiveCompanyContext } from "@/data/companyApi";

const company = ref(null);
const error = ref("");

onMounted(async () => {
	try {
		company.value = await getActiveCompanyContext();
	} catch (err) {
		error.value = err.message;
	}
});
</script>

<template>
	<div
		v-if="company"
		class="h-7 px-2 rounded-md flex items-center gap-2 border border-ink-200 bg-ink-50"
		:title="company.name"
		data-testid="active-company-badge"
	>
		<span class="w-2 h-2 rounded-full bg-brand-600"></span>
		<span class="text-xs font-medium text-ink-700 whitespace-nowrap">{{ company.name }}</span>
	</div>
	<span v-else-if="error" class="text-xs text-danger-600" title="Unable to load company">
		Company unavailable
	</span>
</template>

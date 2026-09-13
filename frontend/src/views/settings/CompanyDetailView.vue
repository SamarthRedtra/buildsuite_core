<script setup>
import { onMounted } from "vue";
import { getFrappeHost } from "@/utils/session";

const props = defineProps({ id: String });

onMounted(() => {
	window.location.replace(`${getFrappeHost()}/app/company/${encodeURIComponent(props.id)}`);
});
</script>

<template><div class="p-6 text-sm text-ink-500">Opening ERPNext Company…</div></template>

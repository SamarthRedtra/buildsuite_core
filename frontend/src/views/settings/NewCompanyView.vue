<script setup>
import { onMounted } from "vue";
import { getFrappeHost } from "@/utils/session";

onMounted(() => {
	window.location.replace(`${getFrappeHost()}/app/company/new-company`);
});
</script>

<template><div class="p-6 text-sm text-ink-500">Opening ERPNext Company…</div></template>

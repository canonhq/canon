<script setup>
import { computed } from "vue";
import { useRoute } from "vitepress";

const route = useRoute();

const versionMatch = computed(() => {
  const match = route.path.match(/\/docs\/v(\d+\.\d+)\//);
  return match ? match[1] : null;
});

const isOldVersion = computed(() => versionMatch.value !== null);
</script>

<template>
  <div v-if="isOldVersion" class="version-banner">
    You are viewing docs for <strong>v{{ versionMatch }}</strong>.
    <a href="/docs/">Switch to latest version</a>
  </div>
</template>

<style scoped>
.version-banner {
  background-color: var(--vp-c-warning-soft);
  border-bottom: 1px solid var(--vp-c-warning-2);
  color: var(--vp-c-warning-1);
  padding: 8px 16px;
  text-align: center;
  font-size: 14px;
}
.version-banner a {
  color: var(--vp-c-brand-1);
  text-decoration: underline;
  margin-left: 8px;
}
</style>

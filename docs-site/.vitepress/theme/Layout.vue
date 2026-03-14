<script setup>
import DefaultTheme from "vitepress/theme";
import { onMounted, watch } from "vue";
import { useRoute } from "vitepress";
import VersionBanner from "./VersionBanner.vue";

const { Layout } = DefaultTheme;
const route = useRoute();
const MAIN_SITE = "https://canonhq.co";

function patchLogoLink() {
  const link = document.querySelector(".VPNavBarTitle a");
  if (link && link.getAttribute("href") !== MAIN_SITE) {
    link.setAttribute("href", MAIN_SITE);
  }
  const mobileLink = document.querySelector(".VPNavBarHamburger + a, .VPNavScreenMenuLink a[href='/docs/']");
  if (mobileLink) {
    mobileLink.setAttribute("href", MAIN_SITE);
  }
}

function injectFonts() {
  if (document.querySelector('link[href*="fonts.googleapis.com/css2"]')) return;
  const preconnect1 = document.createElement("link");
  preconnect1.rel = "preconnect";
  preconnect1.href = "https://fonts.googleapis.com";
  document.head.appendChild(preconnect1);

  const preconnect2 = document.createElement("link");
  preconnect2.rel = "preconnect";
  preconnect2.href = "https://fonts.gstatic.com";
  preconnect2.crossOrigin = "anonymous";
  document.head.appendChild(preconnect2);

  const fontLink = document.createElement("link");
  fontLink.rel = "stylesheet";
  fontLink.href = "https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,600;0,9..144,700;0,9..144,800&family=DM+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap";
  document.head.appendChild(fontLink);
}

onMounted(() => {
  injectFonts();
  patchLogoLink();
  watch(
    () => route.path,
    () => requestAnimationFrame(patchLogoLink),
  );
});
</script>

<template>
  <VersionBanner />
  <Layout />
</template>

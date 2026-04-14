import { defineConfig, type HeadConfig } from "vitepress";
import { withMermaid } from "vitepress-plugin-mermaid";

const SITE_URL = "https://canonhq.co/docs";

export default withMermaid(
  defineConfig({
    title: "Canon",
    description:
      "AI-native enterprise documentation platform. Living specs, agent-maintained docs, repo-native knowledge.",
    base: "/docs/",
    cleanUrls: true,
    head: [
      ["link", { rel: "icon", type: "image/svg+xml", href: "/docs/logo.svg" }],
      ["link", { rel: "icon", type: "image/png", href: "/static/favicon.png" }],
      ["meta", { property: "og:type", content: "website" }],
      ["meta", { property: "og:title", content: "Canon Docs" }],
      [
        "meta",
        {
          property: "og:description",
          content:
            "AI-native enterprise documentation platform. Living specs, agent-maintained docs, repo-native knowledge.",
        },
      ],
      ["meta", { property: "og:url", content: SITE_URL }],
      ["meta", { name: "twitter:card", content: "summary" }],
    ],

    sitemap: {
      hostname: SITE_URL,
    },

    transformHead({ pageData }) {
      const head: HeadConfig[] = [];
      const canonicalUrl = `${SITE_URL}/${pageData.relativePath}`
        .replace(/index\.md$/, "")
        .replace(/\.md$/, "");
      head.push(["link", { rel: "canonical", href: canonicalUrl }]);
      return head;
    },

    themeConfig: {
      logo: "/logo.svg",
      siteTitle: "Canon",

      nav: [
        { text: "Home", link: "https://canonhq.co" },
        { text: "Getting Started", link: "/getting-started/" },
        { text: "Concepts", link: "/concepts/" },
        { text: "Guides", link: "/guides/" },
        { text: "Reference", link: "/reference/" },
        {
          text: "More",
          items: [
            { text: "Architecture", link: "/architecture/" },
            { text: "Contributing", link: "/contributing/" },
            { text: "Changelog", link: "/changelog" },
          ],
        },
        {
          text: "v1.7",
          items: [
            { text: "v1.7 (latest)", link: "/" },
            { text: "v1.6", link: "/v1.6/" },
          ],
        },
      ],

      sidebar: {
        "/getting-started/": [
          {
            text: "Getting Started",
            items: [
              { text: "Overview", link: "/getting-started/" },
              { text: "Installation", link: "/getting-started/installation" },
              { text: "Quickstart", link: "/getting-started/quickstart" },
              {
                text: "Configuration",
                link: "/getting-started/configuration",
              },
            ],
          },
        ],
        "/concepts/": [
          {
            text: "Concepts",
            items: [
              { text: "Overview", link: "/concepts/" },
              { text: "Spec-Driven Development", link: "/concepts/spec-driven-development" },
              { text: "Living Specs", link: "/concepts/living-specs" },
              { text: "Delta Tracking", link: "/concepts/delta-tracking" },
              { text: "Agent Mesh", link: "/concepts/agent-mesh" },
              { text: "Spec Coverage", link: "/concepts/coverage" },
            ],
          },
        ],
        "/guides/": [
          {
            text: "Guides",
            items: [
              { text: "Overview", link: "/guides/" },
              { text: "Writing Specs", link: "/guides/writing-specs" },
              { text: "Example Specs", link: "/guides/examples" },
              { text: "Self-Hosting", link: "/guides/self-hosting" },
              { text: "GitHub App Setup", link: "/guides/github-app" },
              { text: "Ticket Sync", link: "/guides/ticket-sync" },
              { text: "FAQ", link: "/guides/faq" },
              { text: "Troubleshooting", link: "/guides/troubleshooting" },
            ],
          },
          {
            text: "GitHub Actions",
            items: [
              { text: "Overview", link: "/guides/github-actions/" },
              { text: "Setup Canon", link: "/guides/github-actions/setup" },
              { text: "Spec Lint", link: "/guides/github-actions/spec-lint" },
              { text: "Verify", link: "/guides/github-actions/verify" },
              {
                text: "Coverage Report",
                link: "/guides/github-actions/coverage-report",
              },
              {
                text: "Coverage Delta",
                link: "/guides/github-actions/coverage-delta",
              },
              { text: "Audit", link: "/guides/github-actions/audit" },
              { text: "Sync", link: "/guides/github-actions/sync" },
              {
                text: "Release Notes",
                link: "/guides/github-actions/release-notes",
              },
              { text: "Plan", link: "/guides/github-actions/plan" },
              { text: "New Spec", link: "/guides/github-actions/new-spec" },
              { text: "Dedup", link: "/guides/github-actions/dedup" },
              {
                text: "Stale Spec Check",
                link: "/guides/github-actions/stale-spec-check",
              },
              {
                text: "Compliance Export",
                link: "/guides/github-actions/compliance-export",
              },
              { text: "Upgrade", link: "/guides/github-actions/upgrade" },
              { text: "Recipes", link: "/guides/github-actions/recipes" },
            ],
          },
        ],
        "/reference/": [
          {
            text: "Reference",
            items: [
              { text: "Overview", link: "/reference/" },
              { text: "CLI", link: "/reference/cli" },
              { text: "MCP Tools", link: "/reference/mcp" },
              { text: "Claude Code Skills", link: "/reference/skills" },
              { text: "REST API", link: "/reference/api" },
              { text: "Spec Format", link: "/reference/spec-format" },
              { text: "CANON.yaml", link: "/reference/config" },
            ],
          },
        ],
        "/architecture/": [
          {
            text: "Architecture",
            items: [
              { text: "Overview", link: "/architecture/" },
              { text: "System Design", link: "/architecture/system-design" },
              { text: "Data Flow", link: "/architecture/data-flow" },
              { text: "Components", link: "/architecture/components" },
            ],
          },
        ],
        "/contributing/": [
          {
            text: "Contributing",
            items: [
              { text: "Overview", link: "/contributing/" },
              { text: "Development", link: "/contributing/development" },
              { text: "Testing", link: "/contributing/testing" },
              { text: "Code Style", link: "/contributing/code-style" },
            ],
          },
        ],
      },

      socialLinks: [
        {
          icon: "github",
          link: "https://github.com/canonhq/canon",
        },
      ],

      editLink: {
        pattern:
          "https://github.com/canonhq/canon/edit/main/docs-site/:path",
        text: "Edit this page on GitHub",
      },

      search: {
        provider: "local",
      },

      footer: {
        message: "AI-native enterprise documentation platform.",
        copyright: "Copyright © 2026 Gerner Ventures",
      },
    },

    mermaid: {},
  }),
);

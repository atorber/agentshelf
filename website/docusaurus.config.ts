import type {Config} from "@docusaurus/types"
import type * as Preset from "@docusaurus/preset-classic"
import {themes as prismThemes} from "prism-react-renderer"

const config: Config = {
  title: "AgentShelf",
  tagline: "面向多个 AI Agent 的本地知识库",
  favicon: "img/favicon.svg",
  url: "https://atorber.github.io",
  baseUrl: "/agentshelf/",
  organizationName: "atorber",
  projectName: "agentshelf",
  onBrokenLinks: "throw",
  onBrokenAnchors: "throw",
  i18n: {
    defaultLocale: "zh-Hans",
    locales: ["zh-Hans"],
  },
  markdown: {
    mermaid: true,
  },
  themes: ["@docusaurus/theme-mermaid"],
  presets: [
    [
      "classic",
      {
        docs: {
          routeBasePath: "/",
          sidebarPath: "./sidebars.ts",
          editUrl: "https://github.com/atorber/agentshelf/edit/main/website/",
        },
        blog: false,
        theme: {
          customCss: "./src/css/custom.css",
        },
      } satisfies Preset.Options,
    ],
  ],
  themeConfig: {
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: "AgentShelf",
      logo: {
        alt: "AgentShelf",
        src: "img/logo.svg",
      },
      items: [
        {to: "/product", label: "产品", position: "left"},
        {to: "/quickstart", label: "快速开始", position: "left"},
        {to: "/usage", label: "使用", position: "left"},
        {to: "/agent", label: "在 Agent 中", position: "left"},
        {to: "/troubleshooting", label: "排查", position: "left"},
        {href: "https://github.com/atorber/agentshelf", label: "GitHub", position: "right"},
      ],
    },
    footer: {
      style: "dark",
      links: [
        {
          title: "使用",
          items: [
            {label: "快速开始", to: "/quickstart"},
            {label: "在 Agent 中", to: "/agent"},
            {label: "窗口", to: "/usage"},
          ],
        },
        {
          title: "说明",
          items: [
            {label: "产品", to: "/product"},
            {label: "排查", to: "/troubleshooting"},
            {label: "开发者", to: "/developers"},
          ],
        },
      ],
      copyright: "文件、检索词和使用记录都留在本机。",
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
    mermaid: {
      theme: {light: "neutral", dark: "dark"},
    },
  } satisfies Preset.ThemeConfig,
  plugins: [
    [
      "@easyops-cn/docusaurus-search-local",
      {
        hashed: true,
        language: ["en", "zh"],
        indexDocs: true,
        indexBlog: false,
        docsRouteBasePath: "/",
      },
    ],
  ],
}

export default config

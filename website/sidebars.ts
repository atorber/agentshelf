import type {SidebarsConfig} from "@docusaurus/plugin-content-docs"

const sidebars: SidebarsConfig = {
  docs: [
    "product",
    "quickstart",
    {
      type: "category",
      label: "使用",
      link: {type: "doc", id: "usage/index"},
      items: ["usage/library", "usage/upload", "usage/detail", "usage/organize", "usage/settings"],
    },
    "agent",
    "troubleshooting",
    "developers",
  ],
}

export default sidebars

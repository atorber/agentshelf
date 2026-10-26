import Link from "@docusaurus/Link"
import styles from "./Homepage.module.css"

const steps = [
  {
    n: "01",
    title: "安装一次",
    text: "把一段提示词发给正在使用的 Agent。它安装 Skill 并打开窗口。每个 Agent 只做一次。",
    href: "/quickstart",
    more: "查看提示词",
  },
  {
    n: "02",
    title: "一句话归档",
    text: "任务完成时说「把这份最终稿归档到 AgentShelf。」名称、项目、标签和来源由 Agent 填写。",
    href: "/agent",
    more: "归档说明",
  },
  {
    n: "03",
    title: "在窗口里确认",
    text: "正文按文档阅读。图片、视频和附件列在右侧，也能嵌在正文里。",
    href: "/usage",
    more: "窗口说明",
  },
]

const pages = [
  {href: "/usage/library", title: "知识库", text: "一行一条。搜索、筛选，点进去看详情。"},
  {href: "/usage/upload", title: "上传", text: "不经过 Agent，自己把文件放进库。"},
  {href: "/usage/organize", title: "整理", text: "维护项目、标签和来源。删除它们不会删除已收入的知识。"},
  {href: "/usage/learn", title: "学习", text: "静态阅读 Skill 的结构、流程和工具。不执行脚本。"},
  {href: "/usage/settings", title: "设置", text: "复制提示词、查看数据目录、本机备份和 S3，按需启用语义检索。"},
]

export default function Homepage() {
  return (
    <div>
      <header className={styles.hero}>
        <h1>AgentShelf</h1>
        <p className={styles.lead}>面向多个 AI Agent 的本地知识库。任务结束后，把值得留下的最终稿收进这台电脑，在一个窗口里检索、预览和保留版本。</p>
        <p className={styles.meta}>当前版本 0.4.0 · macOS 与 Windows · 文件、检索词和使用记录都留在本机</p>
        <div className={styles.actions}>
          <Link className="button button--primary" to="/quickstart">
            安装并归档第一份
          </Link>
          <Link className="button button--secondary" to="/product">
            看产品说明
          </Link>
        </div>
      </header>

      <section className={styles.section}>
        <h2>三步用起来</h2>
        <div className={styles.grid}>
          {steps.map((step) => (
            <Link className={styles.card} key={step.n} to={step.href}>
              <span className={styles.step}>{step.n}</span>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
              <span className={styles.more}>{step.more}</span>
            </Link>
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <h2>留下什么</h2>
        <p>一次任务结束后，最终稿常常散落在各个 Agent 的对话和项目文件夹里。换一个 Agent 继续时，很难同时回答：文件在哪、哪一版是现在用的、它从哪个 Agent 来。</p>
        <div className={styles.split}>
          <div className={styles.card}>
            <h3>收进知识库</h3>
            <p>文档、代码、图片、报告、数据文件，以及后来对它们的修改。每条知识记下编号、来源 Agent、所属项目和归档时间。</p>
          </div>
          <div className={styles.card}>
            <h3>留在对话里</h3>
            <p>思考过程、工具调用记录和临时中间稿。它们不是最终成果，AgentShelf 不会主动去扫，也只接收你或 Agent 明确提交的文件。</p>
          </div>
        </div>
        <p className={styles.prompt}>把这份最终稿归档到 AgentShelf。</p>
      </section>

      <section className={styles.section}>
        <h2>窗口</h2>
        <div className={styles.split}>
          {pages.map((page) => (
            <Link className={styles.card} key={page.href} to={page.href}>
              <h3>{page.title}</h3>
              <p>{page.text}</p>
            </Link>
          ))}
        </div>
      </section>
    </div>
  )
}

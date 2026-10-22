import { execFileSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")

function dataDir(): string {
  if (process.env.AGENTSHELF_DATA_DIR) return process.env.AGENTSHELF_DATA_DIR
  const python = fs.existsSync(path.join(root, ".venv/bin/python"))
    ? path.join(root, ".venv/bin/python")
    : "python3"
  try {
    return execFileSync(python, ["-c", "from agentshelf.config import load_settings; print(load_settings().data_dir)"], {
      cwd: root,
      encoding: "utf8",
    }).trim()
  } catch {
    if (process.platform === "darwin") return path.join(os.homedir(), "Library", "Application Support", "AgentShelf")
    if (process.platform === "win32") return path.join(process.env.LOCALAPPDATA || "", "AgentShelf")
    return path.join(os.homedir(), ".local", "share", "AgentShelf")
  }
}

function readToken(): string {
  try {
    return fs.readFileSync(path.join(dataDir(), "token"), "utf8").trim()
  } catch {
    return ""
  }
}

function proxyTarget(): string {
  try {
    const runtime = JSON.parse(fs.readFileSync(path.join(dataDir(), "runtime.json"), "utf8")) as { port?: number }
    if (runtime.port) return `http://127.0.0.1:${runtime.port}`
  } catch {
    /* 服务尚未写 runtime.json 时使用默认端口 */
  }
  return "http://127.0.0.1:8765"
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 1420,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        router: () => proxyTarget(),
        configure(proxy) {
          proxy.on("proxyReq", (proxyReq) => {
            const token = readToken()
            if (token) proxyReq.setHeader("Authorization", `Bearer ${token}`)
          })
        },
      },
    },
  },
  build: {
    target: "es2022",
  },
})

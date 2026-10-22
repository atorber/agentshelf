import { execFileSync } from "node:child_process"
import fs from "node:fs"
import http from "node:http"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import type { IncomingMessage, ServerResponse } from "node:http"
import react from "@vitejs/plugin-react"
import { defineConfig, type Plugin } from "vite"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")

let cachedDataDir = ""

function dataDir(): string {
  if (!cachedDataDir) cachedDataDir = resolveDataDir()
  return cachedDataDir
}

function resolveDataDir(): string {
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

function forwardApi(req: IncomingMessage, res: ServerResponse, next: (error?: unknown) => void) {
  const url = req.url || ""
  if (!url.startsWith("/api")) {
    next()
    return
  }
  const target = new URL(proxyTarget())
  const headers = { ...req.headers }
  delete headers.host
  delete headers.connection
  const token = readToken()
  if (token) headers.authorization = `Bearer ${token}`
  const proxyReq = http.request(
    {
      hostname: target.hostname,
      port: target.port,
      method: req.method,
      path: url,
      headers,
    },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode || 502, proxyRes.headers)
      proxyRes.pipe(res)
    },
  )
  proxyReq.on("error", () => {
    if (!res.headersSent) {
      const message = JSON.stringify({ detail: "本地服务不可用" })
      res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" }).end(message)
    }
  })
  const method = req.method || "GET"
  if (method === "GET" || method === "HEAD") {
    proxyReq.end()
  } else {
    req.pipe(proxyReq)
  }
}

function apiProxy(): Plugin {
  return {
    name: "agentshelf-api-proxy",
    configureServer(server) {
      server.middlewares.use(forwardApi)
    },
    configurePreviewServer(server) {
      server.middlewares.use(forwardApi)
    },
  }
}

export default defineConfig({
  plugins: [react(), apiProxy()],
  server: {
    host: "127.0.0.1",
    port: 1420,
    strictPort: true,
  },
  build: {
    target: "es2022",
  },
})

import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import process from "node:process";

import { CDP_CONNECT_TIMEOUT_MS, NETWORK_IDLE_TIMEOUT_MS } from "./constants.js";

type CdpSendOptions = { sessionId?: string; timeoutMs?: number };

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchJsonWithTimeout<T>(url: string, timeoutMs: number, signal?: AbortSignal): Promise<T> {
  const ctl = new AbortController();
  const onCancel = () => ctl.abort(signal?.reason);
  signal?.addEventListener("abort", onCancel, { once: true });
  if (signal?.aborted) onCancel();
  const timer = setTimeout(() => ctl.abort(new Error("Chrome debug response timeout")), timeoutMs);
  let onAbort: () => void = () => {};
  const aborted = new Promise<never>((_, reject) => {
    onAbort = () => reject(ctl.signal.reason);
    ctl.signal.addEventListener("abort", onAbort, { once: true });
    if (ctl.signal.aborted) onAbort();
  });
  try {
    // Keep both the response headers and body inside the same cancellable deadline.
    return await Promise.race([aborted, (async () => {
      ctl.signal.throwIfAborted();
      const res = await fetch(url, { signal: ctl.signal });
      if (!res.ok) throw new Error(`status=${res.status}`);
      return await res.json() as T;
    })()]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onCancel);
    ctl.signal.removeEventListener("abort", onAbort);
  }
}

export class CdpConnection {
  private ws: WebSocket;
  private nextId = 0;
  private pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void; timer: ReturnType<typeof setTimeout> | null }>();
  private eventHandlers = new Map<string, Set<(params: unknown) => void>>();

  private constructor(ws: WebSocket) {
    this.ws = ws;
    this.ws.addEventListener("message", (event) => {
      try {
        const data = typeof event.data === "string" ? event.data : new TextDecoder().decode(event.data as ArrayBuffer);
        const msg = JSON.parse(data) as { id?: number; method?: string; params?: unknown; sessionId?: string; result?: unknown; error?: { message?: string } };
        if (msg.id) {
          const p = this.pending.get(msg.id);
          if (p) {
            this.pending.delete(msg.id);
            if (p.timer) clearTimeout(p.timer);
            if (msg.error?.message) p.reject(new Error(msg.error.message));
            else p.resolve(msg.result);
          }
        } else if (msg.method) {
          const handlers = this.eventHandlers.get(`${msg.sessionId ?? ""}:${msg.method}`);
          if (handlers) {
            for (const h of handlers) h(msg.params);
          }
        }
      } catch {}
    });
    this.ws.addEventListener("close", () => {
      for (const [id, p] of this.pending.entries()) {
        this.pending.delete(id);
        if (p.timer) clearTimeout(p.timer);
        p.reject(new Error("CDP connection closed."));
      }
    });
  }

  static async connect(url: string, timeoutMs: number): Promise<CdpConnection> {
    const ws = new WebSocket(url);
    await new Promise<void>((resolve, reject) => {
      const t = setTimeout(() => { ws.close(); reject(new Error("CDP connection timeout.")); }, timeoutMs);
      ws.addEventListener("open", () => { clearTimeout(t); resolve(); });
      ws.addEventListener("error", () => { clearTimeout(t); reject(new Error("CDP connection failed.")); });
    });
    return new CdpConnection(ws);
  }

  on(event: string, handler: (params: unknown) => void, sessionId = ""): void {
    event = `${sessionId}:${event}`;
    let handlers = this.eventHandlers.get(event);
    if (!handlers) {
      handlers = new Set();
      this.eventHandlers.set(event, handlers);
    }
    handlers.add(handler);
  }

  off(event: string, handler: (params: unknown) => void, sessionId = ""): void {
    event = `${sessionId}:${event}`;
    this.eventHandlers.get(event)?.delete(handler);
  }

  async send<T = unknown>(method: string, params?: Record<string, unknown>, opts?: CdpSendOptions): Promise<T> {
    const id = ++this.nextId;
    const msg: Record<string, unknown> = { id, method };
    if (params) msg.params = params;
    if (opts?.sessionId) msg.sessionId = opts.sessionId;
    const timeoutMs = opts?.timeoutMs ?? 15_000;
    const out = await new Promise<unknown>((resolve, reject) => {
      const t = timeoutMs > 0 ? setTimeout(() => { this.pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, timeoutMs) : null;
      this.pending.set(id, { resolve, reject, timer: t });
      try { this.ws.send(JSON.stringify(msg)); } catch (error) {
        if (t) clearTimeout(t);
        this.pending.delete(id);
        reject(error);
      }
    });
    return out as T;
  }

  close(): void {
    this.ws.close();
  }
}

export async function getFreePort(): Promise<number> {
  return await new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const addr = srv.address();
      if (!addr || typeof addr === "string") {
        srv.close(() => reject(new Error("Unable to allocate a free TCP port.")));
        return;
      }
      const port = addr.port;
      srv.close((err) => (err ? reject(err) : resolve(port)));
    });
  });
}

export function findChromeExecutable(): string | null {
  const override = process.env.URL_CHROME_PATH?.trim();
  if (override && fs.existsSync(override)) return override;

  const candidates: string[] = [];
  switch (process.platform) {
    case "darwin":
      candidates.push(
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
        "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
      );
      break;
    case "win32":
      candidates.push(
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
        "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
      );
      break;
    default:
      candidates.push(
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
        "/usr/bin/microsoft-edge"
      );
      break;
  }

  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  return null;
}

export async function waitForChromeDebugPort(port: number, timeoutMs: number, signal?: AbortSignal): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      signal?.throwIfAborted();
      const j = await fetchJsonWithTimeout<{ webSocketDebuggerUrl?: string }>(
        `http://127.0.0.1:${port}/json/version`, Math.max(1, Math.min(5000, deadline - Date.now())), signal
      );
      if (j.webSocketDebuggerUrl) return j.webSocketDebuggerUrl;
      throw new Error("Missing webSocketDebuggerUrl");
    } catch (error) { signal?.throwIfAborted(); lastError = error; }
    await sleep(Math.min(200, Math.max(0, deadline - Date.now())));
  }
  throw new Error(`Chrome debug port not ready: ${String(lastError)}`, { cause: lastError });
}

export async function launchChrome(url: string, port: number, headless: boolean, profileDir: string): Promise<ChildProcess> {
  const chrome = findChromeExecutable();
  if (!chrome) throw new Error("Chrome executable not found. Install Chrome or set URL_CHROME_PATH env.");

  const args = [
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profileDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-popup-blocking",
  ];
  if (headless) args.push("--headless=new");
  args.push(url);

  const child = spawn(chrome, args, { stdio: "ignore" });
  await new Promise<void>((resolve, reject) => {
    const onError = (error: Error) => { child.off("spawn", onSpawn); reject(error); };
    const onSpawn = () => { child.off("error", onError); resolve(); };
    child.once("error", onError);
    child.once("spawn", onSpawn);
  });
  return child;
}

export async function waitForNetworkIdle(cdp: CdpConnection, sessionId: string, idleMs: number = NETWORK_IDLE_TIMEOUT_MS, timeoutMs = 30_000): Promise<void> {
  return new Promise((resolve, reject) => {
    let idleTimer: ReturnType<typeof setTimeout> | undefined;
    const requests = new Set<string>();
    const cleanup = () => {
      clearTimeout(idleTimer);
      clearTimeout(deadline);
      cdp.off("Network.requestWillBeSent", onRequest, sessionId);
      cdp.off("Network.loadingFinished", onFinish, sessionId);
      cdp.off("Network.loadingFailed", onFinish, sessionId);
    };
    const resetTimer = () => {
      clearTimeout(idleTimer);
      if (!requests.size) idleTimer = setTimeout(() => { cleanup(); resolve(); }, idleMs);
    };
    const onRequest = (params: unknown) => { requests.add((params as { requestId: string }).requestId); resetTimer(); };
    const onFinish = (params: unknown) => { requests.delete((params as { requestId: string }).requestId); resetTimer(); };
    const deadline = setTimeout(() => { cleanup(); reject(new Error("Network idle timeout")); }, timeoutMs);
    cdp.on("Network.requestWillBeSent", onRequest, sessionId);
    cdp.on("Network.loadingFinished", onFinish, sessionId);
    cdp.on("Network.loadingFailed", onFinish, sessionId);
    resetTimer();
  });
}

export async function waitForPageLoad(cdp: CdpConnection, sessionId: string, timeoutMs: number = 30_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await evaluateScript<string>(cdp, sessionId, "document.readyState", Math.max(1, deadline - Date.now())) === "complete") return;
    await sleep(Math.min(100, Math.max(0, deadline - Date.now())));
  }
  throw new Error("Page load timeout");
}

export async function createTargetAndAttach(cdp: CdpConnection, url: string): Promise<{ targetId: string; sessionId: string }> {
  const { targetId } = await cdp.send<{ targetId: string }>("Target.createTarget", { url });
  if (!targetId) throw new Error("Created page target missing");
  const { targetInfos } = await cdp.send<{ targetInfos: Array<{ targetId: string; type: string }> }>("Target.getTargets");
  const matches = targetInfos.filter(target => target.targetId === targetId && target.type === "page");
  if (matches.length !== 1) throw new Error("Created page target missing or ambiguous");
  const { sessionId } = await cdp.send<{ sessionId: string }>("Target.attachToTarget", { targetId, flatten: true });
  if (!sessionId) throw new Error("Attached page session missing");
  await cdp.send("Network.enable", {}, { sessionId });
  await cdp.send("Page.enable", {}, { sessionId });
  return { targetId, sessionId };
}

export async function navigateAndWait(cdp: CdpConnection, sessionId: string, url: string, timeoutMs: number): Promise<void> {
  const result = await cdp.send<{ errorText?: string }>("Page.navigate", { url }, { sessionId, timeoutMs });
  if (result.errorText) throw new Error(`Navigation failed: ${result.errorText}`);
  await waitForPageLoad(cdp, sessionId, timeoutMs);
}

export async function evaluateScript<T>(cdp: CdpConnection, sessionId: string, expression: string, timeoutMs: number = 30_000): Promise<T> {
  const result = await cdp.send<{ result: { value?: T; type?: string; description?: string }; exceptionDetails?: { text?: string; exception?: { description?: string } } }>(
    "Runtime.evaluate",
    { expression, returnByValue: true, awaitPromise: true },
    { sessionId, timeoutMs }
  );
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || "Page evaluation failed");
  return result.result.value as T;
}

export async function autoScroll(cdp: CdpConnection, sessionId: string, steps: number = 8, waitMs: number = 600): Promise<void> {
  let lastHeight = await evaluateScript<number>(cdp, sessionId, "document.body.scrollHeight");
  for (let i = 0; i < steps; i++) {
    await evaluateScript<void>(cdp, sessionId, "window.scrollTo(0, document.body.scrollHeight)");
    await sleep(waitMs);
    const newHeight = await evaluateScript<number>(cdp, sessionId, "document.body.scrollHeight");
    if (newHeight === lastHeight) break;
    lastHeight = newHeight;
  }
  await evaluateScript<void>(cdp, sessionId, "window.scrollTo(0, 0)");
}

export async function killChrome(chrome: ChildProcess): Promise<void> {
  if (chrome.exitCode !== null || chrome.signalCode !== null) return;
  await new Promise<void>((resolve, reject) => {
    let forceTimer: ReturnType<typeof setTimeout>;
    let deadline: ReturnType<typeof setTimeout>;
    const cleanup = () => { clearTimeout(forceTimer); clearTimeout(deadline); chrome.off("exit", onExit); chrome.off("error", onError); };
    const onExit = () => { cleanup(); resolve(); };
    const onError = (error: Error) => { cleanup(); reject(error); };
    chrome.once("exit", onExit);
    chrome.once("error", onError);
    forceTimer = setTimeout(() => {
      try { chrome.kill("SIGKILL"); } catch (error) { onError(error as Error); }
    }, 2000);
    deadline = setTimeout(() => { cleanup(); reject(new Error("Chrome exit timeout")); }, 5000);
    try { chrome.kill("SIGTERM"); } catch (error) { onError(error as Error); }
  });
}

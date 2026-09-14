/** CLI capture: one newly created target, temporary profile, stdout unless -o is explicit. */
import { createInterface } from "node:readline";
import { writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

import { CdpConnection, getFreePort, launchChrome, waitForChromeDebugPort, waitForNetworkIdle, waitForPageLoad, autoScroll, evaluateScript, killChrome, createTargetAndAttach } from "./cdp.js";
import { cleanupAndExtractScript, htmlToMarkdown, createMarkdownDocument, type PageMetadata, type ConversionResult } from "./html-to-markdown.js";
import { createChromeProfile } from "./paths.js";
import { DEFAULT_TIMEOUT_MS, CDP_CONNECT_TIMEOUT_MS, NETWORK_IDLE_TIMEOUT_MS, POST_LOAD_DELAY_MS, SCROLL_STEP_WAIT_MS, SCROLL_MAX_STEPS } from "./constants.js";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export interface Args {
  url: string;
  output?: string;
  profile?: string;
  wait: boolean;
  timeout: number;
}

export function parseArgs(argv: string[]): Args {
  const args: Args = { url: "", wait: false, timeout: DEFAULT_TIMEOUT_MS };
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i]!;
    if (arg === "--wait" || arg === "-w") {
      args.wait = true;
    } else if (["-o", "--output", "--profile", "--timeout", "-t"].includes(arg)) {
      const value = argv[++i];
      if (!value || value.startsWith("-")) throw new Error(`Missing value for ${arg}`);
      if (arg === "--profile") args.profile = value;
      else if (arg === "-o" || arg === "--output") args.output = value;
      else {
        args.timeout = Number(value);
        if (!Number.isSafeInteger(args.timeout) || args.timeout <= 0) throw new Error("Timeout must be a positive integer (ms)");
      }
    } else if (!arg.startsWith("-") && !args.url) {
      args.url = arg;
    } else throw new Error(`Unexpected argument: ${arg}`);
  }
  if (!args.url) throw new Error("Usage: bun scripts/main.ts <url> [-o output.md] [--wait] [--timeout ms] [--profile directory]");
  if (!["http:", "https:"].includes(new URL(args.url).protocol)) throw new Error("Only HTTP(S) URLs are supported");
  return args;
}

export async function waitForPageReady(cdp: CdpConnection, sessionId: string, targetUrl: string, timeoutMs: number): Promise<void> {
  console.error("Page opened. Log in if necessary; press Enter to capture the bound page.");
  const rl = createInterface({ input: process.stdin, output: process.stderr });
  let manual = false;
  rl.once("line", () => { manual = true; });
  const deadline = Date.now() + timeoutMs;
  try {
    while (Date.now() < deadline) {
      if (manual) return;
      const state = await evaluateScript<{ url: string; title: string; ready: string }>(
        cdp, sessionId, "({ url: window.location.href, title: document.title, ready: document.readyState })", Math.max(1, Math.min(1000, deadline - Date.now()))
      );
      // Hostname equality, never substring matching against a URL or query string.
      if (state && new URL(state.url).hostname === new URL(targetUrl).hostname && state.ready === "complete" && !/sign in|log in|happening now|the everything app/i.test(state.title)) return;
      await sleep(Math.min(200, Math.max(0, deadline - Date.now())));
    }
    throw new Error("Timed out waiting for target page or manual capture");
  } finally {
    rl.close();
  }
}

export async function captureUrl(args: Args): Promise<ConversionResult> {
  const profile = await createChromeProfile(args.profile);
  let chrome: Awaited<ReturnType<typeof launchChrome>> | null = null;
  let cdp: CdpConnection | null = null;
  let failed = false;
  let interrupted = false;
  const debugRequest = new AbortController();
  const onInterrupt = () => {
    interrupted = true;
    debugRequest.abort(new Error("Capture interrupted"));
    try { cdp?.close(); } catch (error) { console.error("Interrupt cleanup error:", error); }
  };
  process.once("SIGINT", onInterrupt);
  process.once("SIGTERM", onInterrupt);
  try {
    const port = await getFreePort();
    chrome = await launchChrome("about:blank", port, false, profile.directory);
    const wsUrl = await waitForChromeDebugPort(port, Math.min(args.timeout, 30_000), debugRequest.signal);
    cdp = await CdpConnection.connect(wsUrl, Math.min(args.timeout, CDP_CONNECT_TIMEOUT_MS));
    if (interrupted) throw new Error("Capture interrupted");
    // Creation gives an unambiguous identity even when navigation redirects or other tabs exist.
    const { sessionId } = await createTargetAndAttach(cdp, "about:blank");
    const navigation = await cdp.send<{ errorText?: string }>("Page.navigate", { url: args.url }, { sessionId, timeoutMs: args.timeout });
    if (navigation.errorText) throw new Error(`Navigation failed: ${navigation.errorText}`);
    if (args.wait) {
      await waitForPageReady(cdp, sessionId, args.url, args.timeout);
    } else {
      console.error("Waiting for bound page to load...");
      await waitForPageLoad(cdp, sessionId, args.timeout);
      await waitForNetworkIdle(cdp, sessionId, NETWORK_IDLE_TIMEOUT_MS, args.timeout);
      await sleep(POST_LOAD_DELAY_MS);
      await autoScroll(cdp, sessionId, SCROLL_MAX_STEPS, SCROLL_STEP_WAIT_MS);
      await sleep(POST_LOAD_DELAY_MS);
    }

    if (interrupted) throw new Error("Capture interrupted");
    console.error("Capturing bound main page (frames and other tabs excluded)...");
    const extracted = await evaluateScript<{ title: string; description?: string; author?: string; published?: string; html: string }>(
      cdp, sessionId, cleanupAndExtractScript, args.timeout
    );
    if (!extracted || typeof extracted.html !== "string" || !extracted.html.trim()) throw new Error("No main-page content extracted");
    const capturedUrl = await evaluateScript<string>(cdp, sessionId, "window.location.href", args.timeout);
    const metadata: PageMetadata = {
      url: capturedUrl,
      title: extracted.title || "",
      description: extracted.description,
      author: extracted.author,
      published: extracted.published,
      captured_at: new Date().toISOString()
    };
    const markdown = htmlToMarkdown(extracted.html);
    if (!markdown.trim()) throw new Error("No Markdown content extracted");
    return { metadata, markdown };
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    const cleanupErrors: unknown[] = [];
    try { cdp?.close(); } catch (error) { cleanupErrors.push(error); }
    let stopped = !chrome;
    if (chrome) {
      try { await killChrome(chrome); stopped = true; } catch (error) { cleanupErrors.push(error); }
    }
    if (stopped) {
      try { await profile.cleanup(); } catch (error) { cleanupErrors.push(error); }
    } else console.error(`Chrome exit unconfirmed; profile retained for recovery: ${profile.directory}`);
    for (const error of cleanupErrors) console.error("Cleanup error:", error);
    process.off("SIGINT", onInterrupt);
    process.off("SIGTERM", onInterrupt);
    if (interrupted) throw new Error("Capture interrupted");
    if (!failed && cleanupErrors.length) throw new AggregateError(cleanupErrors, "Capture cleanup failed");
  }
}

export async function main(argv = process.argv): Promise<void> {
  const args = parseArgs(argv);
  console.error(`Fetching: ${args.url}`);
  const result = await captureUrl(args);
  const document = createMarkdownDocument(result);
  if (args.output) {
    const outputPath = path.resolve(args.output);
    await mkdir(path.dirname(outputPath), { recursive: true });
    await writeFile(outputPath, document, "utf-8");
    console.error(`Saved: ${outputPath}`);
  } else {
    process.stdout.write(document + "\n");
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch((err) => {
    console.error("Error:", err instanceof Error ? err.message : String(err));
    process.exitCode = 1;
  });
}

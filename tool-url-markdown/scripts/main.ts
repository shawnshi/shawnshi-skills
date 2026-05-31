/**
 * <!-- Input: URL, Output Path (Optional), Wait Flag -->
 * <!-- Output: Markdown File, Metadata (YAML Frontmatter) -->
 * <!-- Pos: scripts/main.ts. CLI Entry Point for CDP Capturer. -->
 *
 * !!! Maintenance Protocol: This script orchestrates Chrome launch and page evaluation.
 * !!! Dependency: Requires 'bun' runtime and local Chrome installation.
 */

import { createInterface } from "node:readline";
import { writeFile, mkdir, access } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import { CdpConnection, getFreePort, launchChrome, waitForChromeDebugPort, waitForNetworkIdle, waitForPageLoad, autoScroll, evaluateScript, killChrome } from "./cdp.js";
import { cleanupAndExtractScript, htmlToMarkdown, createMarkdownDocument, type PageMetadata, type ConversionResult } from "./html-to-markdown.js";
import { resolveUrlToMarkdownDataDir } from "./paths.js";
import { DEFAULT_TIMEOUT_MS, CDP_CONNECT_TIMEOUT_MS, NETWORK_IDLE_TIMEOUT_MS, POST_LOAD_DELAY_MS, SCROLL_STEP_WAIT_MS, SCROLL_MAX_STEPS } from "./constants.js";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fileExists(filePath: string): Promise<boolean> {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

interface Args {
  url: string;
  output?: string;
  wait: boolean;
  timeout: number;
}

function parseArgs(argv: string[]): Args {
  const args: Args = { url: "", wait: false, timeout: DEFAULT_TIMEOUT_MS };
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--wait" || arg === "-w") {
      args.wait = true;
    } else if (arg === "-o" || arg === "--output") {
      args.output = argv[++i];
    } else if (arg === "--timeout" || arg === "-t") {
      args.timeout = parseInt(argv[++i], 10) || DEFAULT_TIMEOUT_MS;
    } else if (!arg.startsWith("-") && !args.url) {
      args.url = arg;
    }
  }
  return args;
}

function generateSlug(title: string, url: string): string {
  const text = title || new URL(url).pathname.replace(/\//g, "-");
  return text
    .replace(/[\\\/:*?"<>|]/g, "") // Remove illegal filename characters
    .trim()
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 150) || "page";
}

function formatTimestamp(): string {
  const now = new Date();
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

async function generateOutputPath(url: string, title: string): Promise<string> {
  const slug = generateSlug(title, url);
  const dataDir = process.cwd(); // Save to current directory
  const basePath = path.join(dataDir, `${slug}.md`);

  if (!(await fileExists(basePath))) {
    return basePath;
  }

  const timestampSlug = `${slug}-${formatTimestamp()}`;
  return path.join(dataDir, `${timestampSlug}.md`);
}

async function waitForPageReady(cdp: CdpConnection, sessionId: string, targetUrl: string): Promise<void> {
  console.log("Page opened. Please log in if necessary.");
  console.log("Waiting for target page to load... (Or press Enter to force capture)");

  const rl = createInterface({ input: process.stdin, output: process.stdout });
  let resolved = false;

  const manualSignal = new Promise<void>((resolve) => {
    rl.once("line", () => {
      if (!resolved) {
        console.log("Manual capture triggered.");
        resolved = true;
        rl.close();
        resolve();
      }
    });
  });

  const autoCheck = new Promise<void>(async (resolve) => {
    const targetHostname = new URL(targetUrl).hostname;
    
    while (!resolved) {
      try {
        const expr = `({ url: window.location.href, title: document.title, ready: document.readyState })`;
        // Use a short timeout for the check to avoid blocking
        const state = await evaluateScript<{url: string, title: string, ready: string}>(cdp, sessionId, expr, 1000);
        
        // Logic: We are back on the target domain (e.g. draft.blogger.com) AND title doesn't look like a login page
        if (state && state.url && state.url.includes(targetHostname)) {
           const isLoginPage = state.title.toLowerCase().includes("sign in") || state.url.includes("accounts.google.com");
           
           if (!isLoginPage && state.ready === 'complete') {
             console.log(`\nAuto-detected target page: "${state.title}"`);
             console.log("Giving it 5 seconds to finish rendering and load iframes...");
             await sleep(5000); // Wait for client-side hydration and iframes
             resolved = true;
             rl.close();
             resolve();
             return;
           }
        }
      } catch (e) {
        // Ignore evaluation errors during navigation/reloads
      }
      await sleep(1000);
    }
  });

  await Promise.race([manualSignal, autoCheck]);
}

async function captureUrl(args: Args): Promise<ConversionResult> {
  const port = await getFreePort();
  const chrome = await launchChrome(args.url, port, false);

  let cdp: CdpConnection | null = null;
  try {
    const wsUrl = await waitForChromeDebugPort(port, 30_000);
    cdp = await CdpConnection.connect(wsUrl, CDP_CONNECT_TIMEOUT_MS);

    const targets = await cdp.send<{ targetInfos: Array<{ targetId: string; type: string; url: string }> }>("Target.getTargets");
    const pageTarget = targets.targetInfos.find(t => t.type === "page" && t.url.startsWith("http"));
    if (!pageTarget) throw new Error("No page target found");

    const { sessionId } = await cdp.send<{ sessionId: string }>("Target.attachToTarget", { targetId: pageTarget.targetId, flatten: true });
    await cdp.send("Network.enable", {}, { sessionId });
    await cdp.send("Page.enable", {}, { sessionId });

    if (args.wait) {
      await waitForPageReady(cdp, sessionId, args.url);
    } else {
      console.log("Waiting for page to load...");
      await Promise.race([
        waitForPageLoad(cdp, sessionId, 15_000),
        sleep(8_000)
      ]);
      await waitForNetworkIdle(cdp, sessionId, NETWORK_IDLE_TIMEOUT_MS);
      await sleep(POST_LOAD_DELAY_MS);
      console.log("Scrolling to trigger lazy load...");
      await autoScroll(cdp, sessionId, SCROLL_MAX_STEPS, SCROLL_STEP_WAIT_MS);
      await sleep(POST_LOAD_DELAY_MS);
    }

    console.log("Capturing page content...");
    const extracted = await evaluateScript<{ title: string; description?: string; author?: string; published?: string; html: string }>(
      cdp, sessionId, cleanupAndExtractScript, args.timeout
    );

    let combinedHtml = extracted.html;
    let combinedTitle = extracted.title || "";

    // Try to find content in other targets (iframes that might be separate targets)
    try {
      for (const target of targets.targetInfos) {
        if (target.type === "iframe" || (target.type === "page" && target.targetId !== pageTarget.targetId)) {
          try {
            const { sessionId: frameSessionId } = await cdp.send<{ sessionId: string }>("Target.attachToTarget", { targetId: target.targetId, flatten: true });
            await cdp.send("Runtime.enable", {}, { sessionId: frameSessionId });
            const frameContent = await evaluateScript<{ title: string; html: string }>(
              cdp, frameSessionId, "({ title: document.title, html: document.body ? document.body.innerHTML : '' })", 5000
            );
            if (frameContent.html && frameContent.html.length > 200) {
              console.log(`Captured additional content from target: ${target.url || frameContent.title}`);
              combinedHtml += `\n<!-- Target Content Start: ${target.url} -->\n${frameContent.html}\n<!-- Target Content End -->\n`;
              if (!combinedTitle || combinedTitle === "Post: Preview") {
                combinedTitle = frameContent.title || combinedTitle;
              }
            }
            await cdp.send("Target.detachFromTarget", { sessionId: frameSessionId });
          } catch (e) {
            // Skip frames that fail to attach or evaluate
          }
        }
      }
    } catch (e) {}

    const metadata: PageMetadata = {
      url: args.url,
      title: combinedTitle,
      description: extracted.description,
      author: extracted.author,
      published: extracted.published,
      captured_at: new Date().toISOString()
    };

    const markdown = htmlToMarkdown(combinedHtml);
    return { metadata, markdown };
  } finally {
    if (cdp) {
      try { await cdp.send("Browser.close", {}, { timeoutMs: 5_000 }); } catch {}
      cdp.close();
    }
    killChrome(chrome);
  }
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv);
  if (!args.url) {
    console.error("Usage: bun main.ts <url> [-o output.md] [--wait] [--timeout ms]");
    process.exit(1);
  }

  try {
    new URL(args.url);
  } catch {
    console.error(`Invalid URL: ${args.url}`);
    process.exit(1);
  }

  console.log(`Fetching: ${args.url}`);
  console.log(`Mode: ${args.wait ? "wait" : "auto"}`);

  const result = await captureUrl(args);
  const outputPath = path.resolve(args.output || await generateOutputPath(args.url, result.metadata.title));
  const outputDir = path.dirname(outputPath);
  
  try {
    await mkdir(outputDir, { recursive: true });
  } catch (e: any) {
    if (e.code !== 'EEXIST') throw e;
  }

  const document = createMarkdownDocument(result);
  await writeFile(outputPath, document, "utf-8");

  console.log(`Saved: ${outputPath}`);
  console.log(`Title: ${result.metadata.title || "(no title)"}`);
}

main().catch((err) => {
  console.error("Error:", err instanceof Error ? err.message : String(err));
  process.exit(1);
});

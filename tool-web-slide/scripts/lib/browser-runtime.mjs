import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { lstat, readFile, realpath } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import {
  parseDeliveryProfile,
  parseTargetBrowser,
  parseTargetOs,
  requiredGatesFor
} from './delivery-contract.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const skillRoot = resolve(here, '..', '..');

export class BrowserRuntimeError extends Error {
  constructor(message, details = {}) {
    super(message);
    this.name = 'BrowserRuntimeError';
    this.details = details;
  }
}

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function pathInside(root, candidate) {
  const relation = relative(root, candidate);
  return relation === '' || (!relation.startsWith('..') && !isAbsolute(relation));
}

async function snapshotRegularFile(deckRoot, deckRootReal, relativePath, expected = null) {
  if (typeof relativePath !== 'string' || !relativePath || relativePath.includes('\\')
      || relativePath.startsWith('/') || /^[A-Za-z]:/.test(relativePath)
      || relativePath.split('/').some(part => !part || part === '.' || part === '..')) {
    throw new BrowserRuntimeError(`delivery-manifest.json contains an unsafe file path: ${relativePath}`);
  }
  const filePath = resolve(deckRoot, ...relativePath.split('/'));
  if (!pathInside(deckRoot, filePath)) throw new BrowserRuntimeError(`Delivery file escapes its root: ${relativePath}`);
  if (!existsSync(filePath)) throw new BrowserRuntimeError(`Delivery file is missing: ${relativePath}`);
  const info = await lstat(filePath);
  if (info.isSymbolicLink() || !info.isFile()) throw new BrowserRuntimeError(`Delivery file must be a regular non-symlink file: ${relativePath}`);
  const actual = await realpath(filePath);
  if (!pathInside(deckRootReal, actual)) throw new BrowserRuntimeError(`Delivery file escapes its root through a symlink: ${relativePath}`);
  const bytes = await readFile(filePath);
  const receipt = { path: relativePath, bytes: bytes.length, sha256: sha256(bytes) };
  if (expected) {
    if (!Number.isInteger(expected.bytes) || expected.bytes < 0 || expected.bytes !== receipt.bytes) {
      throw new BrowserRuntimeError(`Delivery file byte count mismatch: ${relativePath}`);
    }
    if (!/^[a-f0-9]{64}$/.test(expected.sha256 || '') || expected.sha256 !== receipt.sha256) {
      throw new BrowserRuntimeError(`Delivery file hash mismatch: ${relativePath}`);
    }
  }
  return receipt;
}

export async function captureDeliverySnapshot(htmlPath) {
  const resolvedHtml = resolve(htmlPath);
  const deckRoot = dirname(resolvedHtml);
  const deckRootReal = await realpath(deckRoot);
  const inputRelative = relative(deckRoot, resolvedHtml).split('\\').join('/');
  const input = await snapshotRegularFile(deckRoot, deckRootReal, inputRelative);
  const manifestPath = join(deckRoot, 'delivery-manifest.json');
  let manifestSha256 = null;
  let files = [input];
  if (existsSync(manifestPath)) {
    const manifestInfo = await lstat(manifestPath);
    if (manifestInfo.isSymbolicLink() || !manifestInfo.isFile()) {
      throw new BrowserRuntimeError('delivery-manifest.json must be a regular non-symlink file.');
    }
    if (!pathInside(deckRootReal, await realpath(manifestPath))) {
      throw new BrowserRuntimeError('delivery-manifest.json escapes the delivery root.');
    }
    const manifestBytes = await readFile(manifestPath);
    manifestSha256 = sha256(manifestBytes);
    let manifest;
    try { manifest = JSON.parse(manifestBytes.toString('utf8')); }
    catch (error) { throw new BrowserRuntimeError(`Cannot snapshot delivery-manifest.json: ${error.message}`); }
    if (!Array.isArray(manifest.files) || !manifest.files.length) {
      throw new BrowserRuntimeError('delivery-manifest.json must contain a non-empty files[] integrity ledger.');
    }
    const seen = new Set();
    files = [];
    for (const entry of manifest.files) {
      if (!entry || typeof entry !== 'object' || typeof entry.path !== 'string') {
        throw new BrowserRuntimeError('delivery-manifest.json contains an invalid files[] entry.');
      }
      if (seen.has(entry.path)) throw new BrowserRuntimeError(`delivery-manifest.json contains a duplicate file path: ${entry.path}`);
      seen.add(entry.path);
      files.push(await snapshotRegularFile(deckRoot, deckRootReal, entry.path, entry));
    }
    const inputEntry = files.find(entry => entry.path === inputRelative);
    if (!inputEntry || inputEntry.sha256 !== input.sha256) {
      throw new BrowserRuntimeError('delivery-manifest.json does not bind the current HTML input.');
    }
  }
  files.sort((left, right) => left.path.localeCompare(right.path, 'en'));
  return {
    htmlPath: resolvedHtml,
    inputFile: inputRelative,
    inputSha256: input.sha256,
    manifestFile: manifestSha256 ? 'delivery-manifest.json' : null,
    manifestSha256,
    files
  };
}

export async function assertDeliverySnapshotStable(snapshot) {
  const current = await captureDeliverySnapshot(snapshot.htmlPath);
  if (current.inputSha256 !== snapshot.inputSha256
      || current.manifestSha256 !== snapshot.manifestSha256
      || JSON.stringify(current.files) !== JSON.stringify(snapshot.files)) {
    throw new BrowserRuntimeError('Delivery files changed while browser rendering was in progress; refusing to publish a stale QA receipt.');
  }
  return current;
}

function unique(values) {
  return [...new Set(values.filter(Boolean).map(value => resolve(String(value))))];
}

export async function loadPlaywright() {
  const require = createRequire(import.meta.url);
  const roots = unique([
    skillRoot,
    process.cwd(),
    process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES,
    process.env.CODEX_PRIMARY_RUNTIME_ROOT
      ? join(process.env.CODEX_PRIMARY_RUNTIME_ROOT, 'dependencies', 'node', 'node_modules')
      : null
  ]);
  const attempts = [];

  for (const root of roots) {
    try {
      const resolved = require.resolve('playwright', { paths: [root] });
      const imported = await import(pathToFileURL(resolved).href);
      const api = imported.chromium ? imported : imported.default;
      if (api?.chromium) return { api, resolved };
    } catch (error) {
      attempts.push(`${root}: ${error.code || error.message}`);
    }
  }

  throw new BrowserRuntimeError(
    'Playwright is not available. Install the declared project dependency before running browser QA or PDF export.',
    { attempts }
  );
}

export function normalizeTargetBrowser(value = 'chromium') {
  try { return parseTargetBrowser(value); }
  catch (error) {
    throw new BrowserRuntimeError(`Unsupported target.browser "${value}". Expected chromium, chrome, or edge.`, { cause: error.name });
  }
}

export function normalizeTargetOs(value = 'current') {
  try { return parseTargetOs(value); }
  catch (error) {
    throw new BrowserRuntimeError(`Unsupported target.os "${value}". Expected current, linux, macos, or windows.`, { cause: error.name });
  }
}

export function currentOs(platform = process.platform) {
  if (platform === 'linux') return 'linux';
  if (platform === 'darwin') return 'macos';
  if (platform === 'win32') return 'windows';
  return String(platform || 'unknown');
}

export function assertTargetOs(targetOs = 'current', platform = process.platform) {
  const target = normalizeTargetOs(targetOs);
  const actual = currentOs(platform);
  if (target !== 'current' && target !== actual) {
    throw new BrowserRuntimeError(`Deck target.os=${target} does not match the current runtime OS=${actual}. Render on the declared target OS or change deck.config explicitly.`);
  }
  return { targetOs: target, resolvedTargetOs: target === 'current' ? actual : target, actualOs: actual };
}

function platformBrowserPaths(targetBrowser) {
  const env = process.env;
  const explicit = targetBrowser === 'chromium'
    ? [env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH]
    : targetBrowser === 'chrome'
      ? [env.CHROME_PATH, env.GOOGLE_CHROME_BIN]
      : [env.EDGE_PATH, env.MSEDGE_PATH];
  if (process.platform === 'win32') {
    const bases = [env.PROGRAMFILES, env['PROGRAMFILES(X86)'], env.LOCALAPPDATA].filter(Boolean);
    if (targetBrowser === 'chromium') return explicit;
    const parts = targetBrowser === 'chrome'
      ? ['Google', 'Chrome', 'Application', 'chrome.exe']
      : ['Microsoft', 'Edge', 'Application', 'msedge.exe'];
    return [...explicit, ...bases.map(base => join(base, ...parts))];
  }
  if (process.platform === 'darwin') {
    if (targetBrowser === 'chrome') return [...explicit, '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'];
    if (targetBrowser === 'edge') return [...explicit, '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'];
    return [...explicit, '/Applications/Chromium.app/Contents/MacOS/Chromium'];
  }
  if (targetBrowser === 'chrome') return [...explicit,
    '/usr/bin/google-chrome-stable', '/usr/bin/google-chrome', '/opt/google/chrome/chrome'];
  if (targetBrowser === 'edge') return [...explicit,
    '/usr/bin/microsoft-edge', '/usr/bin/microsoft-edge-stable', '/opt/microsoft/msedge/msedge'];
  return [...explicit, '/usr/bin/chromium', '/usr/bin/chromium-browser', '/snap/bin/chromium'];
}

export function findBrowserExecutable(chromium, targetBrowser = 'chromium') {
  const target = normalizeTargetBrowser(targetBrowser);
  const candidates = [];
  if (target === 'chromium') {
    try {
      const bundled = chromium?.executablePath?.();
      if (bundled) candidates.push({ path: bundled, source: 'playwright', browser: target });
    } catch (_) { /* browser package may be installed without browser binaries */ }
  }
  platformBrowserPaths(target).filter(Boolean).forEach(path => candidates.push({ path, source: 'system', browser: target }));
  return candidates.find(candidate => existsSync(candidate.path)) || null;
}

export function resolveChromiumLaunchArgs(options = {}) {
  const args = [...(options.args || [])];
  const isRoot = options.isRoot ?? (
    process.platform === 'linux'
    && typeof process.getuid === 'function'
    && process.getuid() === 0
  );
  const allowNoSandbox = options.allowNoSandbox ?? process.env.WEB_SLIDE_ALLOW_NO_SANDBOX === '1';
  const requestedNoSandbox = args.some(arg => ['--no-sandbox', '--disable-setuid-sandbox'].includes(arg));
  if ((isRoot || requestedNoSandbox) && !allowNoSandbox) {
    throw new BrowserRuntimeError(
      'Refusing to disable the Chromium sandbox. Run as a non-root user, or explicitly set WEB_SLIDE_ALLOW_NO_SANDBOX=1 after accepting the security risk.'
    );
  }
  if (isRoot && allowNoSandbox) {
    for (const flag of ['--no-sandbox', '--disable-setuid-sandbox']) if (!args.includes(flag)) args.push(flag);
  }
  return { args, isRoot, noSandbox: isRoot && allowNoSandbox };
}

export async function inspectBrowserRuntime(options = {}) {
  const nodeMajor = Number(process.versions.node.split('.')[0]);
  if (nodeMajor < 18) {
    return { ok: false, node: process.versions.node, error: 'Node.js 18 or newer is required.' };
  }
  try {
    const targetBrowser = normalizeTargetBrowser(options.targetBrowser || 'chromium');
    const sandbox = resolveChromiumLaunchArgs();
    const { api, resolved } = await loadPlaywright();
    const executable = findBrowserExecutable(api.chromium, targetBrowser);
    return executable
      ? { ok: true, node: process.versions.node, playwright: resolved, targetBrowser, browser: executable, sandbox }
      : {
          ok: false,
          node: process.versions.node,
          playwright: resolved,
          targetBrowser,
          error: `Playwright is installed, but no executable for target.browser=${targetBrowser} was found.`
        };
  } catch (error) {
    return { ok: false, node: process.versions.node, error: error.message, details: error.details };
  }
}

export async function launchChromium(options = {}) {
  const targetBrowser = normalizeTargetBrowser(options.targetBrowser || 'chromium');
  const launchPolicy = resolveChromiumLaunchArgs(options);
  const { api, resolved } = await loadPlaywright();
  const executable = findBrowserExecutable(api.chromium, targetBrowser);
  if (!executable) {
    throw new BrowserRuntimeError(
      `No executable for target.browser=${targetBrowser} was found. Install that browser or set its explicit path environment variable.`,
      { playwright: resolved, targetBrowser }
    );
  }
  const browser = await api.chromium.launch({
    headless: options.headless !== false,
    executablePath: executable.path,
    args: launchPolicy.args
  });
  return { browser, executable, playwright: resolved, sandbox: launchPolicy, targetBrowser };
}

function normalizedNetworkOrigin(value) {
  const url = new URL(value);
  if (url.protocol === 'ws:') url.protocol = 'http:';
  if (url.protocol === 'wss:') url.protocol = 'https:';
  return url.origin;
}

export function isNetworkRequestAllowed(requestUrl, allowedOrigin, allowNetwork = false) {
  let url;
  try { url = new URL(requestUrl); } catch (_) { return false; }
  if (['data:', 'blob:', 'about:'].includes(url.protocol)) return true;
  if (!['http:', 'https:', 'ws:', 'wss:'].includes(url.protocol)) return false;
  if (allowNetwork) return true;
  try { return normalizedNetworkOrigin(url.href) === new URL(allowedOrigin).origin; }
  catch (_) { return false; }
}

export async function installNetworkPolicy(page, options = {}) {
  const allowedOrigin = new URL(options.allowedOrigin).origin;
  const allowNetwork = options.allowNetwork === true;
  const policy = {
    mode: allowNetwork ? 'allow-network' : 'isolated',
    allowNetwork,
    allowedOrigin,
    externalOrigins: [],
    allowedExternalRequests: [],
    allowedExternalWebSockets: [],
    blockedRequests: [],
    blockedWebSockets: []
  };
  await page.route('**/*', async route => {
    const request = route.request();
    if (isNetworkRequestAllowed(request.url(), allowedOrigin, allowNetwork)) {
      if (allowNetwork) {
        try {
          const parsed = new URL(request.url());
          if (!['http:', 'https:', 'ws:', 'wss:'].includes(parsed.protocol)) throw new Error('not a network URL');
          const origin = normalizedNetworkOrigin(parsed.href);
          if (origin !== allowedOrigin) {
            if (!policy.externalOrigins.includes(origin)) policy.externalOrigins.push(origin);
            if (policy.allowedExternalRequests.length < 500) {
              policy.allowedExternalRequests.push({ url: request.url(), method: request.method(), resourceType: request.resourceType() });
            }
          }
        } catch (_) { /* data/blob/about requests have no network origin */ }
      }
      await route.continue();
      return;
    }
    if (policy.blockedRequests.length < 500) {
      policy.blockedRequests.push({ url: request.url(), method: request.method(), resourceType: request.resourceType() });
    }
    await route.abort('blockedbyclient');
  });
  if (typeof page.routeWebSocket === 'function') {
    await page.routeWebSocket(/.*/, async socket => {
      if (isNetworkRequestAllowed(socket.url(), allowedOrigin, allowNetwork)) {
        if (allowNetwork) {
          try {
            const parsed = new URL(socket.url());
            if (!['http:', 'https:', 'ws:', 'wss:'].includes(parsed.protocol)) throw new Error('not a network URL');
            const origin = normalizedNetworkOrigin(parsed.href);
            if (origin !== allowedOrigin) {
              if (!policy.externalOrigins.includes(origin)) policy.externalOrigins.push(origin);
              if (policy.allowedExternalWebSockets.length < 100) policy.allowedExternalWebSockets.push({ url: socket.url() });
            }
          } catch (_) { /* invalid socket URLs are rejected by the policy above */ }
        }
        socket.connectToServer();
        return;
      }
      if (policy.blockedWebSockets.length < 100) policy.blockedWebSockets.push({ url: socket.url() });
      await socket.close({ code: 1008, reason: 'Blocked by web-slide network policy' });
    });
  }
  return policy;
}

function dataAttribute(markup, name) {
  const pattern = new RegExp(`\\bdata-${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+))`, 'i');
  const match = markup.match(pattern);
  return match ? (match[1] ?? match[2] ?? match[3] ?? '').trim() : null;
}

export async function readDeckExecutionConfig(htmlPath) {
  const resolvedHtml = resolve(htmlPath);
  const html = await readFile(resolvedHtml, 'utf8');
  const declarations = `${html.match(/<html\b[^>]*>/i)?.[0] || ''} ${html.match(/<body\b[^>]*>/i)?.[0] || ''}`;
  const htmlValues = {
    targetBrowser: dataAttribute(declarations, 'target-browser'),
    targetOs: dataAttribute(declarations, 'target-os'),
    deliveryProfile: dataAttribute(declarations, 'delivery-profile'),
    offlineRequired: dataAttribute(declarations, 'offline-required')
  };
  let manifest = null;
  const manifestPath = join(dirname(resolvedHtml), 'delivery-manifest.json');
  if (existsSync(manifestPath)) {
    try { manifest = JSON.parse(await readFile(manifestPath, 'utf8')); }
    catch (error) { throw new BrowserRuntimeError(`Cannot read execution target from delivery-manifest.json: ${error.message}`); }
  }
  const manifestValues = {
    targetBrowser: manifest?.target?.browser ?? null,
    targetOs: manifest?.target?.os ?? null,
    deliveryProfile: manifest?.deliveryProfile ?? null,
    offlineRequired: manifest?.offlineRequired
  };
  for (const field of ['targetBrowser', 'targetOs', 'deliveryProfile']) {
    if (htmlValues[field] && manifestValues[field]
      && String(htmlValues[field]).toLowerCase() !== String(manifestValues[field]).toLowerCase()) {
      throw new BrowserRuntimeError(`Execution target mismatch between HTML and delivery-manifest.json for ${field}.`);
    }
  }
  const targetBrowser = normalizeTargetBrowser(htmlValues.targetBrowser || manifestValues.targetBrowser || 'chromium');
  const targetOs = normalizeTargetOs(htmlValues.targetOs || manifestValues.targetOs || 'current');
  let deliveryProfile;
  try { deliveryProfile = parseDeliveryProfile(htmlValues.deliveryProfile || manifestValues.deliveryProfile || 'standard-client'); }
  catch (error) { throw new BrowserRuntimeError(error.message, { cause: error.name }); }
  const requiredGates = requiredGatesFor(deliveryProfile);
  if (manifest?.requiredGates && JSON.stringify(manifest.requiredGates) !== JSON.stringify(requiredGates)) {
    throw new BrowserRuntimeError('delivery-manifest.json requiredGates do not match its deliveryProfile.');
  }
  const htmlOffline = String(htmlValues.offlineRequired || 'false').toLowerCase() === 'true';
  const manifestOffline = manifestValues.offlineRequired === true;
  if (htmlValues.offlineRequired !== null && manifest && typeof manifestValues.offlineRequired === 'boolean'
      && htmlOffline !== manifestOffline) {
    throw new BrowserRuntimeError('Execution target mismatch between HTML and delivery-manifest.json for offlineRequired.');
  }
  return {
    targetBrowser,
    targetOs,
    deliveryProfile,
    requiredGates,
    offlineRequired: htmlOffline || manifestOffline,
    manifestPath: manifest ? manifestPath : null,
    manifest
  };
}

export function resolveNetworkAccess(options = {}) {
  const requested = options.allowNetwork === true;
  const offlineRequired = options.offlineRequired === true;
  const deliveryProfile = String(options.deliveryProfile || 'unspecified').toLowerCase();
  const locked = offlineRequired || deliveryProfile === 'high-assurance';
  if (requested && locked) {
    const reason = offlineRequired ? 'offlineRequired=true' : 'deliveryProfile=high-assurance';
    throw new BrowserRuntimeError(`--allow-network is forbidden when ${reason}. Rebuild or change the governed deck configuration instead of bypassing the execution gate.`);
  }
  return {
    requested,
    allowNetwork: requested && !locked,
    offlineRequired,
    deliveryProfile,
    locked
  };
}

export function parseAspect(value, fallback = { width: 16, height: 9 }) {
  if (value && typeof value === 'object') {
    const width = Number(value.width);
    const height = Number(value.height);
    if (width > 0 && height > 0) return { width, height, ratio: width / height, label: `${width}:${height}` };
  }
  const text = String(value || '').trim().toLowerCase();
  const pair = text.match(/^(\d+(?:\.\d+)?)\s*(?::|\/|x|×)\s*(\d+(?:\.\d+)?)$/);
  if (pair) {
    const width = Number(pair[1]);
    const height = Number(pair[2]);
    if (width > 0 && height > 0) return { width, height, ratio: width / height, label: `${width}:${height}` };
  }
  const ratio = Number(text);
  if (Number.isFinite(ratio) && ratio > 0) return { width: ratio, height: 1, ratio, label: `${ratio}:1` };
  return parseAspect(fallback, { width: 16, height: 9 });
}

function boundedInteger(value, fallback) {
  const number = Math.round(Number(value));
  return Number.isFinite(number) && number >= 320 && number <= 7680 ? number : fallback;
}

export async function readDeckConfig(page) {
  const raw = await page.evaluate(() => {
    const html = document.documentElement;
    const body = document.body;
    const deck = document.getElementById('deck');
    const runtime = window.__DECK_CONFIG || {};
    const css = getComputedStyle(html);
    const first = (...values) => values.find(value => value !== undefined && value !== null && String(value).trim() !== '');
    return {
      aspect: first(
        runtime.aspect,
        html.dataset.aspect, html.dataset.deckAspect,
        body?.dataset.aspect, body?.dataset.deckAspect,
        deck?.dataset.aspect, deck?.dataset.deckAspect,
        document.querySelector('meta[name="deck:aspect"]')?.content,
        css.getPropertyValue('--deck-aspect').trim()
      ),
      width: first(runtime.width, html.dataset.deckWidth, body?.dataset.deckWidth, deck?.dataset.width),
      height: first(runtime.height, html.dataset.deckHeight, body?.dataset.deckHeight, deck?.dataset.height),
      slideCount: document.querySelectorAll('#deck > .slide, #deck .slide').length,
      deckId: html.dataset.deckId || null,
      deliveryProfile: html.dataset.deliveryProfile || body?.dataset.deliveryProfile || null,
      targetBrowser: html.dataset.targetBrowser || body?.dataset.targetBrowser || 'chromium',
      targetOs: html.dataset.targetOs || body?.dataset.targetOs || 'current',
      offlineRequired: (html.dataset.offlineRequired || body?.dataset.offlineRequired || 'false') === 'true'
    };
  });

  const aspect = parseAspect(raw.aspect || '16:9');
  let width = boundedInteger(raw.width, 1920);
  let height = boundedInteger(raw.height, 0);
  if (!height) height = Math.max(320, Math.round(width / aspect.ratio));
  if (!raw.width && raw.height) width = Math.max(320, Math.round(height * aspect.ratio));
  return { ...raw, aspect: aspect.label, ratio: aspect.ratio, width, height };
}

export function attachPageDiagnostics(page) {
  const diagnostics = { console: [], pageErrors: [], requestFailures: [], httpErrors: [] };
  page.on('console', message => {
    diagnostics.console.push({ type: message.type(), text: message.text(), location: message.location() });
  });
  page.on('pageerror', error => {
    diagnostics.pageErrors.push({ message: error.message, stack: error.stack || '' });
  });
  page.on('requestfailed', request => {
    diagnostics.requestFailures.push({ url: request.url(), error: request.failure()?.errorText || 'request failed' });
  });
  page.on('response', response => {
    if (response.status() >= 400) diagnostics.httpErrors.push({ url: response.url(), status: response.status() });
  });
  return diagnostics;
}

export async function waitForDeck(page, options = {}) {
  const timeout = options.timeout ?? 20_000;
  await page.waitForFunction(
    () => window.__DECK_READY === true || Boolean(window.__DECK_ERROR),
    null,
    { timeout }
  );
  const runtimeError = await page.evaluate(() => window.__DECK_ERROR || null);
  if (runtimeError) throw new BrowserRuntimeError(`Deck runtime failed: ${runtimeError}`);

  const assets = await page.evaluate(async timeoutMs => {
    const timeout = ms => new Promise(resolve => setTimeout(() => resolve('timeout'), ms));
    const fonts = document.fonts?.ready
      ? await Promise.race([document.fonts.ready.then(() => 'ready'), timeout(timeoutMs)])
      : 'unsupported';
    const images = await Promise.all([...document.images].map(async image => {
      if (!image.complete) {
        await Promise.race([
          new Promise(resolve => {
            image.addEventListener('load', resolve, { once: true });
            image.addEventListener('error', resolve, { once: true });
          }),
          timeout(timeoutMs)
        ]);
      }
      try { await image.decode?.(); } catch (_) { /* broken image is reported below */ }
      return { src: image.currentSrc || image.src, ok: image.complete && image.naturalWidth > 0 };
    }));
    window.__setLowPowerMode?.(true, { persist: false });
    document.body.classList.add('low-power');
    document.querySelectorAll('[data-anim]').forEach(element => {
      element.style.opacity = '1';
      element.style.transform = 'none';
    });
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return { fonts, images };
  }, Math.min(timeout, 10_000));
  return assets;
}

export async function installCaptureStyle(page, dimensions) {
  await page.addStyleTag({ content: `
    :root { --deck-export-width: ${dimensions.width}px; --deck-export-height: ${dimensions.height}px; }
    #ctrl-bar, #hint, #nav, #overview, [data-runtime-ui] { display: none !important; }
    html, body { margin: 0 !important; }
    body { overflow: hidden !important; }
  ` });
}

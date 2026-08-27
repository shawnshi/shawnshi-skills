#!/usr/bin/env node
import { existsSync } from 'node:fs';
import { createHash, randomUUID } from 'node:crypto';
import { lstat, mkdir, readFile, realpath, rename, unlink, writeFile } from 'node:fs/promises';
import { basename, dirname, extname, isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { assertDeliverySnapshotStable, assertTargetOs, attachPageDiagnostics, captureDeliverySnapshot, installNetworkPolicy, launchChromium, readDeckConfig, readDeckExecutionConfig, resolveNetworkAccess, waitForDeck } from './lib/browser-runtime.mjs';
import { createStaticServer } from './lib/static-server.mjs';

export function countPdfPages(buffer) {
  const source = buffer.toString('latin1');
  const direct = source.match(/\/Type\s*\/Page\b/g)?.length || 0;
  if (direct) return direct;
  const counts = [...source.matchAll(/\/Count\s+(\d+)/g)].map(match => Number(match[1])).filter(Number.isFinite);
  return counts.length ? Math.max(...counts) : 0;
}

export function validatePdfBuffer(buffer, expectedPages) {
  const pageCount = countPdfPages(buffer);
  if (!pageCount) throw new Error('PDF was created, but its page count could not be verified.');
  if (pageCount !== expectedPages) throw new Error(`PDF page count mismatch: expected ${expectedPages}, got ${pageCount}.`);
  return pageCount;
}

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function pathInside(root, candidate) {
  const relation = relative(root, candidate);
  return relation === '' || (!relation.startsWith('..') && !isAbsolute(relation));
}

function portablePath(root, candidate) {
  return relative(root, candidate).split('\\').join('/');
}

async function nearestExistingAncestor(candidate) {
  let current = candidate;
  while (!existsSync(current)) {
    const parent = dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return current;
}

async function ensureSafeOutputPath(deckRoot, candidate, label) {
  const root = resolve(deckRoot);
  const target = resolve(candidate);
  const rootReal = await realpath(root);
  if (!pathInside(root, target) || target === root) throw new Error(`${label} must stay inside the delivery root.`);
  const parent = dirname(target);
  const ancestorReal = await realpath(await nearestExistingAncestor(parent));
  if (!pathInside(rootReal, ancestorReal)) throw new Error(`${label} parent escapes the delivery root through a symlink.`);
  await mkdir(parent, { recursive: true });
  const parentReal = await realpath(parent);
  if (!pathInside(rootReal, parentReal)) throw new Error(`${label} parent escapes the delivery root through a symlink.`);
  if (existsSync(target)) {
    const info = await lstat(target);
    if (info.isSymbolicLink() || !info.isFile()) throw new Error(`${label} must not be a symlink or non-file target.`);
    const targetReal = await realpath(target);
    if (!pathInside(rootReal, targetReal)) throw new Error(`${label} escapes the delivery root.`);
  }
  return target;
}

export function buildPdfReport(options) {
  return {
    schemaVersion: '1.0.0',
    kind: 'pdf-export',
    ok: true,
    inputFile: options.inputFile,
    inputSha256: options.inputSha256,
    manifestFile: options.manifestFile,
    manifestSha256: options.manifestSha256,
    deliverySnapshot: options.deliverySnapshot,
    pdfFile: options.pdfFile,
    pdfSha256: options.pdfSha256,
    pageCount: options.pageCount,
    expectedPageCount: options.expectedPageCount,
    deliveryProfile: options.deliveryProfile,
    requiredGate: options.requiredGate,
    executionTarget: options.executionTarget,
    networkPolicy: options.networkPolicy,
    startedAt: options.startedAt,
    completedAt: options.completedAt
  };
}

function printCss({ width, height }) {
  return `@page{size:${width}px ${height}px!important;margin:0!important}@media print{
    html,body{width:${width}px!important;height:auto!important;margin:0!important;padding:0!important;overflow:visible!important}
    body{display:block!important}#ctrl-bar,#hint,#nav,#overview,[data-runtime-ui]{display:none!important}
    #deck{position:static!important;display:block!important;width:${width}px!important;height:auto!important;transform:none!important;transition:none!important}
    #deck>.slide,#deck .slide{position:relative!important;left:auto!important;top:auto!important;width:${width}px!important;height:${height}px!important;min-width:${width}px!important;min-height:${height}px!important;max-width:${width}px!important;max-height:${height}px!important;margin:0!important;box-sizing:border-box!important;overflow:hidden!important;break-after:page!important;break-inside:avoid!important;page-break-after:always!important;page-break-inside:avoid!important;opacity:1!important;transform:none!important}
    #deck>.slide:last-child{break-after:auto!important;page-break-after:auto!important}[data-anim]{opacity:1!important;transform:none!important}}`;
}

export async function exportPdf(options = {}) {
  if (!options.htmlPath) throw new Error('HTML input is required.');
  const htmlPath = resolve(options.htmlPath);
  const deckRoot = dirname(htmlPath);
  const outputPath = resolve(options.outputPath || join(deckRoot, 'deck.pdf'));
  if (outputPath === htmlPath) throw new Error('PDF output path must differ from the HTML input path.');
  if (extname(outputPath).toLowerCase() !== '.pdf') throw new Error('PDF output path must use the .pdf extension.');
  if (!existsSync(htmlPath)) throw new Error(`File not found: ${htmlPath}`);
  const reportPath = resolve(options.reportPath || join(dirname(htmlPath), 'qa-report', 'pdf.json'));
  if (reportPath === htmlPath || reportPath === outputPath) throw new Error('PDF report path must differ from the HTML input and PDF output paths.');
  if (extname(reportPath).toLowerCase() !== '.json') throw new Error('PDF report path must use the .json extension.');
  await ensureSafeOutputPath(deckRoot, outputPath, 'PDF output path');
  await ensureSafeOutputPath(deckRoot, reportPath, 'PDF report path');
  await unlink(reportPath).catch(error => { if (error.code !== 'ENOENT') throw error; });
  const deliverySnapshot = await captureDeliverySnapshot(htmlPath);
  const declared = await readDeckExecutionConfig(htmlPath);
  await assertDeliverySnapshotStable(deliverySnapshot);
  const executionTarget = { targetBrowser: declared.targetBrowser, ...assertTargetOs(declared.targetOs) };
  const networkAccess = resolveNetworkAccess({
    allowNetwork: options.allowNetwork === true,
    offlineRequired: declared.offlineRequired,
    deliveryProfile: declared.deliveryProfile
  });
  const temporaryPath = join(dirname(outputPath), `.${basename(outputPath)}.${process.pid}.${randomUUID()}.tmp.pdf`);
  const temporaryReportPath = join(dirname(reportPath), `.${basename(reportPath)}.${process.pid}.${randomUUID()}.tmp`);
  const startedAt = new Date().toISOString();
  let server, browser, page;
  try {
    server = await createStaticServer({ root: dirname(htmlPath) });
    const launched = await launchChromium({ targetBrowser: declared.targetBrowser });
    browser = launched.browser;
    executionTarget.actualBrowser = launched.executable.browser;
    executionTarget.browserSource = launched.executable.source;
    executionTarget.browserExecutable = launched.executable.path;
    page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1, serviceWorkers: 'block' });
    const diagnostics = attachPageDiagnostics(page);
    const networkPolicy = await installNetworkPolicy(page, {
      allowedOrigin: server.baseUrl,
      allowNetwork: networkAccess.allowNetwork
    });
    networkPolicy.gate = networkAccess;
    await page.goto(server.urlFor(htmlPath), { waitUntil: 'domcontentloaded', timeout: options.timeout || 30_000 });
    await page.waitForLoadState('networkidle', { timeout: 8_000 }).catch(() => {});
    const assets = await waitForDeck(page, { timeout: options.timeout || 20_000 });
    if (assets.fonts === 'timeout') throw new Error('Cannot export: document.fonts.ready timed out.');
    const brokenImages = assets.images.filter(image => !image.ok);
    if (brokenImages.length) throw new Error(`Cannot export: ${brokenImages.length} image(s) failed to load.`);
    const config = await readDeckConfig(page);
    config.deliveryProfile = declared.deliveryProfile;
    config.targetBrowser = declared.targetBrowser;
    config.targetOs = declared.targetOs;
    config.offlineRequired = config.offlineRequired || declared.offlineRequired;
    if (!config.slideCount) throw new Error('Cannot export a deck with zero slides.');
    await page.setViewportSize({ width: config.width, height: config.height });
    await page.evaluate(() => {
      window.setMode?.('pres');
      document.body.classList.remove('doc-mode');
      document.body.classList.add('pres-mode', 'low-power');
    });
    await page.addStyleTag({ content: printCss(config) });
    await page.emulateMedia({ media: 'print' });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const consoleErrors = diagnostics.console.filter(item => item.type === 'error');
    if (diagnostics.pageErrors.length || diagnostics.requestFailures.length || diagnostics.httpErrors.length || consoleErrors.length || networkPolicy.blockedRequests.length || networkPolicy.blockedWebSockets.length) {
      throw new Error(`Cannot export a deck with runtime errors: ${diagnostics.pageErrors.length} page, ${consoleErrors.length} console, ${diagnostics.requestFailures.length} request, ${diagnostics.httpErrors.length} HTTP, ${networkPolicy.blockedRequests.length} policy-blocked request, ${networkPolicy.blockedWebSockets.length} policy-blocked WebSocket.`);
    }
    await page.pdf({ path: temporaryPath, printBackground: true, preferCSSPageSize: true,
      width: `${config.width}px`, height: `${config.height}px`, margin: { top: '0', right: '0', bottom: '0', left: '0' },
      timeout: options.timeout || 60_000 });
    const pdfBuffer = await readFile(temporaryPath);
    const pageCount = validatePdfBuffer(pdfBuffer, config.slideCount);
    await assertDeliverySnapshotStable(deliverySnapshot);
    const { browserExecutable: _browserExecutable, ...receiptExecutionTarget } = executionTarget;
    const { htmlPath: _snapshotHtmlPath, ...receiptDeliverySnapshot } = deliverySnapshot;
    const report = buildPdfReport({
      inputFile: deliverySnapshot.inputFile,
      inputSha256: deliverySnapshot.inputSha256,
      manifestFile: deliverySnapshot.manifestFile,
      manifestSha256: deliverySnapshot.manifestSha256,
      deliverySnapshot: receiptDeliverySnapshot,
      pdfFile: portablePath(deckRoot, outputPath),
      pdfSha256: sha256(pdfBuffer),
      pageCount,
      expectedPageCount: config.slideCount,
      deliveryProfile: declared.deliveryProfile,
      requiredGate: declared.requiredGates?.pdf || null,
      executionTarget: receiptExecutionTarget,
      networkPolicy,
      startedAt,
      completedAt: new Date().toISOString()
    });
    await writeFile(temporaryReportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
    await rename(temporaryPath, outputPath);
    await rename(temporaryReportPath, reportPath);
    return { ...report, reportPath, outputPath, config, diagnostics };
  } finally {
    await page?.close().catch(() => {});
    await browser?.close().catch(() => {});
    await server?.close().catch(() => {});
    await unlink(temporaryPath).catch(error => { if (error.code !== 'ENOENT') console.warn(`Could not remove temporary PDF: ${error.message}`); });
    await unlink(temporaryReportPath).catch(error => { if (error.code !== 'ENOENT') console.warn(`Could not remove temporary PDF report: ${error.message}`); });
  }
}

const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  if (process.argv.includes('--help') || process.argv.includes('-h')) {
    console.log('Usage: node scripts/export-pdf.mjs [--allow-network] [--report=<path>] <index.html> [output.pdf]');
    process.exit(0);
  }
  try {
    const raw = process.argv.slice(2);
    let allowNetwork = false;
    let reportPath;
    const positional = [];
    for (let index = 0; index < raw.length; index += 1) {
      const argument = raw[index];
      if (argument === '--allow-network') allowNetwork = true;
      else if (argument.startsWith('--report=')) reportPath = argument.slice('--report='.length);
      else if (argument === '--report') {
        reportPath = raw[index + 1];
        if (!reportPath) throw new Error('--report requires a path.');
        index += 1;
      } else if (argument.startsWith('-')) throw new Error(`Unknown option: ${argument}`);
      else positional.push(argument);
    }
    console.log(`Network policy: ${allowNetwork ? 'allow-network (explicit opt-in)' : 'isolated (static-server origin only)'}`);
    const result = await exportPdf({ htmlPath: positional[0], outputPath: positional[1], reportPath, allowNetwork });
    console.log(`PDF exported: ${result.outputPath} (${result.pageCount} pages, ${result.config.aspect})`);
    console.log(`Delivery profile: ${result.deliveryProfile || 'unspecified'}`);
    console.log(`Execution target: ${result.executionTarget.targetBrowser} on ${result.executionTarget.resolvedTargetOs} (actual ${result.executionTarget.actualBrowser} on ${result.executionTarget.actualOs})`);
    console.log(`Report: ${result.reportPath}`);
  } catch (error) {
    console.error(`PDF export failed: ${error.message}`);
    process.exitCode = 1;
  }
}

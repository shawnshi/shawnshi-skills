#!/usr/bin/env node
import { createHash, randomUUID } from 'node:crypto';
import { existsSync } from 'node:fs';
import { lstat, mkdir, readFile, realpath, rename, unlink, writeFile } from 'node:fs/promises';
import { basename, dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  assertTargetOs,
  assertDeliverySnapshotStable,
  attachPageDiagnostics,
  captureDeliverySnapshot,
  installCaptureStyle,
  installNetworkPolicy,
  launchChromium,
  readDeckExecutionConfig,
  readDeckConfig,
  resolveNetworkAccess,
  waitForDeck
} from './lib/browser-runtime.mjs';
import { createStaticServer } from './lib/static-server.mjs';

function pageName(index) {
  return `slide-${String(index + 1).padStart(3, '0')}.png`;
}

function pathInside(root, candidate) {
  const relation = relative(root, candidate);
  return relation === '' || (!relation.startsWith('..') && !isAbsolute(relation));
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

async function prepareOutputDirectory(deckRoot, outputDir) {
  const root = resolve(deckRoot);
  const directory = resolve(outputDir);
  const rootReal = await realpath(root);
  if (!pathInside(root, directory) || directory === root) {
    throw new Error('Visual QA output directory must be a dedicated directory inside the delivery root.');
  }
  const ancestorReal = await realpath(await nearestExistingAncestor(directory));
  if (!pathInside(rootReal, ancestorReal)) throw new Error('Visual QA output directory escapes the delivery root through a symlink.');
  await mkdir(directory, { recursive: true });
  const info = await lstat(directory);
  if (info.isSymbolicLink() || !info.isDirectory()) throw new Error('Visual QA output directory must not be a symlink or non-directory.');
  const directoryReal = await realpath(directory);
  if (!pathInside(rootReal, directoryReal)) throw new Error('Visual QA output directory escapes the delivery root.');
  return { directory, directoryReal };
}

async function assertSafeOutputFile(outputDir, outputDirReal, filePath, label) {
  const target = resolve(filePath);
  if (!pathInside(outputDir, target)) throw new Error(`${label} escapes the visual QA output directory.`);
  if (!existsSync(target)) return;
  const info = await lstat(target);
  if (info.isSymbolicLink() || !info.isFile()) throw new Error(`${label} must not be a symlink or non-file target.`);
  if (!pathInside(outputDirReal, await realpath(target))) throw new Error(`${label} escapes the visual QA output directory.`);
}

async function trustedPreviousScreenshots(reportPath, outputDir, outputDirReal) {
  if (!existsSync(reportPath)) return [];
  await assertSafeOutputFile(outputDir, outputDirReal, reportPath, 'Visual QA report path');
  let report;
  try { report = JSON.parse(await readFile(reportPath, 'utf8')); }
  catch (_) { return []; }
  if (report?.kind !== 'visual-qa' || !Array.isArray(report.slides)) return [];
  const trusted = [];
  for (const slide of report.slides) {
    const screenshot = slide?.screenshot;
    if (!screenshot || typeof screenshot.file !== 'string' || !/^slide-\d{3,}\.png$/.test(screenshot.file)
        || !Number.isInteger(screenshot.bytes) || !/^[a-f0-9]{64}$/.test(screenshot.sha256 || '')) continue;
    const screenshotPath = resolve(outputDir, screenshot.file);
    await assertSafeOutputFile(outputDir, outputDirReal, screenshotPath, `Previous screenshot ${screenshot.file}`);
    if (!existsSync(screenshotPath)) continue;
    const bytes = await readFile(screenshotPath);
    if (bytes.length === screenshot.bytes && createHash('sha256').update(bytes).digest('hex') === screenshot.sha256) {
      trusted.push(screenshotPath);
    }
  }
  return trusted;
}

async function writeJsonAtomic(filePath, value) {
  const temporaryPath = join(dirname(filePath), `.${basename(filePath)}.${randomUUID()}.tmp`);
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  try {
    await rename(temporaryPath, filePath);
  } finally {
    await unlink(temporaryPath).catch(error => { if (error.code !== 'ENOENT') throw error; });
  }
}

function normalizedSlides(slides) {
  return slides.map((slide, offset) => ({
    index: Number.isInteger(slide?.index) ? slide.index : offset + 1,
    id: String(slide?.id || `slide-${offset + 1}`),
    layout: String(slide?.layout || 'unclassified')
  }));
}

export function selectVisualCoverage(slides, requestedMode = 'all') {
  const normalized = normalizedSlides(slides);
  const mode = ['sample', 'layouts', 'all'].includes(requestedMode) ? requestedMode : 'all';
  const selectedOffsets = new Set();
  if (mode === 'all' || normalized.length <= 3) {
    normalized.forEach((_, offset) => selectedOffsets.add(offset));
  } else if (mode === 'sample') {
    selectedOffsets.add(0);
    selectedOffsets.add(Math.floor((normalized.length - 1) / 2));
    selectedOffsets.add(normalized.length - 1);
  } else {
    normalized.forEach((slide, offset) => {
      if (!normalized.slice(0, offset).some(candidate => candidate.layout === slide.layout)) selectedOffsets.add(offset);
    });
    selectedOffsets.add(0);
    selectedOffsets.add(normalized.length - 1);
  }
  const selectedSlides = [...selectedOffsets].sort((a, b) => a - b).map(offset => normalized[offset]);
  const uniqueLayouts = [...new Set(normalized.map(slide => slide.layout))];
  const coveredLayouts = [...new Set(selectedSlides.map(slide => slide.layout))];
  const layoutCoverage = uniqueLayouts.map(layout => ({
    layout,
    total: normalized.filter(slide => slide.layout === layout).length,
    selected: selectedSlides.filter(slide => slide.layout === layout).length
  }));
  return {
    mode,
    totalSlides: normalized.length,
    selectedCount: selectedSlides.length,
    selectedSlideIndices: selectedSlides.map(slide => slide.index),
    selectedSlideIds: selectedSlides.map(slide => slide.id),
    selectedSlides,
    uniqueLayouts,
    coveredLayouts,
    uniqueLayoutCount: uniqueLayouts.length,
    coveredLayoutCount: coveredLayouts.length,
    layoutCoverage
  };
}

async function readSlideMetadata(page) {
  return page.evaluate(() => [...document.querySelectorAll('#deck .slide')].map((slide, offset) => ({
    index: offset + 1,
    id: slide.dataset.slideId || slide.id || `slide-${offset + 1}`,
    layout: slide.dataset.layout || 'unclassified'
  })));
}

async function inspectOverflow(page, index) {
  return page.evaluate(async slideIndex => {
    window.go?.(slideIndex, { force: true, broadcast: false });
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const slides = [...document.querySelectorAll('#deck .slide')];
    const slide = slides[slideIndex];
    if (!slide) return { slide: slideIndex + 1, missing: true, overflow: [] };
    const frame = slide.getBoundingClientRect();
    const findings = [];
    const selector = element => {
      if (element.id) return `#${element.id}`;
      const classes = [...element.classList].slice(0, 3).join('.');
      return `${element.tagName.toLowerCase()}${classes ? `.${classes}` : ''}`;
    };
    const candidates = [slide, ...slide.querySelectorAll('*')];
    for (const element of candidates) {
      if (findings.length >= 30) break;
      if (element.closest('aside.notes') || element.matches('script,style,template')) continue;
      const style = getComputedStyle(element);
      if (style.display === 'none' || style.visibility === 'hidden') continue;
      const rect = element.getBoundingClientRect();
      if (rect.width < 1 || rect.height < 1) continue;
      const hasContent = element === slide
        || /^(IMG|SVG|CANVAS|VIDEO|TABLE)$/.test(element.tagName)
        || [...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
      if (!hasContent) continue;
      const internalX = element.scrollWidth > element.clientWidth + 2 && !['hidden','clip'].includes(style.overflowX);
      const internalY = element.scrollHeight > element.clientHeight + 2 && !['hidden','clip'].includes(style.overflowY);
      const outside = rect.left < frame.left - 2 || rect.top < frame.top - 2 || rect.right > frame.right + 2 || rect.bottom > frame.bottom + 2;
      if (internalX || internalY || outside) {
        findings.push({
          selector: selector(element),
          internalX, internalY, outside,
          rect: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
          scroll: { width: element.scrollWidth, height: element.scrollHeight }
        });
      }
    }
    return { slide: slideIndex + 1, missing: false, overflow: findings };
  }, index);
}

export async function runVisualQa(options = {}) {
  const htmlPath = resolve(options.htmlPath || '');
  if (!options.htmlPath) throw new Error('HTML input is required.');
  if (!existsSync(htmlPath)) throw new Error(`File not found: ${htmlPath}`);
  const deliverySnapshot = await captureDeliverySnapshot(htmlPath);
  const declared = await readDeckExecutionConfig(htmlPath);
  await assertDeliverySnapshotStable(deliverySnapshot);
  const executionTarget = { targetBrowser: declared.targetBrowser, ...assertTargetOs(declared.targetOs) };
  const networkAccess = resolveNetworkAccess({
    allowNetwork: options.allowNetwork === true,
    offlineRequired: declared.offlineRequired,
    deliveryProfile: declared.deliveryProfile
  });
  const deckRoot = dirname(htmlPath);
  const preparedOutput = await prepareOutputDirectory(deckRoot, options.outputDir || join(deckRoot, 'qa-report'));
  const outputDir = preparedOutput.directory;
  const reportPath = join(outputDir, 'report.json');
  await assertSafeOutputFile(outputDir, preparedOutput.directoryReal, reportPath, 'Visual QA report path');
  const previousScreenshots = await trustedPreviousScreenshots(reportPath, outputDir, preparedOutput.directoryReal);
  await unlink(reportPath).catch(error => { if (error.code !== 'ENOENT') throw error; });

  let server;
  let browser;
  let page;
  const startedAt = new Date().toISOString();
  try {
    server = await createStaticServer({ root: dirname(htmlPath) });
    const launched = await launchChromium({ targetBrowser: declared.targetBrowser });
    browser = launched.browser;
    executionTarget.actualBrowser = launched.executable.browser;
    executionTarget.browserSource = launched.executable.source;
    executionTarget.browserExecutable = launched.executable.path;
    page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1, serviceWorkers: 'block' });
    const diagnostics = attachPageDiagnostics(page);
    const url = server.urlFor(htmlPath);
    const networkPolicy = await installNetworkPolicy(page, {
      allowedOrigin: server.baseUrl,
      allowNetwork: networkAccess.allowNetwork
    });
    networkPolicy.gate = networkAccess;
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: options.timeout || 30_000 });
    const assetReadiness = await waitForDeck(page, { timeout: options.timeout || 20_000 });
    const config = await readDeckConfig(page);
    config.deliveryProfile = declared.deliveryProfile;
    config.targetBrowser = declared.targetBrowser;
    config.targetOs = declared.targetOs;
    config.offlineRequired = config.offlineRequired || declared.offlineRequired;
    await page.setViewportSize({ width: config.width, height: config.height });
    await installCaptureStyle(page, config);
    await page.evaluate(() => window.setMode?.('pres'));

    const slideMetadata = await readSlideMetadata(page);
    const coverage = selectVisualCoverage(
      slideMetadata,
      declared.requiredGates?.visual || options.coverageMode || 'all'
    );

    const brokenImages = assetReadiness.images.filter(image => !image.ok).map(image => image.src);
    for (const screenshotPath of previousScreenshots) await unlink(screenshotPath);
    const slides = [];
    for (const selected of coverage.selectedSlides) {
      const index = selected.index - 1;
      const inspection = await inspectOverflow(page, index);
      const screenshotFile = pageName(index);
      const screenshotPath = join(outputDir, screenshotFile);
      await assertSafeOutputFile(outputDir, preparedOutput.directoryReal, screenshotPath, `Screenshot ${screenshotFile}`);
      await page.screenshot({ path: screenshotPath, animations: 'disabled' });
      const screenshotBytes = await readFile(screenshotPath);
      slides.push({
        ...selected,
        ...inspection,
        screenshot: {
          file: screenshotFile,
          bytes: screenshotBytes.length,
          sha256: createHash('sha256').update(screenshotBytes).digest('hex')
        }
      });
    }

    const failures = {
      consoleErrors: diagnostics.console.filter(item => item.type === 'error'),
      pageErrors: diagnostics.pageErrors,
      requestFailures: diagnostics.requestFailures,
      httpErrors: diagnostics.httpErrors,
      blockedRequests: networkPolicy.blockedRequests,
      blockedWebSockets: networkPolicy.blockedWebSockets,
      fontTimeouts: assetReadiness.fonts === 'timeout' ? [{ message: 'document.fonts.ready timed out' }] : [],
      brokenImages,
      overflowSlides: slides.filter(slide => slide.missing || slide.overflow.length)
    };
    const ok = Object.values(failures).every(items => items.length === 0);
    await assertDeliverySnapshotStable(deliverySnapshot);
    const inputSha256 = deliverySnapshot.inputSha256;
    const manifestSha256 = deliverySnapshot.manifestSha256;
    const { htmlPath: _snapshotHtmlPath, ...receiptDeliverySnapshot } = deliverySnapshot;
    const { browserExecutable: _browserExecutable, ...receiptExecutionTarget } = executionTarget;
    const report = {
      schemaVersion: '1.0.0',
      kind: 'visual-qa',
      ok,
      input: htmlPath,
      inputSha256,
      manifestPath: declared.manifestPath,
      manifestSha256,
      deliverySnapshot: receiptDeliverySnapshot,
      url,
      startedAt,
      completedAt: new Date().toISOString(),
      config,
      deliveryProfile: declared.deliveryProfile,
      requiredGate: declared.requiredGates?.visual || null,
      executionTarget: receiptExecutionTarget,
      networkPolicy,
      coverage,
      slides,
      assetReadiness,
      diagnostics,
      failures
    };
    await writeJsonAtomic(reportPath, report);
    return { ...report, reportPath, outputDir };
  } finally {
    await page?.close().catch(() => {});
    await browser?.close().catch(() => {});
    await server?.close().catch(() => {});
  }
}

const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  if (process.argv.includes('--help') || process.argv.includes('-h')) {
    console.log('Usage: node scripts/visual-qa.mjs [--allow-network] <index.html> [qa-output-dir]');
    process.exit(0);
  }
  try {
    const raw = process.argv.slice(2);
    const allowNetwork = raw.includes('--allow-network');
    const unknown = raw.filter(arg => arg.startsWith('-') && arg !== '--allow-network');
    if(unknown.length) throw new Error(`Unknown option: ${unknown[0]}`);
    const positional = raw.filter(arg => !arg.startsWith('-'));
    console.log(`Network policy: ${allowNetwork ? 'allow-network (explicit opt-in)' : 'isolated (static-server origin only)'}`);
    const result = await runVisualQa({ htmlPath: positional[0], outputDir: positional[1], allowNetwork });
    console.log(`${result.ok ? 'PASS' : 'FAIL'} visual QA: ${result.coverage.selectedCount}/${result.config.slideCount} slides (${result.coverage.mode})`);
    console.log(`Delivery profile: ${result.deliveryProfile || 'unspecified'}`);
    console.log(`Execution target: ${result.executionTarget.targetBrowser} on ${result.executionTarget.resolvedTargetOs} (actual ${result.executionTarget.actualBrowser} on ${result.executionTarget.actualOs})`);
    console.log(`Report: ${result.reportPath}`);
    process.exitCode = result.ok ? 0 : 1;
  } catch (error) {
    console.error(`Visual QA failed: ${error.message}`);
    process.exitCode = 1;
  }
}

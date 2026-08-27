#!/usr/bin/env node
import { createHash, randomUUID } from 'node:crypto';
import { existsSync } from 'node:fs';
import { lstat, mkdir, readFile, readdir, realpath, rename, unlink, writeFile } from 'node:fs/promises';
import { dirname, extname, isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  parseDeliveryProfile,
  parseTargetBrowser,
  parseTargetOs,
  requiredGatesFor
} from './lib/delivery-contract.mjs';
import { assertDeliverySnapshotStable, captureDeliverySnapshot } from './lib/browser-runtime.mjs';
import { countPdfPages } from './export-pdf.mjs';

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function sameJson(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function requiredGate(value) {
  return value === true || ![false, null, undefined, 'optional', 'none'].includes(value);
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

async function ensureSafeDirectory(deckRoot, deckRootReal, candidate, label) {
  const directory = resolve(candidate);
  if (!pathInside(deckRoot, directory)) throw new Error(`${label} must stay inside the delivery root.`);
  const ancestorReal = await realpath(await nearestExistingAncestor(directory));
  if (!pathInside(deckRootReal, ancestorReal)) throw new Error(`${label} escapes the delivery root through a symlink.`);
  await mkdir(directory, { recursive: true });
  const info = await lstat(directory);
  if (info.isSymbolicLink() || !info.isDirectory()) throw new Error(`${label} must not be a symlink or non-directory.`);
  const actual = await realpath(directory);
  if (!pathInside(deckRootReal, actual)) throw new Error(`${label} escapes the delivery root.`);
  return actual;
}

async function ensureSafeWriteTarget(deckRoot, deckRootReal, candidate, label) {
  const target = resolve(candidate);
  if (!pathInside(deckRoot, target) || target === deckRoot) throw new Error(`${label} must stay inside the delivery root.`);
  await ensureSafeDirectory(deckRoot, deckRootReal, dirname(target), `${label} parent`);
  if (existsSync(target)) {
    const info = await lstat(target);
    if (info.isSymbolicLink() || !info.isFile()) throw new Error(`${label} must not be a symlink or non-file target.`);
    if (!pathInside(deckRootReal, await realpath(target))) throw new Error(`${label} escapes the delivery root.`);
  }
  return target;
}

async function safeRegularFile(deckRoot, deckRootReal, candidate, label, errors) {
  const target = resolve(candidate);
  if (!pathInside(deckRoot, target)) {
    errors.push(`${label} is outside the delivery root`);
    return false;
  }
  if (!existsSync(target)) return false;
  try {
    const info = await lstat(target);
    if (info.isSymbolicLink() || !info.isFile()) {
      errors.push(`${label} must be a regular file and not a symlink`);
      return false;
    }
    if (!pathInside(deckRootReal, await realpath(target))) {
      errors.push(`${label} escapes the delivery root`);
      return false;
    }
    return true;
  } catch (error) {
    errors.push(`${label} cannot be inspected safely: ${error.message}`);
    return false;
  }
}

function targetErrors(reportTarget, target) {
  const errors = [];
  if (!reportTarget || typeof reportTarget !== 'object') return ['execution target is missing'];
  if (reportTarget.targetBrowser !== target.browser) errors.push('target browser does not match the manifest');
  if (reportTarget.actualBrowser !== target.browser) errors.push('actual browser does not match the declared browser');
  if (reportTarget.targetOs !== target.os) errors.push('target OS does not match the manifest');
  if (target.os === 'current') {
    if (!reportTarget.actualOs || reportTarget.resolvedTargetOs !== reportTarget.actualOs) {
      errors.push('current target OS was not resolved to the recorded actual OS');
    }
  } else if (reportTarget.actualOs !== target.os || reportTarget.resolvedTargetOs !== target.os) {
    errors.push('actual OS does not match the declared target OS');
  }
  return errors;
}

function networkErrors(policy, manifest) {
  const errors = [];
  if (!policy || typeof policy !== 'object') return ['network policy is missing'];
  const gate = policy.gate || {};
  const allowNetwork = policy.allowNetwork === true || gate.allowNetwork === true;
  const locked = manifest.offlineRequired === true || manifest.deliveryProfile === 'high-assurance';
  if (gate.deliveryProfile !== manifest.deliveryProfile) errors.push('network gate profile does not match the manifest');
  if (gate.offlineRequired !== (manifest.offlineRequired === true)) errors.push('network gate offlineRequired does not match the manifest');
  if (locked && allowNetwork) errors.push('network access was enabled for an offline/high-assurance delivery');
  if (allowNetwork && policy.mode !== 'allow-network') errors.push('network policy mode does not record the network opt-in');
  if (!allowNetwork && policy.mode !== 'isolated') errors.push('isolated network policy was not recorded');
  if (!policy.allowedOrigin || !/^http:\/\/127\.0\.0\.1:\d+$/.test(policy.allowedOrigin)) {
    errors.push('static-server origin is missing or invalid');
  }
  if (Array.isArray(policy.blockedRequests) && policy.blockedRequests.length) errors.push('network policy recorded blocked requests');
  if (Array.isArray(policy.blockedWebSockets) && policy.blockedWebSockets.length) errors.push('network policy recorded blocked WebSockets');
  return errors;
}

function timeErrors(report) {
  const started = Date.parse(report?.startedAt);
  const completed = Date.parse(report?.completedAt);
  if (!Number.isFinite(started) || !Number.isFinite(completed)) return ['execution timestamps are missing or invalid'];
  return completed >= started ? [] : ['execution completion time precedes its start time'];
}

async function readJsonReport(filePath, label, errors, deckRoot, deckRootReal, gate = null) {
  if (!existsSync(filePath)) return null;
  if (!await safeRegularFile(deckRoot, deckRootReal, filePath, label, errors)) return null;
  try {
    const bytes = await readFile(filePath);
    if (gate) gate.reportSha256 = sha256(bytes);
    return JSON.parse(bytes.toString('utf8'));
  }
  catch (error) {
    errors.push(`${label} is not valid JSON: ${error.message}`);
    return null;
  }
}

function reportHashes(report, inputSha256, manifestSha256, deliverySnapshot = null) {
  const errors = [];
  if (report?.inputSha256 !== inputSha256) errors.push('HTML hash is stale or missing');
  if (report?.manifestSha256 !== manifestSha256) errors.push('manifest hash is stale or missing');
  if (deliverySnapshot && !sameJson(report?.deliverySnapshot, deliverySnapshot)) {
    errors.push('delivery file snapshot is stale or missing');
  }
  return errors;
}

function reportIdentity(report, manifest, target) {
  const errors = [];
  if (report?.deliveryProfile !== manifest.deliveryProfile) errors.push('delivery profile does not match the manifest');
  errors.push(...targetErrors(report?.executionTarget, target));
  errors.push(...networkErrors(report?.networkPolicy, manifest));
  errors.push(...timeErrors(report));
  return errors;
}

function makeGate(expected, reportPath, deckRoot) {
  const safePath = pathInside(deckRoot, reportPath);
  return {
    expected,
    required: requiredGate(expected),
    present: existsSync(reportPath),
    reportFile: portablePath(deckRoot, reportPath),
    reportSha256: null,
    ok: false,
    errors: safePath ? [] : ['report path is outside the delivery root']
  };
}

function validateStaticReport(report, context) {
  const errors = reportHashes(report, context.inputSha256, context.manifestSha256, context.deliverySnapshot);
  if (report?.valid !== true) errors.push('static QA report is not valid');
  if (report?.configuration?.deliveryProfile !== context.manifest.deliveryProfile) errors.push('delivery profile does not match the manifest');
  if (!sameJson(report?.configuration?.requiredGates, context.requiredGates)) errors.push('required gates do not match the delivery profile');
  const target = report?.configuration?.target;
  if (!target || target.browser !== context.target.browser || target.os !== context.target.os
      || !sameJson(target.viewport, context.target.viewport)) {
    errors.push('static target does not match the manifest');
  }
  if (!sameJson(report?.slideIds, context.slideIds)) errors.push('static slide IDs do not match the manifest');
  if (!Array.isArray(report?.layouts) || report.layouts.length !== context.slideIds.length) errors.push('static layout list is missing or incomplete');
  if (report?.summary?.slides !== context.slideIds.length) errors.push('static slide count does not match the manifest');
  return errors;
}

function representativeIndices(total) {
  if (total <= 3) return Array.from({ length: total }, (_, index) => index + 1);
  return [1, Math.floor((total - 1) / 2) + 1, total];
}

function validateCoverage(report, expected, slideIds, layouts) {
  const errors = [];
  const coverage = report?.coverage;
  if (!coverage || typeof coverage !== 'object') return ['visual coverage record is missing'];
  const total = slideIds.length;
  const indices = coverage.selectedSlideIndices;
  const ids = coverage.selectedSlideIds;
  if (coverage.totalSlides !== total) errors.push('visual total slide count does not match the manifest');
  if (!Array.isArray(indices) || !Array.isArray(ids) || indices.length !== ids.length || !indices.length) {
    return [...errors, 'selected slide indices/IDs are missing or inconsistent'];
  }
  if (new Set(indices).size !== indices.length) errors.push('selected slide indices contain duplicates');
  if (coverage.selectedCount !== indices.length) errors.push('selected slide count does not match its index list');
  const coverageRank = { sample: 1, layouts: 2, all: 3 };
  if (!coverageRank[coverage.mode] || coverageRank[coverage.mode] < coverageRank[expected]) {
    errors.push(`coverage mode ${coverage.mode || '(missing)'} is weaker than ${expected}`);
  }
  for (let offset = 0; offset < indices.length; offset += 1) {
    const index = indices[offset];
    if (!Number.isInteger(index) || index < 1 || index > total) errors.push(`selected slide index ${index} is out of range`);
    else if (ids[offset] !== slideIds[index - 1]) errors.push(`selected slide ID at index ${index} does not match the manifest`);
  }
  const selected = new Set(indices);
  if (expected === 'sample') {
    for (const index of representativeIndices(total)) if (!selected.has(index)) errors.push(`representative slide ${index} is missing`);
  } else if (expected === 'layouts') {
    if (!selected.has(1)) errors.push('first slide is missing from layout coverage');
    if (!selected.has(total)) errors.push('last slide is missing from layout coverage');
    if (!Array.isArray(layouts) || layouts.length !== total) errors.push('trusted layout metadata is unavailable');
    else {
      for (const layout of new Set(layouts)) {
        if (!indices.some(index => layouts[index - 1] === layout)) errors.push(`layout ${layout} is not covered`);
      }
    }
  } else if (expected === 'all') {
    for (let index = 1; index <= total; index += 1) if (!selected.has(index)) errors.push(`slide ${index} is missing from full coverage`);
  } else {
    errors.push(`unsupported visual gate: ${expected}`);
  }
  if (Array.isArray(layouts) && layouts.length === total) {
    const uniqueLayouts = [...new Set(layouts)];
    const coveredLayouts = [...new Set(indices.filter(index => index >= 1 && index <= total).map(index => layouts[index - 1]))];
    if (!sameJson(coverage.uniqueLayouts, uniqueLayouts)) errors.push('reported unique layouts do not match static QA metadata');
    if (!sameJson(coverage.coveredLayouts, coveredLayouts)) errors.push('reported covered layouts do not match selected slides');
    if (!Array.isArray(coverage.layoutCoverage) || coverage.layoutCoverage.length !== uniqueLayouts.length) {
      errors.push('per-layout coverage counts are missing');
    } else {
      for (const layout of uniqueLayouts) {
        const row = coverage.layoutCoverage.find(candidate => candidate?.layout === layout);
        const totalForLayout = layouts.filter(candidate => candidate === layout).length;
        const selectedForLayout = indices.filter(index => layouts[index - 1] === layout).length;
        if (!row || row.total !== totalForLayout || row.selected !== selectedForLayout) {
          errors.push(`per-layout coverage is incorrect for ${layout}`);
        }
      }
    }
  }
  return errors;
}

async function validateVisualReport(report, context, reportDir, reportDirReal, deckRoot, deckRootReal) {
  const errors = [
    ...reportHashes(report, context.inputSha256, context.manifestSha256, context.deliverySnapshot),
    ...reportIdentity(report, context.manifest, context.target)
  ];
  if (report?.ok !== true) errors.push('visual QA report is not successful');
  if (report?.requiredGate !== context.requiredGates.visual) errors.push('visual required gate does not match the manifest');
  errors.push(...validateCoverage(report, context.requiredGates.visual, context.slideIds, context.layouts));

  const screenshots = Array.isArray(report?.slides) ? report.slides.map(slide => slide?.screenshot) : [];
  const expectedNames = new Set();
  if (screenshots.length !== report?.coverage?.selectedCount) errors.push('screenshot count does not match selected coverage');
  for (const [offset, screenshot] of screenshots.entries()) {
    const slideReceipt = report.slides[offset];
    if (slideReceipt?.index !== report?.coverage?.selectedSlideIndices?.[offset]
        || slideReceipt?.id !== report?.coverage?.selectedSlideIds?.[offset]) {
      errors.push('screenshot slide identity does not match selected coverage');
    }
    if (!screenshot || typeof screenshot !== 'object' || !/^slide-\d{3,}\.png$/.test(screenshot.file || '')
        || !Number.isInteger(screenshot.bytes) || !/^[a-f0-9]{64}$/.test(screenshot.sha256 || '')) {
      errors.push('visual report contains incomplete screenshot integrity metadata');
      continue;
    }
    const screenshotPath = resolve(reportDir, screenshot.file);
    if (!pathInside(reportDir, screenshotPath)
        || !await safeRegularFile(deckRoot, deckRootReal, screenshotPath, `Screenshot ${screenshot.file}`, errors)) {
      errors.push(`screenshot is missing or unsafe: ${screenshot.file}`);
      continue;
    }
    const screenshotReal = await realpath(screenshotPath);
    if (!pathInside(reportDirReal, screenshotReal)) {
      errors.push(`screenshot escapes its visual report directory: ${screenshot.file}`);
      continue;
    }
    const screenshotBytes = await readFile(screenshotPath);
    if (screenshotBytes.length !== screenshot.bytes) errors.push(`screenshot byte count does not match: ${screenshot.file}`);
    if (sha256(screenshotBytes) !== screenshot.sha256) errors.push(`screenshot hash does not match: ${screenshot.file}`);
    const selectedIndex = report?.coverage?.selectedSlideIndices?.[offset];
    if (Number.isInteger(selectedIndex) && screenshot.file !== `slide-${String(selectedIndex).padStart(3, '0')}.png`) {
      errors.push(`screenshot name does not match selected slide ${selectedIndex}`);
    }
    expectedNames.add(screenshot.file);
  }
  const actualNames = (await readdir(reportDir).catch(() => [])).filter(name => /^slide-\d{3,}\.png$/.test(name));
  if (!sameJson([...actualNames].sort(), [...expectedNames].sort())) errors.push('screenshot directory does not contain exactly the selected slides');
  return errors;
}

async function validatePdfReport(report, context, deckRoot, deckRootReal) {
  const errors = [
    ...reportHashes(report, context.inputSha256, context.manifestSha256, context.deliverySnapshot),
    ...reportIdentity(report, context.manifest, context.target)
  ];
  if (report?.ok !== true) errors.push('PDF report is not successful');
  if (report?.inputFile !== portablePath(deckRoot, context.htmlPath)) errors.push('PDF input file path is missing or not portable');
  if (report?.manifestFile !== portablePath(deckRoot, context.manifestPath)) errors.push('PDF manifest file path is missing or not portable');
  if (report?.requiredGate !== context.requiredGates.pdf) errors.push('PDF required gate does not match the manifest');
  if (report?.pageCount !== context.slideIds.length || report?.expectedPageCount !== context.slideIds.length) {
    errors.push('PDF page count does not match the manifest');
  }
  if (typeof report?.pdfFile !== 'string' || !report.pdfFile || isAbsolute(report.pdfFile)) return [...errors, 'portable PDF file path is missing'];
  const pdfPath = resolve(deckRoot, report.pdfFile);
  if (extname(pdfPath).toLowerCase() !== '.pdf' || !pathInside(deckRoot, pdfPath)) errors.push('PDF path is outside the delivery root or has the wrong extension');
  else if (!existsSync(pdfPath)) errors.push('PDF file does not exist');
  else if (!await safeRegularFile(deckRoot, deckRootReal, pdfPath, 'PDF file', errors)) {
    errors.push('PDF file is unsafe');
  }
  else {
    const pdf = await readFile(pdfPath);
    if (sha256(pdf) !== report.pdfSha256) errors.push('PDF hash does not match its report');
    if (countPdfPages(pdf) !== context.slideIds.length) errors.push('actual PDF page count does not match the manifest');
  }
  return errors;
}

async function writeJsonAtomic(filePath, value) {
  const temporaryPath = join(dirname(filePath), `.${randomUUID()}.delivery.tmp`);
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  try { await rename(temporaryPath, filePath); }
  finally { await unlink(temporaryPath).catch(error => { if (error.code !== 'ENOENT') throw error; }); }
}

export async function verifyDelivery(options = {}) {
  if (!options.htmlPath) throw new Error('HTML input is required.');
  const htmlPath = resolve(options.htmlPath);
  const deckRoot = dirname(htmlPath);
  const manifestPath = join(deckRoot, 'delivery-manifest.json');
  const reportDir = resolve(options.reportDir || join(deckRoot, 'qa-report'));
  const reportPath = resolve(options.reportPath || join(reportDir, 'delivery.json'));
  if (extname(reportPath).toLowerCase() !== '.json' || reportPath === htmlPath || reportPath === manifestPath) {
    throw new Error('Delivery report must be a distinct .json path.');
  }
  const deckRootReal = await realpath(deckRoot);
  await ensureSafeDirectory(deckRoot, deckRootReal, reportDir, 'QA report directory');
  await ensureSafeWriteTarget(deckRoot, deckRootReal, reportPath, 'Delivery report path');
  const startedAt = new Date().toISOString();
  const errors = [];
  let deliverySnapshot = null;
  try {
    deliverySnapshot = await captureDeliverySnapshot(htmlPath);
  } catch (error) {
    errors.push(`Delivery integrity snapshot failed: ${error.message}`);
  }
  const inputSafe = await safeRegularFile(deckRoot, deckRootReal, htmlPath, 'HTML input', errors);
  const inputBytes = inputSafe ? await readFile(htmlPath) : null;
  if (!existsSync(htmlPath)) errors.push(`HTML file does not exist: ${htmlPath}`);
  const inputSha256 = inputBytes ? sha256(inputBytes) : null;
  const manifestSafe = await safeRegularFile(deckRoot, deckRootReal, manifestPath, 'Delivery manifest', errors);
  const manifestBytes = manifestSafe ? await readFile(manifestPath) : null;
  if (!existsSync(manifestPath)) errors.push(`Delivery manifest does not exist: ${manifestPath}`);
  const manifestSha256 = manifestBytes ? sha256(manifestBytes) : null;
  let manifest = null;
  if (manifestBytes) {
    try { manifest = JSON.parse(manifestBytes.toString('utf8')); }
    catch (error) { errors.push(`Delivery manifest is not valid JSON: ${error.message}`); }
  }

  let deliveryProfile = 'standard-client';
  let requiredGates = requiredGatesFor(deliveryProfile);
  let target = { browser: 'chromium', os: 'current', viewport: null };
  let slideIds = [];
  if (manifest) {
    try { deliveryProfile = parseDeliveryProfile(manifest.deliveryProfile); }
    catch (error) { errors.push(error.message); }
    requiredGates = requiredGatesFor(deliveryProfile);
    if (!sameJson(manifest.requiredGates, requiredGates)) errors.push('Manifest requiredGates do not match its deliveryProfile.');
    try {
      target = {
        browser: parseTargetBrowser(manifest.target?.browser),
        os: parseTargetOs(manifest.target?.os),
        viewport: manifest.target?.viewport ?? null
      };
    } catch (error) { errors.push(error.message); }
    const viewport = target.viewport;
    if (!viewport || !Number.isInteger(viewport.width) || !Number.isInteger(viewport.height)
        || viewport.width < 320 || viewport.width > 7680 || viewport.height < 320 || viewport.height > 7680) {
      errors.push('Manifest target.viewport is missing or invalid.');
    }
    if (typeof manifest.offlineRequired !== 'boolean') errors.push('Manifest offlineRequired must be boolean.');
    if (deliveryProfile === 'high-assurance' && manifest.offlineRequired !== true) {
      errors.push('High-assurance delivery must be offlineRequired=true.');
    }
    if (!Array.isArray(manifest.slides) || manifest.slides.some((slide, offset) => slide?.index !== offset + 1 || typeof slide?.id !== 'string')) {
      errors.push('Manifest slides are missing or out of order.');
    } else {
      slideIds = manifest.slides.map(slide => slide.id);
      if (!slideIds.length || new Set(slideIds).size !== slideIds.length || slideIds.some(id => !id)) {
        errors.push('Manifest slide IDs must be non-empty and unique.');
      }
    }
    const relativeInput = relative(deckRoot, htmlPath).split('\\').join('/');
    const inputEntry = Array.isArray(manifest.files) ? manifest.files.find(file => file?.path === relativeInput) : null;
    if (!inputEntry || inputEntry.sha256 !== inputSha256) errors.push('Manifest HTML file entry is missing or its hash does not match.');
  }
  const governedManifest = { ...(manifest || {}), deliveryProfile, requiredGates, target };
  const receiptDeliverySnapshot = deliverySnapshot
    ? (({ htmlPath: _htmlPath, ...receipt }) => receipt)(deliverySnapshot)
    : null;
  const context = {
    htmlPath, manifestPath, inputSha256, manifestSha256,
    manifest: governedManifest, requiredGates, target, slideIds, layouts: null,
    deliverySnapshot: receiptDeliverySnapshot
  };

  const staticPath = resolve(options.staticReportPath || join(reportDir, 'qa-report.json'));
  const visualPath = resolve(options.visualReportPath || join(reportDir, 'report.json'));
  const pdfPath = resolve(options.pdfReportPath || join(reportDir, 'pdf.json'));
  const gates = {
    static: makeGate(requiredGates.static, staticPath, deckRoot),
    visual: makeGate(requiredGates.visual, visualPath, deckRoot),
    pdf: makeGate(requiredGates.pdf, pdfPath, deckRoot)
  };

  const staticReport = await readJsonReport(staticPath, 'Static QA report', gates.static.errors, deckRoot, deckRootReal, gates.static);
  if (!gates.static.present && gates.static.required) gates.static.errors.push('required static QA report is missing');
  if (staticReport) {
    gates.static.errors.push(...validateStaticReport(staticReport, context));
    context.layouts = staticReport.layouts;
  }
  gates.static.ok = gates.static.errors.length === 0 && (gates.static.present || !gates.static.required);

  const visualReport = await readJsonReport(visualPath, 'Visual QA report', gates.visual.errors, deckRoot, deckRootReal, gates.visual);
  if (!gates.visual.present && gates.visual.required) gates.visual.errors.push('required visual QA report is missing');
  if (visualReport) {
    const visualDir = dirname(visualPath);
    const visualDirReal = await realpath(visualDir);
    gates.visual.errors.push(...await validateVisualReport(
      visualReport, context, visualDir, visualDirReal, deckRoot, deckRootReal
    ));
  }
  gates.visual.ok = gates.visual.errors.length === 0 && (gates.visual.present || !gates.visual.required);

  const pdfReport = await readJsonReport(pdfPath, 'PDF report', gates.pdf.errors, deckRoot, deckRootReal, gates.pdf);
  if (!gates.pdf.present && gates.pdf.required) gates.pdf.errors.push('required PDF report is missing');
  if (pdfReport) gates.pdf.errors.push(...await validatePdfReport(pdfReport, context, deckRoot, deckRootReal));
  gates.pdf.ok = gates.pdf.errors.length === 0 && (gates.pdf.present || !gates.pdf.required);

  for (const [name, gate] of Object.entries(gates)) {
    for (const error of gate.errors) errors.push(`${name}: ${error}`);
  }
  if (deliverySnapshot) {
    try {
      await assertDeliverySnapshotStable(deliverySnapshot);
    } catch (error) {
      errors.push(`Delivery integrity snapshot became stale: ${error.message}`);
    }
  }
  const report = {
    schemaVersion: '1.0.0',
    kind: 'delivery-verification',
    ok: errors.length === 0,
    inputFile: portablePath(deckRoot, htmlPath),
    inputSha256,
    manifestFile: portablePath(deckRoot, manifestPath),
    manifestSha256,
    deliverySnapshot: receiptDeliverySnapshot,
    reportFile: portablePath(deckRoot, reportPath),
    deliveryProfile,
    requiredGates,
    target,
    slideIds,
    totalSlides: slideIds.length,
    startedAt,
    completedAt: new Date().toISOString(),
    gates,
    errors
  };
  await writeJsonAtomic(reportPath, report);
  return { ...report, reportPath };
}

const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  if (process.argv.includes('--help') || process.argv.includes('-h')) {
    console.log('Usage: node scripts/verify-delivery.mjs [--report-dir=<dir>] [--report=<path>] [--static-report=<path>] [--visual-report=<path>] [--pdf-report=<path>] <index.html>');
    process.exit(0);
  }
  try {
    let reportDir;
    let reportPath;
    let staticReportPath;
    let visualReportPath;
    let pdfReportPath;
    const positional = [];
    for (const argument of process.argv.slice(2)) {
      if (argument.startsWith('--report-dir=')) reportDir = argument.slice('--report-dir='.length);
      else if (argument.startsWith('--report=')) reportPath = argument.slice('--report='.length);
      else if (argument.startsWith('--static-report=')) staticReportPath = argument.slice('--static-report='.length);
      else if (argument.startsWith('--visual-report=')) visualReportPath = argument.slice('--visual-report='.length);
      else if (argument.startsWith('--pdf-report=')) pdfReportPath = argument.slice('--pdf-report='.length);
      else if (argument.startsWith('-')) throw new Error(`Unknown option: ${argument}`);
      else positional.push(argument);
    }
    if (positional.length !== 1) throw new Error('Exactly one index.html argument is required.');
    const result = await verifyDelivery({
      htmlPath: positional[0], reportDir, reportPath, staticReportPath, visualReportPath, pdfReportPath
    });
    for (const [name, gate] of Object.entries(result.gates)) {
      console.log(`${gate.ok ? 'PASS' : 'FAIL'} ${name}${gate.present ? '' : ' (not present)'}`);
    }
    console.log(`${result.ok ? 'PASS' : 'FAIL'} delivery verification: ${result.reportPath}`);
    if (!result.ok) result.errors.forEach(error => console.error(`ERROR ${error}`));
    process.exitCode = result.ok ? 0 : 1;
  } catch (error) {
    console.error(`Delivery verification failed: ${error.message}`);
    process.exitCode = 1;
  }
}

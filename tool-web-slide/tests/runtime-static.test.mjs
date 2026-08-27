import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, mkdir, mkdtemp, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { assertDeliverySnapshotStable, assertTargetOs, captureDeliverySnapshot, currentOs, findBrowserExecutable, inspectBrowserRuntime, installNetworkPolicy, isNetworkRequestAllowed, launchChromium, normalizeTargetBrowser, normalizeTargetOs, parseAspect, readDeckExecutionConfig, resolveChromiumLaunchArgs, resolveNetworkAccess } from '../scripts/lib/browser-runtime.mjs';
import { createStaticServer } from '../scripts/lib/static-server.mjs';
import { buildPdfReport, countPdfPages, exportPdf, validatePdfBuffer } from '../scripts/export-pdf.mjs';
import { browserGateSeverity, runPreflight } from '../scripts/preflight.mjs';
import { runVisualQa, selectVisualCoverage } from '../scripts/visual-qa.mjs';
import { verifyDelivery } from '../scripts/verify-delivery.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

test('aspect parser accepts supported deck ratios', () => {
  assert.equal(parseAspect('16:9').ratio, 16 / 9);
  assert.equal(parseAspect('16 / 10').ratio, 1.6);
  assert.equal(parseAspect('4x3').ratio, 4 / 3);
  assert.equal(parseAspect('').label, '16:9');
});

test('static server serves local files and rejects missing paths', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'web-slide-server-'));
  let server;
  try {
    await writeFile(join(directory, 'index.html'), '<!doctype html><title>ok</title>', 'utf8');
    server = await createStaticServer({ root: directory });
    const response = await fetch(`${server.baseUrl}/`);
    assert.equal(response.status, 200);
    assert.match(response.headers.get('content-type'), /^text\/html/);
    assert.match(await response.text(), /<title>ok<\/title>/);
    assert.equal((await fetch(`${server.baseUrl}/missing.js`)).status, 404);
    assert.equal(isNetworkRequestAllowed(`${server.baseUrl}/assets/core.css`, server.baseUrl), true);
    const otherPort = new URL(server.baseUrl);
    otherPort.port = String(Number(otherPort.port) + 1);
    assert.equal(isNetworkRequestAllowed(`${otherPort.origin}/assets/core.css`, server.baseUrl), false);
    assert.equal(isNetworkRequestAllowed('https://example.com/runtime.js', server.baseUrl), false);
    assert.equal(isNetworkRequestAllowed('data:text/plain,ok', server.baseUrl), true);
    assert.equal(isNetworkRequestAllowed('blob:https://example.com/id', server.baseUrl), true);
    assert.equal(isNetworkRequestAllowed('about:blank', server.baseUrl), true);
    assert.equal(isNetworkRequestAllowed('https://example.com/runtime.js', server.baseUrl, true), true);
    const localFileUrl = ['file:', '///etc/passwd'].join('');
    assert.equal(isNetworkRequestAllowed(localFileUrl, server.baseUrl, true), false);
  } finally {
    await server?.close();
    await rm(directory, { recursive: true, force: true });
  }
});

test('browser delivery snapshot validates the full manifest ledger and detects concurrent mutation', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'web-slide-snapshot-'));
  try {
    const html = Buffer.from('<!doctype html><title>snapshot</title>');
    const css = Buffer.from('body{color:#111}');
    await mkdir(join(directory, 'assets'));
    await writeFile(join(directory, 'index.html'), html);
    await writeFile(join(directory, 'assets', 'core.css'), css);
    const files = [
      { path: 'assets/core.css', bytes: css.length, sha256: sha256(css) },
      { path: 'index.html', bytes: html.length, sha256: sha256(html) }
    ];
    await writeFile(join(directory, 'delivery-manifest.json'), JSON.stringify({ files }));
    const snapshot = await captureDeliverySnapshot(join(directory, 'index.html'));
    assert.deepEqual(snapshot.files, files);
    await writeFile(join(directory, 'assets', 'core.css'), 'body{color:#222}');
    await assert.rejects(assertDeliverySnapshotStable(snapshot), /hash mismatch|changed while browser rendering/);
    await assert.rejects(captureDeliverySnapshot(join(directory, 'index.html')), /hash mismatch/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test('Chromium sandbox can only be disabled by explicit opt-in', () => {
  assert.throws(
    () => resolveChromiumLaunchArgs({ isRoot: true, allowNoSandbox: false }),
    /Refusing to disable the Chromium sandbox/
  );
  assert.throws(
    () => resolveChromiumLaunchArgs({ isRoot: false, allowNoSandbox: false, args: ['--no-sandbox'] }),
    /Refusing to disable the Chromium sandbox/
  );
  const optedIn = resolveChromiumLaunchArgs({ isRoot: true, allowNoSandbox: true });
  assert.ok(optedIn.args.includes('--no-sandbox'));
  assert.ok(optedIn.args.includes('--disable-setuid-sandbox'));
});

test('target browser and OS gates are strict and browser selection is target-specific', async () => {
  assert.equal(normalizeTargetBrowser('CHROME'), 'chrome');
  assert.equal(normalizeTargetOs('macOS'), 'macos');
  assert.throws(() => normalizeTargetBrowser('firefox'), /Unsupported target.browser/);
  assert.throws(() => normalizeTargetOs('android'), /Unsupported target.os/);
  assert.equal(assertTargetOs('current').actualOs, currentOs());
  assert.throws(() => assertTargetOs(currentOs() === 'windows' ? 'linux' : 'windows'), /does not match/);

  const directory = await mkdtemp(join(tmpdir(), 'web-slide-browser-target-'));
  const chrome = join(directory, 'chrome');
  const edge = join(directory, 'edge');
  const previousChrome = process.env.CHROME_PATH;
  const previousEdge = process.env.EDGE_PATH;
  try {
    await writeFile(chrome, 'fake', 'utf8');
    await writeFile(edge, 'fake', 'utf8');
    process.env.CHROME_PATH = chrome;
    process.env.EDGE_PATH = edge;
    const chromium = { executablePath: () => join(directory, 'missing-chromium') };
    assert.equal(findBrowserExecutable(chromium, 'chrome').path, chrome);
    assert.equal(findBrowserExecutable(chromium, 'edge').path, edge);
    assert.equal(findBrowserExecutable(chromium, 'chromium'), null);
  } finally {
    if (previousChrome === undefined) delete process.env.CHROME_PATH; else process.env.CHROME_PATH = previousChrome;
    if (previousEdge === undefined) delete process.env.EDGE_PATH; else process.env.EDGE_PATH = previousEdge;
    await rm(directory, { recursive: true, force: true });
  }
});

test('execution config reads HTML and manifest and enforces governed network mode', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'web-slide-execution-config-'));
  const html = join(directory, 'index.html');
  const manifest = join(directory, 'delivery-manifest.json');
  try {
    await writeFile(html, '<!doctype html><html data-target-browser="edge" data-target-os="current" data-delivery-profile="high-assurance" data-offline-required="true"><body></body></html>', 'utf8');
    await writeFile(manifest, JSON.stringify({ target: { browser: 'edge', os: 'current' }, deliveryProfile: 'high-assurance', offlineRequired: true }), 'utf8');
    const config = await readDeckExecutionConfig(html);
    assert.equal(config.targetBrowser, 'edge');
    assert.equal(config.offlineRequired, true);
    assert.throws(() => resolveNetworkAccess({ allowNetwork: true, ...config }), /--allow-network is forbidden/);
    assert.equal(resolveNetworkAccess({ allowNetwork: false, ...config }).locked, true);
    assert.equal(resolveNetworkAccess({ allowNetwork: true, offlineRequired: false, deliveryProfile: 'standard-client' }).allowNetwork, true);

    await writeFile(manifest, JSON.stringify({ target: { browser: 'chrome', os: 'current' }, deliveryProfile: 'high-assurance', offlineRequired: true }), 'utf8');
    await assert.rejects(readDeckExecutionConfig(html), /mismatch.*targetBrowser/i);

    const incompatibleOs = currentOs() === 'windows' ? 'linux' : 'windows';
    await writeFile(html, `<!doctype html><html data-target-browser="chromium" data-target-os="${incompatibleOs}" data-delivery-profile="standard-client" data-offline-required="false"><body></body></html>`, 'utf8');
    await writeFile(manifest, JSON.stringify({ target: { browser: 'chromium', os: incompatibleOs }, deliveryProfile: 'standard-client', offlineRequired: false }), 'utf8');
    const preflight = await runPreflight({ htmlPath: html });
    assert.equal(preflight.checks.find(check => check.name === 'execution-target')?.ok, false);
    assert.ok(preflight.errors.some(error => /does not match/.test(error)));
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test('static server rejects a symlink whose real target is outside root', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'web-slide-symlink-'));
  const served = join(directory, 'served');
  const outside = join(directory, 'outside.txt');
  let server;
  try {
    await mkdir(served);
    await writeFile(join(served, 'index.html'), '<!doctype html><title>safe</title>', 'utf8');
    await writeFile(outside, 'secret', 'utf8');
    await symlink(outside, join(served, 'escape.txt'));
    server = await createStaticServer({ root: served });
    const response = await fetch(`${server.baseUrl}/escape.txt`);
    assert.equal(response.status, 403);
    assert.throws(() => server.urlFor(join(served, 'escape.txt')), /outside static server root/);
  } finally {
    await server?.close();
    await rm(directory, { recursive: true, force: true });
  }
});

test('engine has offline fallbacks and a deterministic ready contract', async () => {
  const engine = await readFile(join(root, 'assets', 'slide-engine.js'), 'utf8');
  const icons = await readFile(join(root, 'assets', 'icon-runtime.js'), 'utf8');
  assert.doesNotMatch(engine, /cdn\.jsdelivr|unpkg\.com|https:\/\/.*motion/i);
  assert.match(engine, /__WEB_SLIDE_STANDALONE__/);
  assert.match(engine, /__DECK_READY/);
  assert.match(engine, /web-slide:/);
  assert.match(engine, /crypto\?\.getRandomValues/);
  assert.match(engine, /new BroadcastChannel\(`web-slide:\$\{id\}:\$\{this\.capability\}`\)/);
  assert.match(engine, /fragmentParams\.get\('cap'\)/);
  assert.match(engine, /url\.hash = capability \? `cap=/);
  assert.doesNotMatch(engine, /url\.searchParams\.set\(['"]cap['"]/);
  assert.match(engine, /capability:\s*this\.capability/);
  assert.match(engine, /message\.capability !== this\.capability/);
  assert.match(engine, /isKnownSource\(event\.source\)/);
  assert.match(engine, /addEventListener\('click'/);
  assert.match(icons, /createIcons/);
});

test('PDF page counter ignores the Pages tree object', () => {
  const pdf = Buffer.from('%PDF-1.7\n1 0 obj <</Type /Pages /Count 2>>\n2 0 obj <</Type /Page>>\n3 0 obj <</Type /Page>>', 'latin1');
  assert.equal(countPdfPages(pdf), 2);
  assert.equal(validatePdfBuffer(pdf, 2), 2);
  assert.throws(() => validatePdfBuffer(pdf, 3), /page count mismatch/);
  assert.throws(() => validatePdfBuffer(Buffer.from('%PDF-1.7'), 1), /could not be verified/);
});

test('PDF export rejects unsafe output targets before browser launch', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'web-slide-pdf-path-'));
  const html = join(directory, 'index.html');
  try {
    await writeFile(html, '<!doctype html><title>safe</title>', 'utf8');
    await assert.rejects(exportPdf({ htmlPath: html, outputPath: html }), /must differ/);
    await assert.rejects(exportPdf({ htmlPath: html, outputPath: join(directory, 'deck.txt') }), /\.pdf extension/);
    await mkdir(join(directory, 'qa-report'));
    await writeFile(join(directory, 'outside-report.json'), 'sentinel');
    await symlink(join(directory, 'outside-report.json'), join(directory, 'qa-report', 'pdf.json'));
    await assert.rejects(exportPdf({ htmlPath: html, outputPath: join(directory, 'deck.pdf') }), /must not be a symlink/);
    await rm(join(directory, 'qa-report', 'pdf.json'));
    await writeFile(html, '<!doctype html><html data-target-browser="chromium" data-target-os="current" data-delivery-profile="high-assurance" data-offline-required="false"><body></body></html>', 'utf8');
    await assert.rejects(exportPdf({ htmlPath: html, outputPath: join(directory, 'deck.pdf'), allowNetwork: true }), /--allow-network is forbidden/);
    await assert.rejects(runVisualQa({ htmlPath: html, outputDir: join(directory, 'qa-report'), allowNetwork: true }), /--allow-network is forbidden/);
    const source = await readFile(join(root, 'scripts', 'export-pdf.mjs'), 'utf8');
    assert.ok(source.indexOf('await page?.close()') < source.indexOf('await unlink(temporaryPath)'));
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test('visual coverage follows sample, layout, and all profile gates deterministically', () => {
  const slides = [
    { id: 'opening', layout: 'hero' },
    { id: 'context', layout: 'content' },
    { id: 'detail-a', layout: 'content' },
    { id: 'detail-b', layout: 'grid' },
    { id: 'detail-c', layout: 'grid' },
    { id: 'summary', layout: 'content' },
    { id: 'closing', layout: 'hero' }
  ];
  assert.deepEqual(selectVisualCoverage(slides, 'sample').selectedSlideIndices, [1, 4, 7]);
  const layouts = selectVisualCoverage(slides, 'layouts');
  assert.deepEqual(layouts.selectedSlideIndices, [1, 2, 4, 7]);
  assert.deepEqual(layouts.coveredLayouts, ['hero', 'content', 'grid']);
  assert.deepEqual(selectVisualCoverage(slides, 'all').selectedSlideIndices, [1, 2, 3, 4, 5, 6, 7]);
  assert.deepEqual(selectVisualCoverage(slides.slice(0, 3), 'sample').selectedSlideIndices, [1, 2, 3]);
});

test('visual QA rejects an output directory symlink that escapes the delivery root', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'web-slide-visual-root-'));
  const outside = await mkdtemp(join(tmpdir(), 'web-slide-visual-outside-'));
  const htmlPath = join(directory, 'index.html');
  const sentinel = join(outside, 'slide-001.png');
  try {
    await writeFile(htmlPath, '<!doctype html><main id="deck"><section class="slide">safe</section></main>');
    await writeFile(sentinel, 'keep');
    await symlink(outside, join(directory, 'qa-report'));
    await assert.rejects(runVisualQa({ htmlPath, outputDir: join(directory, 'qa-report') }), /escapes|symlink/);
    assert.equal(await readFile(sentinel, 'utf8'), 'keep');
  } finally {
    await rm(directory, { recursive: true, force: true });
    await rm(outside, { recursive: true, force: true });
  }
});

test('preflight browser gate is advisory except for high assurance or explicit enforcement', () => {
  assert.equal(browserGateSeverity('quick-internal'), 'warning');
  assert.equal(browserGateSeverity('standard-client'), 'warning');
  assert.equal(browserGateSeverity('high-assurance'), 'error');
  assert.equal(browserGateSeverity('quick-internal', true), 'error');
});

test('PDF report schema records integrity, target, profile, network, and time', () => {
  const report = buildPdfReport({
    inputFile: 'index.html', inputSha256: 'input', manifestFile: 'delivery-manifest.json',
    manifestSha256: 'manifest', pdfFile: 'deck.pdf', pdfSha256: 'pdf', pageCount: 3,
    expectedPageCount: 3, deliveryProfile: 'high-assurance', requiredGate: 'required',
    executionTarget: { targetBrowser: 'chromium', actualBrowser: 'chromium' },
    networkPolicy: { mode: 'isolated' }, startedAt: '2026-01-01T00:00:00.000Z',
    completedAt: '2026-01-01T00:00:01.000Z'
  });
  assert.equal(report.ok, true);
  assert.equal(report.pdfSha256, 'pdf');
  assert.equal(report.requiredGate, 'required');
  assert.equal(report.networkPolicy.mode, 'isolated');
});

test('delivery verifier accepts fresh required evidence and rejects stale or invalid optional reports', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'web-slide-delivery-verify-'));
  const outsideDirectory = await mkdtemp(join(tmpdir(), 'web-slide-delivery-outside-'));
  const qa = join(directory, 'qa-report');
  const htmlPath = join(directory, 'index.html');
  const manifestPath = join(directory, 'delivery-manifest.json');
  const html = Buffer.from('<!doctype html><html><body><main id="deck"></main></body></html>');
  const asset = Buffer.from('body{background:#fff}');
  const target = { browser: 'chromium', os: 'current', viewport: { width: 1920, height: 1080 } };
  const slideIds = ['opening', 'context', 'detail', 'closing'];
  const layouts = ['hero', 'content', 'content', 'closing'];
  const requiredGates = { static: true, visual: 'layouts', pdf: 'optional' };
  const manifest = {
    deliveryProfile: 'standard-client', offlineRequired: true, requiredGates, target,
    slides: slideIds.map((id, offset) => ({ index: offset + 1, id })),
    files: [
      { path: 'assets/core.css', bytes: asset.length, sha256: sha256(asset) },
      { path: 'index.html', bytes: html.length, sha256: sha256(html) }
    ]
  };
  try {
    await mkdir(qa);
    await mkdir(join(directory, 'assets'));
    await writeFile(htmlPath, html);
    await writeFile(join(directory, 'assets', 'core.css'), asset);
    await writeFile(manifestPath, `${JSON.stringify(manifest)}\n`);
    const manifestSha256 = sha256(await readFile(manifestPath));
    const inputSha256 = sha256(html);
    const deliverySnapshot = {
      inputFile: 'index.html', inputSha256,
      manifestFile: 'delivery-manifest.json', manifestSha256,
      files: manifest.files
    };
    await writeFile(join(qa, 'qa-report.json'), JSON.stringify({
      valid: true, inputSha256, manifestSha256, deliverySnapshot, slideIds, layouts,
      configuration: { deliveryProfile: 'standard-client', requiredGates, target },
      summary: { slides: slideIds.length }
    }));
    const executionTarget = {
      targetBrowser: 'chromium', actualBrowser: 'chromium', targetOs: 'current',
      actualOs: currentOs(), resolvedTargetOs: currentOs()
    };
    const networkPolicy = {
      mode: 'isolated', allowNetwork: false, allowedOrigin: 'http://127.0.0.1:41234',
      gate: { deliveryProfile: 'standard-client', offlineRequired: true, allowNetwork: false }
    };
    const selectedSlideIndices = [1, 2, 4];
    const selectedSlideIds = selectedSlideIndices.map(index => slideIds[index - 1]);
    const screenshots = selectedSlideIndices.map(index => `slide-${String(index).padStart(3, '0')}.png`);
    const screenshotBytes = Buffer.from('png');
    await Promise.all(screenshots.map(name => writeFile(join(qa, name), screenshotBytes)));
    await writeFile(join(qa, 'report.json'), JSON.stringify({
      ok: true, inputSha256, manifestSha256, deliverySnapshot, deliveryProfile: 'standard-client', requiredGate: 'layouts',
      executionTarget, networkPolicy, startedAt: '2026-01-01T00:00:00.000Z', completedAt: '2026-01-01T00:00:01.000Z',
      coverage: {
        mode: 'layouts', totalSlides: slideIds.length, selectedCount: selectedSlideIndices.length,
        selectedSlideIndices, selectedSlideIds, uniqueLayouts: [...new Set(layouts)],
        coveredLayouts: [...new Set(selectedSlideIndices.map(index => layouts[index - 1]))],
        layoutCoverage: [...new Set(layouts)].map(layout => ({
          layout,
          total: layouts.filter(candidate => candidate === layout).length,
          selected: selectedSlideIndices.filter(index => layouts[index - 1] === layout).length
        }))
      },
      slides: screenshots.map((file, offset) => ({
        index: selectedSlideIndices[offset], id: selectedSlideIds[offset],
        screenshot: { file, bytes: screenshotBytes.length, sha256: sha256(screenshotBytes) }
      }))
    }));

    const passed = await verifyDelivery({ htmlPath });
    assert.equal(passed.ok, true, passed.errors.join('\n'));
    assert.equal(passed.gates.pdf.ok, true);
    assert.equal(passed.gates.pdf.present, false);

    await writeFile(join(directory, 'assets', 'core.css'), 'body{background:#000}');
    const tamperedAsset = await verifyDelivery({ htmlPath });
    assert.equal(tamperedAsset.ok, false);
    assert.ok(tamperedAsset.errors.some(error => /Delivery integrity snapshot failed.*hash mismatch/.test(error)));
    await writeFile(join(directory, 'assets', 'core.css'), asset);

    const escapedScreenshot = screenshots[0];
    const outsideScreenshot = join(outsideDirectory, escapedScreenshot);
    await writeFile(outsideScreenshot, screenshotBytes);
    await rm(join(qa, escapedScreenshot));
    await symlink(outsideScreenshot, join(qa, escapedScreenshot));
    const unsafeScreenshot = await verifyDelivery({ htmlPath });
    assert.equal(unsafeScreenshot.ok, false);
    assert.ok(unsafeScreenshot.gates.visual.errors.some(error => /symlink|unsafe|escapes/.test(error)));
    await rm(join(qa, escapedScreenshot));
    await writeFile(join(qa, escapedScreenshot), screenshotBytes);

    const pdfBytes = Buffer.from('%PDF-1.7\n1 0 obj <</Type /Page>>\n2 0 obj <</Type /Page>>\n3 0 obj <</Type /Page>>\n4 0 obj <</Type /Page>>', 'latin1');
    const outsidePdf = join(outsideDirectory, 'deck.pdf');
    await writeFile(outsidePdf, pdfBytes);
    await symlink(outsidePdf, join(directory, 'deck.pdf'));
    await writeFile(join(qa, 'pdf.json'), JSON.stringify({
      ok: true, inputSha256, manifestSha256, deliverySnapshot, pdfFile: 'deck.pdf', pdfSha256: sha256(pdfBytes),
      pageCount: 4, expectedPageCount: 4, deliveryProfile: 'standard-client', requiredGate: 'optional',
      executionTarget, networkPolicy, startedAt: '2026-01-01T00:00:00.000Z', completedAt: '2026-01-01T00:00:01.000Z'
    }));
    const invalidOptional = await verifyDelivery({ htmlPath });
    assert.equal(invalidOptional.ok, false);
    assert.ok(invalidOptional.gates.pdf.errors.some(error => /symlink|unsafe|escapes/.test(error)));

    await rm(join(qa, 'pdf.json'));
    await rm(join(directory, 'deck.pdf'));
    const visual = JSON.parse(await readFile(join(qa, 'report.json'), 'utf8'));
    visual.inputSha256 = 'stale';
    await writeFile(join(qa, 'report.json'), JSON.stringify(visual));
    const stale = await verifyDelivery({ htmlPath });
    assert.equal(stale.ok, false);
    assert.ok(stale.gates.visual.errors.some(error => /HTML hash/.test(error)));
  } finally {
    await rm(directory, { recursive: true, force: true });
    await rm(outsideDirectory, { recursive: true, force: true });
  }
});

test('delivery verifier rejects symlinked gate and receipt targets', async () => {
  const parent = await mkdtemp(join(tmpdir(), 'web-slide-delivery-symlink-'));
  const directory = join(parent, 'deck');
  const outside = join(parent, 'outside');
  const qa = join(directory, 'qa-report');
  const htmlPath = join(directory, 'index.html');
  try {
    await mkdir(qa, { recursive: true });
    await mkdir(outside);
    const html = Buffer.from('<!doctype html><main id="deck"></main>');
    await writeFile(htmlPath, html);
    const manifest = {
      deliveryProfile: 'quick-internal', offlineRequired: true,
      requiredGates: { static: true, visual: 'sample', pdf: 'optional' },
      target: { browser: 'chromium', os: 'current', viewport: { width: 1920, height: 1080 } },
      slides: [{ index: 1, id: 'only' }], files: [{ path: 'index.html', bytes: html.length, sha256: sha256(html) }]
    };
    await writeFile(join(directory, 'delivery-manifest.json'), JSON.stringify(manifest));
    const outsideStatic = join(outside, 'qa-report.json');
    await writeFile(outsideStatic, '{}');
    await symlink(outsideStatic, join(qa, 'qa-report.json'));
    const unsafeGate = await verifyDelivery({ htmlPath });
    assert.equal(unsafeGate.ok, false);
    assert.ok(unsafeGate.gates.static.errors.some(error => /symlink|regular file/.test(error)));

    await rm(join(qa, 'delivery.json'));
    const outsideReceipt = join(outside, 'delivery.json');
    await writeFile(outsideReceipt, 'sentinel');
    await symlink(outsideReceipt, join(qa, 'delivery.json'));
    await assert.rejects(verifyDelivery({ htmlPath }), /must not be a symlink/);
    assert.equal(await readFile(outsideReceipt, 'utf8'), 'sentinel');
  } finally {
    await rm(parent, { recursive: true, force: true });
  }
});

test('browser runtime can complete a minimal local HTTP render when available', async t => {
  const runtime = await inspectBrowserRuntime({ targetBrowser: 'chromium' });
  if (!runtime.ok) {
    t.skip(runtime.error);
    return;
  }
  const directory = await mkdtemp(join(tmpdir(), 'web-slide-browser-e2e-'));
  let server;
  let browser;
  let page;
  try {
    await writeFile(join(directory, 'index.html'), '<!doctype html><title>local-e2e</title><main id="deck"><section class="slide">ok</section></main>', 'utf8');
    server = await createStaticServer({ root: directory });
    const launched = await launchChromium({ targetBrowser: 'chromium' });
    browser = launched.browser;
    page = await browser.newPage({ serviceWorkers: 'block' });
    const policy = await installNetworkPolicy(page, { allowedOrigin: server.baseUrl });
    await page.goto(server.urlFor(join(directory, 'index.html')), { waitUntil: 'domcontentloaded' });
    assert.equal(await page.title(), 'local-e2e');
    assert.equal(policy.blockedRequests.length, 0);
  } finally {
    await page?.close().catch(() => {});
    await browser?.close().catch(() => {});
    await server?.close().catch(() => {});
    await rm(directory, { recursive: true, force: true });
  }
});

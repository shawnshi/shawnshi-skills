import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { cpSync, mkdtempSync, mkdirSync, readFileSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { validateDeck } from '../scripts/lib/deck-validator.mjs';
import { initDeck } from '../scripts/init-deck.mjs';
import { buildDeck } from '../scripts/build-deck.mjs';

const skillRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function makeDeck({ html, config, manifest = true } = {}) {
  const root = mkdtempSync(join(tmpdir(), 'web-slide-qa-'));
  mkdirSync(join(root, 'assets'));
  cpSync(join(skillRoot, 'assets', 'core.css'), join(root, 'assets', 'core.css'));
  cpSync(join(skillRoot, 'assets', 'icon-runtime.js'), join(root, 'assets', 'icon-runtime.js'));
  cpSync(join(skillRoot, 'assets', 'slide-engine.js'), join(root, 'assets', 'slide-engine.js'));
  const source = html ?? validHtml();
  writeFileSync(join(root, 'index.html'), source);
  if (config) writeFileSync(join(root, 'deck.config.json'), JSON.stringify(config));
  if (manifest) {
    const fileEntry = (path) => {
      const bytes = readFileSync(join(root, path));
      return { path, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') };
    };
    writeFileSync(join(root, 'delivery-manifest.json'), JSON.stringify({
      schemaVersion: '1.0.0',
      mode: 'bundle',
      theme: 'swiss',
      aspect: '16:9',
      deliveryProfile: 'standard-client',
      requiredGates: { static: true, visual: 'layouts', pdf: 'optional' },
      evidencePolicy: 'advisory',
      offlineRequired: false,
      externalDependencies: 0,
      externalDependencyUrls: [],
      target: { browser: 'chromium', os: 'current', viewport: { width: 1920, height: 1080 } },
      slides: [{ index: 1, id: 'intro' }],
      files: ['assets/core.css', 'assets/icon-runtime.js', 'assets/slide-engine.js', 'index.html'].map(fileEntry),
    }));
  }
  return { root, file: join(root, 'index.html') };
}

function validHtml(slides = `
  <section class="slide" data-slide-id="intro" data-layout="hero" data-evidence="none">
    <div class="canvas-card layout-hero"><h1>Valid deck</h1></div>
  </section>`) {
  return `<!doctype html>
<html lang="en" data-delivery-profile="standard-client" data-aspect="16:9" data-deck-width="1920" data-deck-height="1080" data-target-browser="chromium" data-target-os="current" data-offline-required="false" data-evidence-policy="advisory">
<head><title>Deck</title><link rel="stylesheet" href="./assets/core.css"></head>
<body data-theme="swiss" data-delivery-profile="standard-client" data-aspect="16:9" data-deck-width="1920" data-deck-height="1080" data-target-browser="chromium" data-target-os="current"><div id="deck">${slides}</div>
<script src="./assets/icon-runtime.js"></script><script src="./assets/slide-engine.js"></script></body></html>`;
}

function codes(report) { return new Set(report.issues.map((issue) => issue.code)); }
function validate(file, options = {}) { return validateDeck(file, { ...options, writeReport: false }); }

test('valid DOM and multi-class canvas-card pass', () => {
  const { file } = makeDeck();
  const report = validate(file);
  assert.equal(report.valid, true, JSON.stringify(report.issues, null, 2));
});

test('static QA binds parsing and receipts to one stable delivery snapshot', () => {
  const { file } = makeDeck();
  const initial = readFileSync(file);
  const report = validateDeck(file, {
    writeReport: false,
    _beforeSnapshotRecheck() {
      writeFileSync(file, Buffer.concat([initial, Buffer.from('\n<!-- concurrent mutation -->\n')]));
    },
  });
  assert.ok(codes(report).has('DELIVERY_CHANGED_DURING_QA'));
  assert.equal(report.valid, false);
  assert.equal(report.inputSha256, createHash('sha256').update(initial).digest('hex'));
});

test('comments cannot impersonate slides', () => {
  const { file } = makeDeck({ html: validHtml('<!-- <section class="slide"><div class="canvas-card"></div></section> -->') });
  assert.ok(codes(validate(file)).has('SLIDES_MISSING'));
});

test('canvas-card is checked on every slide', () => {
  const slides = `
    <section class="slide" data-slide-id="one" data-layout="hero" data-evidence="none"><div class="canvas-card layout-hero"><h1>One</h1></div></section>
    <section class="slide layout-hero" data-slide-id="two" data-layout="hero" data-evidence="none"><h2>Two</h2></section>`;
  const { file } = makeDeck({ html: validHtml(slides) });
  assert.ok(codes(validate(file)).has('CANVAS_CARD_INVALID'));
});

test('only CSS actually loaded by the page defines classes and variables', () => {
  const { root, file } = makeDeck({ html: validHtml().replace('</head>', '<style>.bad{color:var(--brand-does-not-exist)}</style></head>') });
  writeFileSync(join(root, 'assets', 'unlinked.css'), '.phantom{color:red}');
  writeFileSync(file, readFileSync(file, 'utf8').replace('layout-hero', 'layout-hero phantom'));
  const resultCodes = codes(validate(file));
  assert.ok(resultCodes.has('CSS_VARIABLE_UNDEFINED'));
  assert.ok(resultCodes.has('CSS_CLASS_UNDEFINED'));
});

test('missing referenced scripts and images fail, alt is required', () => {
  const html = validHtml().replace('<h1>Valid deck</h1>', '<h1>Valid deck</h1><img src="images/missing.png">')
    .replace('assets/slide-engine.js', 'assets/missing.js');
  const { file } = makeDeck({ html });
  const resultCodes = codes(validate(file));
  assert.ok(resultCodes.has('RESOURCE_MISSING'));
  assert.ok(resultCodes.has('IMAGE_ALT_MISSING'));
});

test('theme, layout, slide id, deck root and evidence are explicit contracts', () => {
  const slides = '<div><section class="slide" data-slide-id="Bad ID" data-layout="unknown"><div class="canvas-card"><p>No heading</p></div></section></div>';
  const { file } = makeDeck({ html: validHtml(slides).replace('data-theme="swiss"', '') });
  const resultCodes = codes(validate(file));
  for (const expected of ['THEME_MISSING', 'SLIDE_ID_INVALID', 'LAYOUT_UNKNOWN', 'SLIDE_NOT_DIRECT_DECK_CHILD', 'EVIDENCE_DECLARATION_MISSING', 'SLIDE_HEADING_MISSING']) {
    assert.ok(resultCodes.has(expected), `missing ${expected}`);
  }
});

test('required evidence needs a structured source note', () => {
  const slides = '<section class="slide" data-slide-id="evidence" data-layout="hero" data-evidence="required"><div class="canvas-card layout-hero"><h1>Claim</h1><p class="source-note" data-source="" data-source-date="">Source</p></div></section>';
  const { file } = makeDeck({ html: validHtml(slides) });
  const resultCodes = codes(validate(file));
  assert.ok(resultCodes.has('SOURCE_NOTE_FIELDS_MISSING'));
  assert.ok(resultCodes.has('SOURCE_NOTE_REQUIRED'));
});

test('offline policy, event handlers, and arbitrary inline scripts are blocked', () => {
  const html = validHtml().replace('</head>', '<link rel="preconnect" href="https://example.com"></head>')
    .replace('<h1>Valid deck</h1>', '<h1 onclick="alert(1)">Valid deck</h1>')
    .replace('</body>', '<script>alert(1)</script></body>');
  const { file } = makeDeck({ html, config: { offlineRequired: true, evidencePolicy: 'advisory' } });
  const resultCodes = codes(validate(file));
  assert.ok(resultCodes.has('REMOTE_RESOURCE_OFFLINE'));
  assert.ok(resultCodes.has('INLINE_EVENT_HANDLER'));
  assert.ok(resultCodes.has('INLINE_EXECUTABLE_SCRIPT'));
});

test('real standalone builder output passes canonical inline-asset checks', async () => {
  const root = mkdtempSync(join(tmpdir(), 'web-slide-standalone-'));
  await initDeck({ projectDir: root, mode: 'standalone', theme: 'swiss', skillRoot });
  const built = await buildDeck({ projectDir: root, mode: 'standalone', skillRoot });
  const report = validate(join(built.outputDir, 'index.html'));
  assert.equal(report.valid, true, JSON.stringify(report.issues, null, 2));
});

test('evidence placeholders do not satisfy required mode', () => {
  const slides = '<section class="slide" data-slide-id="claim" data-layout="hero" data-evidence="required"><div class="canvas-card layout-hero"><h1>Claim</h1><p class="source-note" data-source="TODO" data-source-date="待核验">x</p></div></section>';
  const { file } = makeDeck({ html: validHtml(slides) });
  assert.ok(codes(validate(file)).has('SOURCE_NOTE_FIELDS_MISSING'));
});

test('offline truth cannot be bypassed with allowRemote', () => {
  const html = validHtml().replace('</head>', '<link rel="preconnect" href="https://example.com"></head>');
  const { file } = makeDeck({ html, config: { offlineRequired: true, evidencePolicy: 'advisory' } });
  assert.ok(codes(validate(file, { allowRemote: true })).has('REMOTE_RESOURCE_OFFLINE'));
});

test('canonical bundle script names do not hide modified content', () => {
  const { root, file } = makeDeck();
  writeFileSync(join(root, 'assets', 'slide-engine.js'), 'console.log("replaced")');
  assert.ok(codes(validate(file)).has('SCRIPT_ASSET_CONTENT_MISMATCH'));
});

test('resource symlinks cannot escape the delivery directory', () => {
  const outside = mkdtempSync(join(tmpdir(), 'web-slide-outside-'));
  writeFileSync(join(outside, 'image.png'), 'not-an-image');
  const html = validHtml().replace('<h1>Valid deck</h1>', '<h1>Valid deck</h1><img src="images/link.png" alt="test">');
  const { root, file } = makeDeck({ html });
  mkdirSync(join(root, 'images'));
  symlinkSync(join(outside, 'image.png'), join(root, 'images', 'link.png'));
  assert.ok(codes(validate(file)).has('RESOURCE_NOT_PORTABLE'));
});

test('base elements and remote form submission are blocked', () => {
  const html = validHtml().replace('</head>', '<base href="https://example.com/"></head>')
    .replace('<h1>Valid deck</h1>', '<h1>Valid deck</h1><form action="https://example.com/collect"><button>Send</button></form>');
  const { file } = makeDeck({ html, config: { offlineRequired: true, evidencePolicy: 'advisory' } });
  const resultCodes = codes(validate(file));
  assert.ok(resultCodes.has('BASE_ELEMENT_PROHIBITED'));
  assert.ok(resultCodes.has('REMOTE_FORM_TARGET_OFFLINE'));
});

test('entity-encoded schemes, active embeds, and unsafe data MIME cannot bypass policy', () => {
  const html = validHtml()
    .replace('data-offline-required="false"', 'data-offline-required="true"')
    .replace('</head>', '<link rel="preload" href="http&#58;//example.com/x"><link rel="icon" href="javascript&colon;alert(1)"></head>')
    .replace('<h1>Valid deck</h1>', '<h1>Valid deck</h1><iframe src="about:blank"></iframe><object data="blob:evil"></object><embed src="data:text/html,x"><img src="data:text/html,x" alt="unsafe">')
    .replace('</body>', '<script src="jav&#x61;script&colon;alert(1)"></script><a href="java&Tab;script&colon;alert(1)">x</a></body>');
  const { file } = makeDeck({ html });
  const resultCodes = codes(validate(file));
  assert.ok(resultCodes.has('EMBED_ELEMENT_PROHIBITED'));
  assert.ok(resultCodes.has('DANGEROUS_URL'));
  assert.ok(resultCodes.has('REMOTE_RESOURCE_OFFLINE'));
  assert.ok(resultCodes.has('DANGEROUS_DATA_MIME'));
  assert.ok(resultCodes.has('BLOB_URL_NOT_ALLOWED'));
});

test('safe image data MIME remains available for self-contained media', () => {
  const html = validHtml().replace('<h1>Valid deck</h1>', '<h1>Valid deck</h1><img src="data:image/png;base64,iVBORw0KGgo=" alt="pixel">');
  const { file } = makeDeck({ html });
  const report = validate(file);
  assert.equal(report.valid, true, JSON.stringify(report.issues, null, 2));
});

test('srcset tokenizer preserves commas inside data URLs', () => {
  const html = validHtml().replace('<h1>Valid deck</h1>', '<h1>Valid deck</h1><img src="data:image/png;base64,AAAA" srcset="data:image/png;base64,AAAA 1x, data:image/png;base64,BBBB 2x" alt="pixels">');
  const { file } = makeDeck({ html });
  const report = validate(file);
  assert.equal(report.valid, true, JSON.stringify(report.issues, null, 2));
  assert.equal(report.resources.missing.length, 0);
});

test('blob URLs are rejected even for image and media elements', () => {
  const html = validHtml().replace('<h1>Valid deck</h1>', '<h1>Valid deck</h1><img src="blob:https://example.com/id" alt="x"><video src="blob:https://example.com/video"></video>');
  const { file } = makeDeck({ html });
  assert.ok(codes(validate(file)).has('BLOB_URL_NOT_ALLOWED'));
});

test('encoded meta refresh and anchor ping are prohibited', () => {
  const html = validHtml().replace('</head>', '<meta http-equiv="refr&#x65;sh" content="0;url=http&#58;//example.com"></head>')
    .replace('<h1>Valid deck</h1>', '<h1>Valid deck</h1><a href="#ok" ping="http&#58;//tracker.example/p">Open</a><map><area ping="/local-tracker"></map>');
  const { file } = makeDeck({ html });
  const resultCodes = codes(validate(file));
  assert.ok(resultCodes.has('META_REFRESH'));
  assert.ok(resultCodes.has('PING_ATTRIBUTE_PROHIBITED'));
});

test('SVG fetch attributes and escaped CSS resource functions are scanned', () => {
  const css = String.raw`<style>.probe{background-image:\75rl(https://example.com/a.png);mask-image:image-set("images/missing.png" 1x)}.probe-upper{background:URL(https://example.com/upper.png)}</style>`;
  const html = validHtml().replace('data-offline-required="false"', 'data-offline-required="true"')
    .replace('</head>', `${css}</head>`)
    .replace('<h1>Valid deck</h1>', '<h1>Valid deck</h1><div class="probe probe-upper"></div><svg><use href="https://example.com/sprite.svg#icon"></use><feImage xlink:href="https://example.com/image.png"></feImage></svg>');
  const { file } = makeDeck({ html });
  const resultCodes = codes(validate(file));
  assert.ok(resultCodes.has('REMOTE_RESOURCE_OFFLINE'));
  assert.ok(resultCodes.has('RESOURCE_MISSING'));
});

test('local SVG fragments and direct-string image-set resources pass containment checks', () => {
  const html = validHtml().replace('</head>', '<style>.probe{background-image:image-set("assets/core.css" 1x)}</style></head>')
    .replace('<h1>Valid deck</h1>', '<h1>Valid deck</h1><div class="probe"></div><svg><use href="assets/core.css#token"></use></svg>');
  const { file } = makeDeck({ html });
  const report = validate(file);
  assert.equal(report.valid, true, JSON.stringify(report.issues, null, 2));
});

test('formal profiles require a delivery manifest', () => {
  const { file } = makeDeck({ manifest: false });
  assert.ok(codes(validate(file)).has('DELIVERY_MANIFEST_MISSING'));
});

test('target attributes must agree and preserve the declared aspect ratio', () => {
  const html = validHtml()
    .replace('data-deck-width="1920" data-deck-height="1080" data-target-browser="chromium" data-target-os="current"><div id="deck">', 'data-deck-width="100" data-deck-height="1080" data-target-browser="" data-target-os="current"><div id="deck">');
  const { file } = makeDeck({ html });
  const resultCodes = codes(validate(file));
  assert.ok(resultCodes.has('TARGET_WIDTH_MISMATCH'));
  assert.ok(resultCodes.has('TARGET_WIDTH_INVALID'));
  assert.ok(resultCodes.has('TARGET_BROWSER_MISSING'));
  assert.ok(resultCodes.has('TARGET_RATIO_MISMATCH'));
});

test('unsupported target browser and OS are rejected before rendering', () => {
  const html = validHtml().replaceAll('data-target-browser="chromium"', 'data-target-browser="safari"')
    .replaceAll('data-target-os="current"', 'data-target-os="plan9"');
  const { file } = makeDeck({ html });
  const resultCodes = codes(validate(file));
  assert.ok(resultCodes.has('TARGET_BROWSER_UNSUPPORTED'));
  assert.ok(resultCodes.has('TARGET_OS_UNSUPPORTED'));
});

test('high-assurance profile enforces offline and required evidence policies', () => {
  const html = validHtml().replaceAll('standard-client', 'high-assurance');
  const { file } = makeDeck({ html });
  assert.ok(codes(validate(file)).has('HIGH_ASSURANCE_POLICY'));
});

test('delivery manifest detects post-build tampering', async () => {
  const root = mkdtempSync(join(tmpdir(), 'web-slide-manifest-'));
  await initDeck({ projectDir: root, mode: 'bundle', theme: 'swiss', skillRoot });
  const built = await buildDeck({ projectDir: root, mode: 'bundle', skillRoot });
  const index = join(built.outputDir, 'index.html');
  writeFileSync(index, readFileSync(index, 'utf8').replace('</title>', ' changed</title>'));
  assert.ok(codes(validate(index)).has('DELIVERY_MANIFEST_MISMATCH'));
});

test('manifest runtime mode, slide order, and external dependency ledger are verified', () => {
  const { root, file } = makeDeck();
  const manifestPath = join(root, 'delivery-manifest.json');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  manifest.mode = 'standalone';
  manifest.slides = [{ index: 2, id: 'other' }];
  manifest.externalDependencies = 1;
  manifest.externalDependencyUrls = ['https://example.com/runtime.js'];
  writeFileSync(manifestPath, JSON.stringify(manifest));
  const resultCodes = codes(validate(file));
  assert.ok(resultCodes.has('DELIVERY_MANIFEST_MODE_MISMATCH'));
  assert.ok(resultCodes.has('DELIVERY_MANIFEST_SLIDES_MISMATCH'));
  assert.ok(resultCodes.has('DELIVERY_MANIFEST_EXTERNAL_MISMATCH'));
});

test('manifest external dependency count uses unique URLs, not reference occurrences', () => {
  const remoteUrl = 'https://example.com/shared.png';
  const html = validHtml().replace(
    '<h1>Valid deck</h1>',
    `<h1>Valid deck</h1><img src="${remoteUrl}" alt="Shared"><img src="${remoteUrl}" alt="Shared again">`,
  );
  const { root, file } = makeDeck({ html });
  const manifestPath = join(root, 'delivery-manifest.json');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  manifest.externalDependencies = 1;
  manifest.externalDependencyUrls = [remoteUrl];
  writeFileSync(manifestPath, JSON.stringify(manifest));
  const report = validate(file);
  assert.equal(report.valid, true, JSON.stringify(report.issues, null, 2));
  assert.equal(report.resources.remote.length, 2);
  assert.ok(!codes(report).has('DELIVERY_MANIFEST_EXTERNAL_MISMATCH'));
});

test('static report carries current artifact hashes and rendered slide contract', () => {
  const { root, file } = makeDeck();
  const first = validate(file);
  const inputDigest = createHash('sha256').update(readFileSync(file)).digest('hex');
  const manifestDigest = createHash('sha256').update(readFileSync(join(root, 'delivery-manifest.json'))).digest('hex');
  assert.equal(first.inputSha256, inputDigest);
  assert.equal(first.manifestSha256, manifestDigest);
  assert.deepEqual(first.slideIds, ['intro']);
  assert.deepEqual(first.layouts, ['hero']);
  writeFileSync(file, readFileSync(file, 'utf8').replace('<title>Deck</title>', '<title>Changed</title>'));
  const second = validate(file);
  assert.notEqual(second.inputSha256, first.inputSha256);
  assert.ok(codes(second).has('DELIVERY_MANIFEST_MISMATCH'));
});

test('only approved builder inline scripts are trusted', () => {
  const html = validHtml().replace('</body>', '<script data-web-slide-asset="assets/evil.js">alert(1)</script></body>');
  const { file } = makeDeck({ html });
  const resultCodes = codes(validate(file));
  assert.ok(resultCodes.has('INLINE_ASSET_MARKER_INVALID'));
  assert.ok(resultCodes.has('INLINE_EXECUTABLE_SCRIPT'));
});

test('known markers cannot authenticate forged content; importmap and alternate src are blocked', () => {
  const html = validHtml()
    .replace('</body>', '<script data-web-slide-asset="assets/slide-engine.js">alert(1)</script><script type="importmap">{"imports":{}}</script><script src="data:text/javascript,alert(1)"></script><script src="./assets/evil.js"></script></body>');
  const { root, file } = makeDeck({ html });
  writeFileSync(join(root, 'assets', 'evil.js'), 'alert(1)');
  const resultCodes = codes(validate(file));
  assert.ok(resultCodes.has('INLINE_ASSET_CONTENT_MISMATCH'));
  assert.ok(resultCodes.has('INLINE_EXECUTABLE_SCRIPT'));
  assert.ok(resultCodes.has('SCRIPT_SRC_NOT_ALLOWED'));
});

test('layout class must be on the direct canvas-card', () => {
  const slides = '<section class="slide" data-slide-id="nested" data-layout="hero" data-evidence="none"><div class="canvas-card"><div class="layout-hero"><h1>Nested</h1></div></div></section>';
  const { file } = makeDeck({ html: validHtml(slides) });
  assert.ok(codes(validate(file)).has('LAYOUT_CLASS_MISSING'));
});

test('malformed HTML and unnamed buttons are rejected', () => {
  const html = validHtml().replace('<h1>Valid deck</h1></div>', '<h1>Valid deck</h1><button></button>');
  const { file } = makeDeck({ html });
  const resultCodes = codes(validate(file));
  assert.ok([...resultCodes].some((code) => code.startsWith('HTML_')));
  assert.ok(resultCodes.has('BUTTON_NAME_MISSING'));
});

test('CLI writes the canonical report and uses 0/1/2 exit codes', () => {
  const cli = join(skillRoot, 'scripts', 'qa-deck.mjs');
  const valid = makeDeck();
  assert.equal(spawnSync(process.execPath, [cli, valid.file]).status, 0);
  const persisted = JSON.parse(readFileSync(join(valid.root, 'qa-report', 'qa-report.json'), 'utf8'));
  assert.equal(persisted.valid, true);
  assert.match(persisted.inputSha256, /^[a-f0-9]{64}$/);
  assert.match(persisted.manifestSha256, /^[a-f0-9]{64}$/);
  assert.deepEqual(persisted.slideIds, ['intro']);
  assert.deepEqual(persisted.layouts, ['hero']);

  const invalid = makeDeck({ html: validHtml().replace('data-slide-id="intro"', '') });
  assert.equal(spawnSync(process.execPath, [cli, invalid.file]).status, 1);
  assert.equal(spawnSync(process.execPath, [cli]).status, 2);
});

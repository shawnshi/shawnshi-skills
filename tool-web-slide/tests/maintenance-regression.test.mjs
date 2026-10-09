import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import test from 'node:test';
import { updateResourceManifest } from '../scripts/update-manifest.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const engine = await readFile(join(root, 'assets/slide-engine.js'), 'utf8');
const css = await readFile(join(root, 'assets/winning.css'), 'utf8');

function block(selector) {
  const blocks = [];
  let offset = 0;
  while (true) {
    const start = css.indexOf(`${selector} {`, offset);
    if (start === -1) break;
    const end = css.indexOf('}', start) + 1;
    blocks.push(css.slice(start, end));
    offset = end;
  }
  assert.ok(blocks.length, selector);
  return blocks.join('\n');
}
function tokens(text) {
  return Object.fromEntries([...text.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map(match => [match[1], match[2].trim()]));
}
function color(value, values) {
  const match = /^var\((--[\w-]+)\)$/.exec(value.trim());
  return match ? color(values[match[1]], values) : value.trim();
}
function luminance(hex) {
  const channels = hex.slice(1).match(/../g).map(channel => parseInt(channel, 16) / 255);
  return channels.map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4)
    .reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
}
function ratio(a, b) {
  const x = luminance(a), y = luminance(b);
  return (Math.max(x, y) + .05) / (Math.min(x, y) + .05);
}

test('Winning title, emphasis, body and sources meet normal-text contrast across supported surfaces', () => {
  const theme = 'body[data-theme="winning-clinical"]';
  for (const mode of ['normal', 'dark', 'accent']) {
    const values = { ...tokens(block(theme)) };
    if (mode !== 'normal') Object.assign(values, tokens(block(`${theme} .slide:is(.dark,.accent)`)));
    if (mode === 'accent') Object.assign(values, tokens(block(`${theme} .slide.accent`)));
    const surface = block(`${theme} .slide${mode === 'normal' ? '' : `.${mode}`}`);
    const background = color(/background:([^;]+);/.exec(surface)[1], values);
    for (const component of ['.c-action-title', '.c-action-title strong', '.c-pillar-body', '.c-footnote', '.c-footnote strong']) {
      const foreground = color(/color:([^;]+);/.exec(block(component))[1], values);
      assert.ok(ratio(foreground, background) >= 4.5, `${mode} ${component}: ${foreground}/${background}`);
    }
  }
});

test('Winning comparisons do not use red as decoration and radar never invents score geometry', () => {
  assert.doesNotMatch(block('.c-matrix-col-bad'), /--danger|#fdf0ef/);
  assert.doesNotMatch(block('.emr-level5-radar::before'), /polygon|clip-path/);
  assert.match(block('.emr-level5-radar::before'), /非评分/);
});

test('inactive slides are inert except in reading mode; overview isolates every slide', () => {
  const source = engine.slice(engine.indexOf('function syncSlideAccess(){'), engine.indexOf('function editableTarget('));
  let reading = false;
  const slides = Array.from({ length: 3 }, () => ({ attributes: {}, setAttribute(key, value) { this.attributes[key] = value; }, removeAttribute(key) { delete this.attributes[key]; } }));
  const context = { slides, idx: 1, overviewOn: false, document: { body: { classList: { contains: () => reading } } } };
  vm.createContext(context);
  vm.runInContext(source, context);
  context.syncSlideAccess();
  assert.deepEqual(slides.map(slide => slide.inert), [true, false, true]);
  assert.equal(slides[0].attributes['aria-hidden'], 'true');
  reading = true;
  context.syncSlideAccess();
  assert.ok(slides.every(slide => !slide.inert && !('aria-hidden' in slide.attributes)));
  context.overviewOn = true;
  context.syncSlideAccess();
  assert.ok(slides.every(slide => slide.inert));
});

test('actual key handler preserves save shortcuts, text editing and native button activation', () => {
  class Element {
    constructor(editable = false, control = false) { this.editable = editable; this.control = control; }
    closest(selector) { return (selector.startsWith('input') ? this.editable : this.control) ? this : null; }
  }
  let handler, speaker = 0;
  const advanced = [];
  const context = {
    Element, role: null, idx: 0, total: 3, overviewOn: false, capability: true, deckId: 'test',
    window: { open: () => { speaker++; return {}; } }, deckUrl: () => 'about:blank',
    publishState() {}, setTimeout() {}, toggleOverview() {}, go: index => advanced.push(index),
    addEventListener: (_name, callback) => { handler = callback; },
    document: { activeElement: null }, console
  };
  const editable = engine.slice(engine.indexOf('function editableTarget('), engine.indexOf('function go('));
  const start = engine.indexOf("addEventListener('keydown',e=>{");
  const keys = engine.slice(start, engine.indexOf('let wheelTO=', start));
  vm.runInNewContext(editable + keys, context);
  const send = (key, options = {}) => {
    let prevented = false;
    handler({ key, target: new Element(), preventDefault() { prevented = true; }, ...options });
    return prevented;
  };
  assert.equal(send('s', { ctrlKey: true }), false);
  assert.equal(send('s', { metaKey: true }), false);
  assert.equal(send('s', { target: new Element(true) }), false);
  assert.equal(send(' ', { target: new Element(false, true) }), false);
  assert.equal(speaker, 0);
  assert.equal(advanced.length, 0);
  assert.equal(send('s'), true);
  assert.equal(speaker, 1);
  assert.equal(send('ArrowRight'), true);
  assert.deepEqual(advanced, [1]);
});

test('resource manifest ignores materializer-owned metadata and ordering, not content changes', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'web-slide-manifest-'));
  try {
    await writeFile(join(directory, 'SKILL.md'), '---\nname: test\ndescription: test\n---\nTest\n');
    await updateResourceManifest({ skillRoot: directory });
    const path = join(directory, 'resource-manifest.json');
    const manifest = JSON.parse(await readFile(path, 'utf8'));
    manifest.top_level_files.reverse();
    manifest.top_level_file_hashes.reverse();
    manifest.resource_file_hashes.push({ path: 'agents/openai.yaml', sha256: 'a'.repeat(64) });
    manifest.top_level_directories = ['agents'];
    manifest.resource_directories = [{ name: 'agents', file_count: 1 }];
    await writeFile(path, JSON.stringify(manifest));
    assert.equal((await updateResourceManifest({ skillRoot: directory, check: true })).ok, true);
    await writeFile(join(directory, 'SKILL.md'), 'Changed content\n');
    assert.equal((await updateResourceManifest({ skillRoot: directory, check: true })).ok, false);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

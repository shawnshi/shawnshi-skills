import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as crypto from 'node:crypto';
import * as path from 'node:path';
import vm from 'node:vm';
import { mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import test from 'node:test';
import { inspectQaArtifacts, publishQaArtifacts } from '../scripts/lib/qa-artifacts.mjs';
import { resolveChromiumLaunchArgs } from '../scripts/lib/browser-runtime.mjs';
import { exportPdf } from '../scripts/export-pdf.mjs';

async function fixture(run) {
  const root = await mkdtemp(join(tmpdir(), 'web-slide-artifact-'));
  try { await run(root); } finally { await rm(root, { recursive: true, force: true }); }
}

test('QA publication replaces only unchanged owned artifacts', async () => fixture(async root => {
  const path = join(root, 'qa-report', 'report.json');
  publishQaArtifacts(root, new Map([[path, 'first']]));
  publishQaArtifacts(root, new Map([[path, 'second']]));
  assert.equal(await readFile(path, 'utf8'), 'second');
  await writeFile(path, 'user edit');
  assert.throws(() => publishQaArtifacts(root, new Map([[path, 'third']])), /user-modified/);
  assert.equal(await readFile(path, 'utf8'), 'user edit');
}));

test('an unmanaged collision prevents the entire QA batch from being published', async () => fixture(async root => {
  const owned = join(root, 'report.json');
  const unmanaged = join(root, 'slide-001.png');
  publishQaArtifacts(root, new Map([[owned, 'original']]));
  await writeFile(unmanaged, 'user screenshot');
  assert.throws(() => publishQaArtifacts(root, new Map([[owned, 'replacement'], [unmanaged, 'generated']])), /unmanaged/);
  assert.equal(await readFile(owned, 'utf8'), 'original');
  assert.equal(await readFile(unmanaged, 'utf8'), 'user screenshot');
}));

test('QA publication rejects outside paths, ledger replacement and symlinks', async () => fixture(async root => {
  assert.throws(() => publishQaArtifacts(root, new Map([[join(root, '..', 'escape.json'), '{}']])), /delivery root/);
  assert.throws(() => inspectQaArtifacts(root, [join(root, '.web-slide-qa-manifest.json')]), /ownership manifest/);
  const path = join(root, 'original.json');
  await writeFile(path, 'user data');
  const link = join(root, 'linked.json');
  await symlink(path, link);
  assert.throws(() => publishQaArtifacts(root, new Map([[link, 'replacement']])), /non-symlink/);
  assert.equal(await readFile(path, 'utf8'), 'user data');
}));

test('PDF refuses an unmanaged existing PDF before attempting browser launch', async () => fixture(async root => {
  const html = join(root, 'index.html');
  const pdf = join(root, 'deck.pdf');
  await writeFile(html, '<main id="deck"></main>');
  await writeFile(pdf, 'existing user PDF');
  await assert.rejects(exportPdf({ htmlPath: html, outputPath: pdf }), /unmanaged/);
  assert.equal(await readFile(pdf, 'utf8'), 'existing user PDF');
}));

test('explicit non-root no-sandbox opt-in is reported accurately', () => {
  assert.equal(resolveChromiumLaunchArgs({ isRoot: false, args: ['--no-sandbox'], allowNoSandbox: true }).noSandbox, true);
  assert.equal(resolveChromiumLaunchArgs({ isRoot: false, allowNoSandbox: false }).noSandbox, false);
});

test('actual Chromium launch passes sandbox=true unless a validated opt-in disables it', async () => {
  const source = await readFile(new URL('../scripts/lib/browser-runtime.mjs', import.meta.url), 'utf8');
  const start = source.indexOf('export async function launchChromium(');
  const code = source.slice(start, source.indexOf('function normalizedNetworkOrigin(', start)).replace('export async function', 'async function');
  const context = {
    normalizeTargetBrowser: value => value || 'chromium', resolveChromiumLaunchArgs,
    loadPlaywright: async () => ({ api: { chromium: { launch: async options => ({ options }) } }, resolved: 'controlled fixture' }),
    findBrowserExecutable: () => ({ path: 'controlled fixture', browser: 'chromium' }), BrowserRuntimeError: Error
  };
  vm.createContext(context);
  vm.runInContext(code, context);
  const secure = await context.launchChromium({ isRoot: false, allowNoSandbox: false });
  assert.equal(secure.browser.options.chromiumSandbox, true);
  const accepted = await context.launchChromium({ isRoot: false, args: ['--no-sandbox'], allowNoSandbox: true });
  assert.equal(accepted.browser.options.chromiumSandbox, false);
  await assert.rejects(context.launchChromium({ isRoot: true, allowNoSandbox: false }), /Refusing/);
});

test('QA publication restores files and ownership after a mid-commit filesystem failure', async () => fixture(async root => {
  const source = await readFile(new URL('../scripts/lib/qa-artifacts.mjs', import.meta.url), 'utf8');
  const first = join(root, 'first.json'), second = join(root, 'second.json');
  let inject = false;
  const context = {
    ...fs, ...crypto, ...path, Buffer,
    renameSync: (from, to) => {
      if (inject && to === second) { inject = false; throw new Error('forced rename failure'); }
      return fs.renameSync(from, to);
    }
  };
  vm.createContext(context);
  vm.runInContext(source.replace(/^import .*;\n/gm, '').replace(/^export /gm, ''), context);
  context.publishQaArtifacts(root, new Map([[first, 'original first'], [second, 'original second']]));
  const ledger = await readFile(join(root, '.web-slide-qa-manifest.json'), 'utf8');
  inject = true;
  assert.throws(() => context.publishQaArtifacts(root, new Map([[first, 'replacement first'], [second, 'replacement second']])), /forced rename failure/);
  assert.equal(await readFile(first, 'utf8'), 'original first');
  assert.equal(await readFile(second, 'utf8'), 'original second');
  assert.equal(await readFile(join(root, '.web-slide-qa-manifest.json'), 'utf8'), ledger);
}));

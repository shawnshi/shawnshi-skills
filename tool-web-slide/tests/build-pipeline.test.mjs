import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, rm, stat, symlink, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  buildDeck,
  commitStagedOutputs,
  DeckBuildError,
  sha256,
} from '../scripts/build-deck.mjs';
import { initDeck } from '../scripts/init-deck.mjs';
import { createResourceManifest } from '../scripts/update-manifest.mjs';
import {
  DELIVERY_PROFILES,
  REQUIRED_GATES,
  standaloneEngineSource,
  TARGET_BROWSERS,
  TARGET_OSES,
} from '../scripts/lib/delivery-contract.mjs';

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const REAL_SKILL_ROOT = path.resolve(TEST_DIR, '..');

async function write(root, relative, contents) {
  const target = path.join(root, ...relative.split('/'));
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, contents, 'utf8');
  return target;
}

async function fakeSkillRoot(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'web-slide-skill-'));
  t.after(async () => {
    const { rm } = await import('node:fs/promises');
    await rm(root, { recursive: true, force: true });
  });
  const skeleton = await readFile(path.join(REAL_SKILL_ROOT, 'starter-components', 'index-skeleton.html'), 'utf8');
  await write(root, 'starter-components/index-skeleton.html', skeleton);
  await write(root, 'references/components.json', `${JSON.stringify({
    schemaVersion: '1.0.0',
    themes: {
      swiss: {
        baseStylesheet: 'assets/core.css',
        stylesheet: 'assets/swiss.css',
        classes: [],
      },
      clinical: {
        baseStylesheet: 'assets/core.css',
        stylesheet: 'assets/clinical.css',
        classes: [],
      },
    },
    runtimeClasses: [],
  }, null, 2)}\n`);
  await write(root, 'assets/core.css', ':root{--paper:#fff} .slide{background:var(--paper)}\n');
  await write(root, 'assets/swiss.css', 'body[data-theme="swiss"]{--accent:#00f}\n');
  await write(root, 'assets/clinical.css', 'body[data-theme="clinical"]{--accent:#005eb8}\n');
  await write(root, 'assets/icon-runtime.js', 'window.lucide={createIcons(){}};\n');
  await write(root, 'assets/slide-engine.js', "let motion; const staticRuntime=!!window.__WEB_SLIDE_STANDALONE__; if(!staticRuntime){ const localMotionModule='./motion.min.js'; try { motion=await import(localMotionModule); } catch {} } if(!motion){ window.__fallback=true; } window.__engineLoaded=true;\n");
  await write(root, 'assets/motion.min.js', 'export const animate=()=>{};\n');
  await write(root, 'package.json', '{"name":"tool-web-slide","version":"9.0.0","type":"module"}\n');
  return root;
}

async function projectRoot(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'web-slide-project-'));
  t.after(async () => {
    const { rm } = await import('node:fs/promises');
    await rm(root, { recursive: true, force: true });
  });
  return root;
}

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, 'utf8'));
}

test('initializer creates the deterministic project contract without CDNs', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  const result = await initDeck({
    projectDir: project,
    title: '测试演示',
    theme: 'swiss',
    aspect: '16:10',
    mode: 'bundle',
    skillRoot,
  });

  assert.deepEqual(result.changed, ['deck.config.json', 'src/slides/001-opening.html']);
  const config = await readJson(path.join(project, 'deck.config.json'));
  assert.equal(config.schemaVersion, '1.0.0');
  assert.equal(config.aspect, '16:10');
  assert.equal(config.offlineRequired, true);
  assert.equal(config.evidencePolicy, 'advisory');
  assert.equal(config.deliveryProfile, 'standard-client');
  assert.deepEqual(config.target, { browser: 'chromium', os: 'current', viewport: { width: 1920, height: 1200 } });
  const slide = await readFile(path.join(project, 'src/slides/001-opening.html'), 'utf8');
  assert.match(slide, /data-slide-id="opening"/);
  assert.match(slide, /data-layout="hero"/);
  assert.match(slide, /data-evidence="none"/);
  assert.match(slide, /class="canvas-card layout-hero"/);
  assert.doesNotMatch(slide, /data-animate=/);
  assert.doesNotMatch(slide, /https?:\/\//);
  const skeleton = await readFile(path.join(skillRoot, 'starter-components/index-skeleton.html'), 'utf8');
  assert.match(skeleton, /<meta name="referrer" content="no-referrer">/);

  await assert.rejects(
    initDeck({ projectDir: project, skillRoot }),
    (error) => error instanceof DeckBuildError && /未做覆盖/.test(error.message),
  );
});

test('bundle build reads theme registry, copies canonical assets, and preserves unchanged mtimes', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'Bundle', theme: 'clinical', skillRoot });
  const configPath = path.join(project, 'deck.config.json');
  const config = await readJson(configPath);
  config.designSystem.stylesheet = 'src/design-system.css';
  await write(project, 'src/media/local.woff2', 'bundle-font');
  await write(project, 'src/slides/media/chart.png', 'bundle-image');
  await write(project, 'src/design-system.css', '@font-face{font-family:Local;src:url("./media/local.woff2")} .project-token{color:var(--accent)}\n');
  const openingPath = path.join(project, 'src/slides/001-opening.html');
  const opening = await readFile(openingPath, 'utf8');
  await writeFile(openingPath, opening.replace('</section>', '<img alt="chart" src="./media/chart.png"></section>'));
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);

  const first = await buildDeck({ projectDir: project, skillRoot });
  assert.equal(first.slideCount, 1);
  assert.equal(first.manifest.externalDependencies, 0);
  assert.deepEqual(first.manifest.target, { browser: 'chromium', os: 'current', viewport: { width: 1920, height: 1080 } });
  assert.equal(first.manifest.deliveryProfile, 'standard-client');
  assert.deepEqual(first.manifest.requiredGates, { static: true, visual: 'layouts', pdf: 'optional' });
  const deliveredPaths = first.manifest.files.map((file) => file.path);
  for (const expected of ['assets/clinical.css', 'assets/core.css', 'assets/design-system.css', 'assets/icon-runtime.js', 'assets/slide-engine.js', 'index.html']) {
    assert.ok(deliveredPaths.includes(expected), `missing ${expected}`);
  }
  assert.equal(deliveredPaths.filter((file) => file.startsWith('assets/media/')).length, 2);
  assert.equal(first.manifest.copiedAssets.length, 2);
  const indexPath = path.join(project, 'dist', 'index.html');
  const html = await readFile(indexPath, 'utf8');
  assert.match(html, /data-theme="clinical"/);
  assert.match(html, /data-aspect="16:9"/);
  assert.match(html, /data-evidence-policy="advisory"/);
  assert.match(html, /data-deck-width="1920" data-deck-height="1080"/);
  assert.match(html, /data-delivery-profile="standard-client"/);
  assert.ok(html.indexOf('./assets/design-system.css') < html.indexOf('--slide-aspect:16/9'));
  assert.match(html, /\.\/assets\/design-system\.css/);
  assert.match(html, /src="\.\/assets\/media\/[a-f0-9]{64}\.png"/);
  assert.match(html, /data-slide-id="opening"/);
  assert.doesNotMatch(html, /fonts\.googleapis|unpkg|jsdelivr/);
  assert.equal(
    await readFile(path.join(project, 'dist', 'assets', 'clinical.css'), 'utf8'),
    await readFile(path.join(skillRoot, 'assets', 'clinical.css'), 'utf8'),
  );
  const designCss = await readFile(path.join(project, 'dist', 'assets', 'design-system.css'), 'utf8');
  assert.match(designCss, /url\("\.\/media\/[a-f0-9]{64}\.woff2"\)/);

  const before = (await stat(indexPath)).mtimeMs;
  const second = await buildDeck({ projectDir: project, skillRoot });
  const after = (await stat(indexPath)).mtimeMs;
  assert.deepEqual(second.changed, []);
  assert.equal(after, before);
});

test('standalone build produces one self-contained runtime file plus its delivery metadata', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'Standalone', theme: 'swiss', mode: 'standalone', skillRoot });
  await write(project, 'src/slides/media/pixel.png', 'fake-png-bytes');
  await write(project, 'src/fonts/local.woff2', 'fake-font-bytes');
  const slidePath = path.join(project, 'src/slides/001-opening.html');
  const slide = await readFile(slidePath, 'utf8');
  await writeFile(slidePath, slide.replace('</section>', '<img alt="pixel" src="./media/pixel.png"></section>'));
  await write(project, 'src/design-system.css', '@font-face{font-family:Local;src:url("./fonts/local.woff2") format("woff2")}\n');
  const configPath = path.join(project, 'deck.config.json');
  const config = await readJson(configPath);
  config.designSystem.stylesheet = 'src/design-system.css';
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);

  const result = await buildDeck({ projectDir: project, skillRoot });
  assert.deepEqual(result.manifest.files.map((file) => file.path), ['index.html']);
  assert.equal(result.manifest.embeddedAssets.length, 2);
  const html = await readFile(path.join(project, 'dist', 'index.html'), 'utf8');
  assert.match(html, /data-web-slide-asset="assets\/core\.css"/);
  assert.match(html, /data-web-slide-asset="assets\/icon-runtime\.js"/);
  assert.match(html, /data-web-slide-asset="assets\/slide-engine\.js"/);
  assert.match(html, /__WEB_SLIDE_STANDALONE__/);
  assert.ok(html.indexOf('data-web-slide-asset="assets/swiss.css"') < html.indexOf('--slide-aspect:16/9'));
  assert.doesNotMatch(html, /\bimport\b/);
  assert.doesNotMatch(html, /\.\/motion\.min\.js/);
  assert.match(html, /src="data:image\/png;base64,/);
  assert.match(html, /url\("data:font\/woff2;base64,/);
  assert.doesNotMatch(html, /(?:src|href)="\.\/assets\//);
  assert.doesNotMatch(html, /https?:\/\/(?:unpkg|cdn\.jsdelivr|fonts\.googleapis)/);
});

test('missing slide IDs are derived from semantic filenames and remain stable across no-op builds', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'IDs', theme: 'swiss', skillRoot });
  await write(project, 'src/slides/002-roadmap.html', '<section class="slide" data-layout="pathway" data-evidence="source"><p>Roadmap</p></section>\n');
  const configPath = path.join(project, 'deck.config.json');
  const config = await readJson(configPath);
  config.slides.order.push('002-roadmap.html');
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);

  const first = await buildDeck({ projectDir: project, skillRoot });
  const second = await buildDeck({ projectDir: project, skillRoot });
  assert.deepEqual(first.generatedIds, [{ file: 'src/slides/002-roadmap.html', id: 'roadmap' }]);
  assert.deepEqual(second.generatedIds, first.generatedIds);
  const html = await readFile(path.join(project, 'dist', 'index.html'), 'utf8');
  assert.match(html, /id="slide-roadmap" data-slide-id="roadmap"|data-slide-id="roadmap" id="slide-roadmap"/);
});

test('offline builds reject remote runtime media but allow ordinary citation links', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'Offline', theme: 'swiss', skillRoot });
  const slidePath = path.join(project, 'src/slides/001-opening.html');
  await writeFile(slidePath, '<section class="slide" data-slide-id="opening" data-layout="hero" data-evidence="source"><a href="https://example.org/report">source</a><img src="https://example.org/chart.png"></section>\n');
  await assert.rejects(
    buildDeck({ projectDir: project, skillRoot }),
    (error) => error instanceof DeckBuildError && /offlineRequired=true/.test(error.message),
  );

  await writeFile(slidePath, '<section class="slide" data-slide-id="opening" data-layout="hero" data-evidence="source"><img src="http&#58;//example.org/chart.png"></section>\n');
  await assert.rejects(buildDeck({ projectDir: project, skillRoot }), /offlineRequired=true/);

  await writeFile(slidePath, '<section class="slide" data-slide-id="opening" data-layout="hero" data-evidence="source"><a href="https://example.org/report">source</a></section>\n');
  const result = await buildDeck({ projectDir: project, skillRoot });
  assert.equal(result.manifest.externalDependencies, 0);
});

test('builder rejects ambiguous page ordering and duplicate stable IDs', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'Validation', theme: 'swiss', skillRoot });
  await write(project, 'src/slides/002-copy.html', '<section class="slide" data-slide-id="opening" data-layout="focus" data-evidence="none"></section>\n');
  await assert.rejects(
    buildDeck({ projectDir: project, skillRoot }),
    (error) => error instanceof DeckBuildError && /未列出/.test(error.message),
  );
  const configPath = path.join(project, 'deck.config.json');
  const config = await readJson(configPath);
  config.slides.order.push('002-copy.html');
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);
  await assert.rejects(
    buildDeck({ projectDir: project, skillRoot }),
    (error) => error instanceof DeckBuildError && /重复 data-slide-id/.test(error.message),
  );
});

test('slide fragments allow nested semantic sections while enforcing one top-level slide', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'Nested', theme: 'swiss', skillRoot });
  const slidePath = path.join(project, 'src/slides/001-opening.html');
  await writeFile(slidePath, '<section class="slide" data-slide-id="opening" data-layout="architecture" data-evidence="none"><section class="c-layer"><p>应用层</p></section><section class="c-layer"><p>数据层</p></section></section>\n');
  const result = await buildDeck({ projectDir: project, skillRoot });
  assert.equal(result.slideCount, 1);
  const html = await readFile(path.join(project, 'dist/index.html'), 'utf8');
  assert.match(html, /class="c-layer"/);
});

test('arbitrary fixed aspect ratios drive the core slide variables', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'Aspect', theme: 'swiss', aspect: '3:2', skillRoot });
  let result = await buildDeck({ projectDir: project, skillRoot });
  let html = await readFile(path.join(project, 'dist/index.html'), 'utf8');
  assert.equal(result.aspect, '3:2');
  assert.match(html, /--slide-aspect:3\/2;--slide-width:1920px;--slide-height:1280px/);

  const configPath = path.join(project, 'deck.config.json');
  const config = await readJson(configPath);
  config.aspect = '4:3';
  config.target.viewport = { width: 1920, height: 1440 };
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);
  result = await buildDeck({ projectDir: project, skillRoot });
  html = await readFile(path.join(project, 'dist/index.html'), 'utf8');
  assert.equal(result.aspect, '4:3');
  assert.match(html, /--slide-aspect:4\/3;--slide-width:1920px;--slide-height:1440px/);
  assert.ok(html.indexOf('./assets/swiss.css') < html.indexOf('--slide-aspect:4/3'));
});

test('required evidence initialization is explicitly blocked until a real source is supplied', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  const result = await initDeck({
    projectDir: project,
    title: 'Evidence',
    theme: 'swiss',
    evidencePolicy: 'required',
    skillRoot,
  });
  assert.equal(result.readyForQa, false);
  assert.equal(result.blockingActions.length, 1);
  const slide = await readFile(path.join(project, 'src/slides/001-opening.html'), 'utf8');
  assert.match(slide, /data-evidence="required"/);
  assert.match(slide, /class="source-note" data-source="" data-source-date=""/);
  assert.match(slide, /待填写/);
});

test('high-assurance profile enforces evidence and offline gates', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  const initialized = await initDeck({
    projectDir: project,
    title: 'High assurance',
    theme: 'swiss',
    profile: 'high-assurance',
    evidencePolicy: 'advisory',
    skillRoot,
  });
  assert.equal(initialized.readyForQa, false);
  assert.equal(initialized.config.evidencePolicy, 'required');
  assert.equal(initialized.config.offlineRequired, true);
  const built = await buildDeck({ projectDir: project, skillRoot });
  assert.equal(built.manifest.deliveryProfile, 'high-assurance');
  assert.deepEqual(built.manifest.requiredGates, { static: true, visual: 'all', pdf: 'required' });
  const html = await readFile(path.join(project, 'dist/index.html'), 'utf8');
  assert.match(html, /data-delivery-profile="high-assurance"/);

  const configPath = path.join(project, 'deck.config.json');
  const config = await readJson(configPath);
  config.offlineRequired = false;
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);
  await assert.rejects(buildDeck({ projectDir: project, skillRoot }), /high-assurance 强制/);
});

test('target viewport is bounded and must match the configured aspect ratio', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'Target', theme: 'swiss', skillRoot });
  const configPath = path.join(project, 'deck.config.json');
  const config = await readJson(configPath);
  config.target.viewport = { width: 100, height: 100 };
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);
  await assert.rejects(buildDeck({ projectDir: project, skillRoot }), /320–7680/);
  config.target.viewport = { width: 1920, height: 1200 };
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);
  await assert.rejects(buildDeck({ projectDir: project, skillRoot }), /与 aspect 16:9 不一致/);
});

test('slide fragments reject executable markup before skeleton assembly', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const cases = [
    ['<script>alert(1)</script>', /禁止 <script>/],
    ['<button onclick="alert(1)">x</button>', /禁止 on\*/],
    ['<a href="javascript:alert(1)">x</a>', /禁止可执行 URL scheme/],
    ['<a href="javascript&colon;alert(1)">x</a>', /禁止可执行 URL scheme/],
    ['<a href="&#106;&#97;&#118;&#97;&#115;&#99;&#114;&#105;&#112;&#116;&#58;alert(1)">x</a>', /禁止可执行 URL scheme/],
    ['<iframe srcdoc="<p>x</p>"></iframe>', /禁止 <iframe>|srcdoc/],
    ['<base href="https://example.org/">', /禁止 <base>/],
  ];
  for (const [payload, expected] of cases) {
    const project = await projectRoot(t);
    await initDeck({ projectDir: project, title: 'Unsafe', theme: 'swiss', skillRoot });
    await writeFile(
      path.join(project, 'src/slides/001-opening.html'),
      `<section class="slide" data-slide-id="opening" data-layout="hero" data-evidence="none"><div class="canvas-card layout-hero"><h1>Unsafe</h1>${payload}</div></section>\n`,
    );
    await assert.rejects(buildDeck({ projectDir: project, skillRoot }), expected);
  }
});

test('realpath containment rejects input symlink read escapes', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  const outside = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'Symlink input', theme: 'swiss', skillRoot });
  const outsideSlide = await write(
    outside,
    'outside.html',
    '<section class="slide" data-slide-id="outside" data-layout="hero" data-evidence="none"><div class="canvas-card layout-hero"><h1>Outside</h1></div></section>\n',
  );
  const slidePath = path.join(project, 'src/slides/001-opening.html');
  await rm(slidePath);
  await symlink(outsideSlide, slidePath);
  await assert.rejects(buildDeck({ projectDir: project, skillRoot }), /符号链接逃逸|真实路径位于项目之外/);
});

test('realpath containment rejects media symlink reads and output symlink writes', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const outside = await projectRoot(t);

  const mediaProject = await projectRoot(t);
  await initDeck({ projectDir: mediaProject, title: 'Media escape', theme: 'swiss', mode: 'standalone', skillRoot });
  const secret = await write(outside, 'secret.png', 'secret');
  await symlink(secret, path.join(mediaProject, 'src/slides/secret.png'));
  const mediaSlide = path.join(mediaProject, 'src/slides/001-opening.html');
  const source = await readFile(mediaSlide, 'utf8');
  await writeFile(mediaSlide, source.replace('</section>', '<img alt="secret" src="./secret.png"></section>'));
  await assert.rejects(buildDeck({ projectDir: mediaProject, skillRoot }), /符号链接逃逸/);

  const outputProject = await projectRoot(t);
  await initDeck({ projectDir: outputProject, title: 'Output escape', theme: 'swiss', skillRoot });
  await symlink(outside, path.join(outputProject, 'dist'));
  await assert.rejects(buildDeck({ projectDir: outputProject, skillRoot }), /output\.dir.*符号链接逃逸|真实路径不安全/);
  assert.equal(await readFile(path.join(outside, 'index.html'), 'utf8').catch(() => null), null);
});

test('output directory cannot overlap slide or design-system source directories', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'Overlap', theme: 'swiss', skillRoot });
  const configPath = path.join(project, 'deck.config.json');
  const config = await readJson(configPath);
  config.output.dir = 'src/slides/dist';
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);
  await assert.rejects(buildDeck({ projectDir: project, skillRoot }), /不得与源目录重叠/);
});

test('a project-root design stylesheet does not make a separate dist directory overlap source', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'Root design', theme: 'swiss', skillRoot });
  await write(project, 'design-system.css', '.root-design{color:blue}\n');
  const configPath = path.join(project, 'deck.config.json');
  const config = await readJson(configPath);
  config.designSystem.stylesheet = 'design-system.css';
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);
  const result = await buildDeck({ projectDir: project, skillRoot });
  assert.equal(result.slideCount, 1);
});

test('pruning ignores unhashed entries and refuses an untrusted manifest', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'Prune trust', theme: 'swiss', skillRoot });
  await buildDeck({ projectDir: project, skillRoot });
  const keepPath = await write(project, 'dist/assets/keep.txt', 'keep me');
  const manifestPath = path.join(project, 'dist/delivery-manifest.json');
  let manifest = await readJson(manifestPath);
  manifest.files.push({ path: 'assets/keep.txt' });
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  await buildDeck({ projectDir: project, skillRoot });
  assert.equal(await readFile(keepPath, 'utf8'), 'keep me');

  manifest = await readJson(manifestPath);
  manifest.generator.name = 'forged-builder';
  manifest.files.push({ path: 'assets/keep.txt', sha256: sha256(Buffer.from('keep me')) });
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  await assert.rejects(buildDeck({ projectDir: project, skillRoot }), /不受信任的 delivery-manifest/);
  assert.equal(await readFile(keepPath, 'utf8'), 'keep me');
});

test('blob URLs, entity-obfuscated meta refresh, and anchor ping are rejected', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const cases = [
    ['<img src="blob:https://example.org/id">', /禁止 blob:/],
    ['<img srcset="blob:https://example.org/id 1x">', /禁止 blob:/],
    ['<meta http-equiv=" &#114;&#101;&#102;&#114;&#101;&#115;&#104; " content="0;url=https://example.org">', /禁止 meta refresh/],
    ['<a href="https://example.org" ping="https://tracker.example.org">x</a>', /禁止 ping/],
    ['<map><area href="https://example.org" ping="https://tracker.example.org"></map>', /禁止 ping/],
  ];
  for (const [payload, expected] of cases) {
    const project = await projectRoot(t);
    await initDeck({ projectDir: project, title: 'URL safety', theme: 'swiss', skillRoot });
    await writeFile(
      path.join(project, 'src/slides/001-opening.html'),
      `<section class="slide" data-slide-id="opening" data-layout="hero" data-evidence="none"><div class="canvas-card layout-hero">${payload}</div></section>\n`,
    );
    await assert.rejects(buildDeck({ projectDir: project, skillRoot }), expected);
  }

  const cssProject = await projectRoot(t);
  await initDeck({ projectDir: cssProject, title: 'CSS URL safety', theme: 'swiss', skillRoot });
  await write(cssProject, 'design-system.css', '.unsafe{background:url("blob:https://example.org/id")}\n');
  const configPath = path.join(cssProject, 'deck.config.json');
  const config = await readJson(configPath);
  config.designSystem.stylesheet = 'design-system.css';
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);
  await assert.rejects(buildDeck({ projectDir: cssProject, skillRoot }), /禁止 blob:/);
});

test('srcset tokenization preserves data-URI commas while rewriting local candidates', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'Srcset', theme: 'swiss', mode: 'standalone', skillRoot });
  await write(project, 'src/slides/media/pixel.png', 'local-pixel');
  await writeFile(
    path.join(project, 'src/slides/001-opening.html'),
    '<section class="slide" data-slide-id="opening" data-layout="hero" data-evidence="none"><div class="canvas-card layout-hero"><img alt="responsive" srcset="data:image/png;base64,QUJDRA== 1x, ./media/pixel.png 2x"><img alt="descriptorless" srcset="data:image/png;base64,QUJDRA==, ./media/pixel.png 2x"></div></section>\n',
  );
  await buildDeck({ projectDir: project, skillRoot });
  const html = await readFile(path.join(project, 'dist/index.html'), 'utf8');
  assert.match(
    html,
    /srcset="data:image\/png;base64,QUJDRA== 1x, data:image\/png;base64,[A-Za-z0-9+/=]+ 2x"/,
  );
  assert.match(
    html,
    /srcset="data:image\/png;base64,QUJDRA==, data:image\/png;base64,[A-Za-z0-9+/=]+ 2x"/,
  );
});

test('non-force builds refuse unmanaged and user-modified delivery files', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'Ownership', theme: 'swiss', skillRoot });
  const unmanagedIndex = await write(project, 'dist/index.html', 'user-owned-index\n');
  await assert.rejects(buildDeck({ projectDir: project, skillRoot }), /未由构建器管理的输出：index\.html/);
  assert.equal(await readFile(unmanagedIndex, 'utf8'), 'user-owned-index\n');

  const identicalProject = await projectRoot(t);
  await initDeck({ projectDir: identicalProject, title: 'Identical ownership', theme: 'swiss', skillRoot });
  await write(
    identicalProject,
    'dist/assets/core.css',
    await readFile(path.join(skillRoot, 'assets/core.css')),
  );
  await assert.rejects(
    buildDeck({ projectDir: identicalProject, skillRoot }),
    /未由构建器管理的输出：assets\/core\.css/,
  );

  await buildDeck({ projectDir: project, skillRoot, force: true });
  const corePath = path.join(project, 'dist/assets/core.css');
  await writeFile(corePath, 'user-modified-core\n');
  await assert.rejects(buildDeck({ projectDir: project, skillRoot }), /用户修改过的输出：assets\/core\.css/);
  assert.equal(await readFile(corePath, 'utf8'), 'user-modified-core\n');
  await buildDeck({ projectDir: project, skillRoot, force: true });
  assert.match(await readFile(corePath, 'utf8'), /--paper/);
});

test('staged commit publishes the manifest last and rolls back every prior replacement on failure', async (t) => {
  const output = await projectRoot(t);
  const oldFiles = new Map([
    ['assets/core.css', Buffer.from('old-core')],
    ['index.html', Buffer.from('old-index')],
    ['delivery-manifest.json', Buffer.from('old-manifest')],
  ]);
  const nextFiles = new Map([
    ['assets/core.css', Buffer.from('new-core')],
    ['index.html', Buffer.from('new-index')],
    ['delivery-manifest.json', Buffer.from('new-manifest')],
  ]);
  const currentHashes = new Map();
  for (const [relative, content] of oldFiles) {
    await write(output, relative, content);
    currentHashes.set(relative, sha256(content));
  }
  const order = [];
  await assert.rejects(
    commitStagedOutputs(
      output,
      nextFiles,
      ['delivery-manifest.json', 'index.html', 'assets/core.css'],
      currentHashes,
      {
        beforeRename(relative) {
          order.push(relative);
          if (relative === 'delivery-manifest.json') throw new Error('injected commit failure');
        },
      },
    ),
    /injected commit failure/,
  );
  assert.deepEqual(order, ['index.html', 'assets/core.css', 'delivery-manifest.json']);
  for (const [relative, content] of oldFiles) {
    assert.deepEqual(await readFile(path.join(output, relative)), content);
  }
  const entries = await (await import('node:fs/promises')).readdir(output);
  assert.equal(entries.some((entry) => entry.startsWith('.web-slide-stage-')), false);
});

test('shared delivery enums govern init, build, gates, and CLI help', async (t) => {
  assert.deepEqual(TARGET_BROWSERS, ['chromium', 'chrome', 'edge']);
  assert.deepEqual(TARGET_OSES, ['current', 'linux', 'macos', 'windows']);
  assert.deepEqual(DELIVERY_PROFILES, ['quick-internal', 'standard-client', 'high-assurance']);
  assert.deepEqual(REQUIRED_GATES['high-assurance'], { static: true, visual: 'all', pdf: 'required' });

  const help = spawnSync(process.execPath, [path.join(REAL_SKILL_ROOT, 'scripts/init-deck.mjs'), '--help'], {
    encoding: 'utf8',
  });
  assert.equal(help.status, 0, help.stderr);
  assert.match(help.stdout, /chromium\|chrome\|edge/);
  assert.match(help.stdout, /current\|linux\|macos\|windows/);
  assert.match(help.stdout, /quick-internal\|standard-client\|high-assurance/);
  const buildHelp = spawnSync(process.execPath, [path.join(REAL_SKILL_ROOT, 'scripts/build-deck.mjs'), '--help'], {
    encoding: 'utf8',
  });
  assert.equal(buildHelp.status, 0, buildHelp.stderr);
  assert.match(buildHelp.stdout, /target\.browser\s+chromium\|chrome\|edge/);
  assert.match(buildHelp.stdout, /target\.os\s+current\|linux\|macos\|windows/);

  const skillRoot = await fakeSkillRoot(t);
  for (const options of [
    { targetBrowser: 'firefox' },
    { targetOs: 'android' },
    { profile: 'unreviewed' },
  ]) {
    const project = await projectRoot(t);
    await assert.rejects(initDeck({ projectDir: project, skillRoot, ...options }), /expected one of/);
  }

  const project = await projectRoot(t);
  await initDeck({ projectDir: project, skillRoot });
  const configPath = path.join(project, 'deck.config.json');
  const config = await readJson(configPath);
  config.target.browser = 'firefox';
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);
  await assert.rejects(buildDeck({ projectDir: project, skillRoot }), /target\.browser.*expected one of/);
  config.target.browser = 'chromium';
  config.target.os = 'android';
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);
  await assert.rejects(buildDeck({ projectDir: project, skillRoot }), /target\.os.*expected one of/);
  config.target.os = 'current';
  config.deliveryProfile = 'unreviewed';
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);
  await assert.rejects(buildDeck({ projectDir: project, skillRoot }), /deliveryProfile.*expected one of/);
});

test('standalone engine conversion removes variable dynamic imports and the local motion path', async () => {
  const source = "const localMotionModule='./motion.min.js'; try { await import(localMotionModule); } catch {}";
  const converted = standaloneEngineSource(source);
  assert.match(converted, /^window\.__WEB_SLIDE_STANDALONE__ = true;/);
  assert.doesNotMatch(converted, /\bimport\b/);
  assert.doesNotMatch(converted, /\.\/motion\.min\.js/);
  assert.equal(standaloneEngineSource(converted), converted);
  assert.throws(
    () => standaloneEngineSource("import /* hidden */ ('./motion.min.js')"),
    /still contains a local dynamic import/,
  );
});

test('a compatible prior manifest remains managed across generator version upgrades', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'Upgrade', theme: 'swiss', skillRoot });
  await write(project, 'src/slides/media/old.png', 'old-media');
  const slidePath = path.join(project, 'src/slides/001-opening.html');
  const original = await readFile(slidePath, 'utf8');
  await writeFile(slidePath, original.replace('</section>', '<img alt="old" src="./media/old.png"></section>'));
  const first = await buildDeck({ projectDir: project, skillRoot });
  const oldMedia = first.manifest.files.find((entry) => entry.path.startsWith('assets/media/')).path;
  assert.equal(first.manifest.generator.version, '9.0.0');

  await write(skillRoot, 'package.json', '{"name":"tool-web-slide","version":"10.0.0","type":"module"}\n');
  await writeFile(slidePath, original);
  const upgraded = await buildDeck({ projectDir: project, skillRoot });
  assert.equal(upgraded.manifest.generator.version, '10.0.0');
  assert.ok(upgraded.removed.includes(oldMedia));
  await assert.rejects(readFile(path.join(project, 'dist', ...oldMedia.split('/'))), /ENOENT/);
});

test('media delivery deduplicates by full content hash, MIME, and normalized extension', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  for (const mode of ['bundle', 'standalone']) {
    const project = await projectRoot(t);
    await initDeck({ projectDir: project, title: `Dedupe ${mode}`, theme: 'swiss', mode, skillRoot });
    await write(project, 'src/slides/media/alpha.png', 'same-media-bytes');
    await write(project, 'src/slides/media/beta.png', 'same-media-bytes');
    await write(project, 'src/slides/media/gamma.jpg', 'same-media-bytes');
    const slidePath = path.join(project, 'src/slides/001-opening.html');
    const slide = await readFile(slidePath, 'utf8');
    await writeFile(
      slidePath,
      slide.replace(
        '</section>',
        '<img alt="alpha" src="./media/alpha.png"><img alt="beta" src="./media/beta.png"><img alt="gamma" src="./media/gamma.jpg"></section>',
      ),
    );
    const result = await buildDeck({ projectDir: project, skillRoot });
    const media = mode === 'bundle' ? result.manifest.copiedAssets : result.manifest.embeddedAssets;
    assert.equal(media.length, 2);
    const png = media.find((entry) => entry.extension === '.png');
    assert.deepEqual(png.sources, ['src/slides/media/alpha.png', 'src/slides/media/beta.png']);
    assert.equal(png.sha256.length, 64);
    const html = await readFile(path.join(project, 'dist/index.html'), 'utf8');
    const alpha = html.match(/alt="alpha" src="([^"]+)"/)?.[1];
    const beta = html.match(/alt="beta" src="([^"]+)"/)?.[1];
    assert.equal(alpha, beta);
    if (mode === 'bundle') {
      assert.match(alpha, /^\.\/assets\/media\/[a-f0-9]{64}\.png$/);
      assert.equal(result.manifest.files.filter((entry) => entry.path.startsWith('assets/media/')).length, 2);
      const noOp = await buildDeck({ projectDir: project, skillRoot });
      assert.deepEqual(noOp.changed, []);
    } else {
      assert.match(alpha, /^data:image\/png;base64,/);
    }
  }
});

test('SVG fetch attributes are localized and remote SVG resources are blocked offline', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'SVG resources', theme: 'swiss', skillRoot });
  await write(project, 'src/slides/media/sprite.svg', '<svg xmlns="http://www.w3.org/2000/svg"><path id="shape" d="M0 0h1v1z"/></svg>');
  await writeFile(
    path.join(project, 'src/slides/001-opening.html'),
    '<section class="slide" data-slide-id="opening" data-layout="hero" data-evidence="none"><div class="canvas-card layout-hero"><svg><use href="./media/sprite.svg#shape"></use><feImage xlink:href="./media/sprite.svg"></feImage><linearGradient href="#local"></linearGradient></svg></div></section>\n',
  );
  const result = await buildDeck({ projectDir: project, skillRoot });
  assert.equal(result.manifest.copiedAssets.length, 1);
  const html = await readFile(path.join(project, 'dist/index.html'), 'utf8');
  assert.match(html, /<use href="\.\/assets\/media\/[a-f0-9]{64}\.svg#shape"/);
  assert.match(html, /<feImage xlink:href="\.\/assets\/media\/[a-f0-9]{64}\.svg"/);
  assert.match(html, /<linearGradient href="#local"/);

  const remoteProject = await projectRoot(t);
  await initDeck({ projectDir: remoteProject, title: 'Remote SVG', theme: 'swiss', skillRoot });
  await writeFile(
    path.join(remoteProject, 'src/slides/001-opening.html'),
    '<section class="slide" data-slide-id="opening" data-layout="hero" data-evidence="none"><div class="canvas-card layout-hero"><svg><use href=https://example.org/sprite.svg#shape></use></svg></div></section>\n',
  );
  await assert.rejects(buildDeck({ projectDir: remoteProject, skillRoot }), /offlineRequired=true/);
});

test('CSS resource syntax is case-insensitive and fails closed on escaped or indirect functions', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const valid = await projectRoot(t);
  await initDeck({ projectDir: valid, title: 'Upper URL', theme: 'swiss', skillRoot });
  await write(valid, 'pixel.png', 'pixel');
  await write(valid, 'design-system.css', '.pixel{background:URL("./pixel.png")}\n');
  const validConfigPath = path.join(valid, 'deck.config.json');
  const validConfig = await readJson(validConfigPath);
  validConfig.designSystem.stylesheet = 'design-system.css';
  await writeFile(validConfigPath, `${JSON.stringify(validConfig, null, 2)}\n`);
  await buildDeck({ projectDir: valid, skillRoot });
  assert.match(
    await readFile(path.join(valid, 'dist/assets/design-system.css'), 'utf8'),
    /url\("\.\/media\/[a-f0-9]{64}\.png"\)/,
  );

  for (const css of [
    '.x{background:\\75rl(https://example.org/x.png)}',
    '.x{background:u/**/rl(https://example.org/x.png)}',
    '.x{background:image-set(url("https://example.org/x.png") 1x)}',
    '@\\69mport "https://example.org/x.css";',
  ]) {
    const project = await projectRoot(t);
    await initDeck({ projectDir: project, title: 'Unsafe CSS', theme: 'swiss', skillRoot });
    await write(project, 'design-system.css', `${css}\n`);
    const configPath = path.join(project, 'deck.config.json');
    const config = await readJson(configPath);
    config.designSystem.stylesheet = 'design-system.css';
    await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);
    await assert.rejects(buildDeck({ projectDir: project, skillRoot }), /不允许|不支持/);
  }
});

test('HTML resource rewriting is scoped to style blocks and style attributes, not body text', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'Inline CSS scope', theme: 'swiss', skillRoot });
  await write(project, 'src/slides/media/pixel.png', 'inline-css-pixel');
  const slidePath = path.join(project, 'src/slides/001-opening.html');
  const slide = await readFile(slidePath, 'utf8');
  await writeFile(
    slidePath,
    slide.replace(
      '</section>',
      '<p class="source-note">CSS example: url("https://example.org/not-a-resource.png") and image-set(...)</p><style>.local{background:URL("./media/pixel.png")}</style><div class="local" style="background:URL(&quot;./media/pixel.png&quot;)"></div></section>',
    ),
  );
  const result = await buildDeck({ projectDir: project, skillRoot });
  assert.equal(result.manifest.copiedAssets.length, 1);
  const html = await readFile(path.join(project, 'dist/index.html'), 'utf8');
  assert.match(html, /CSS example: url\("https:\/\/example\.org\/not-a-resource\.png"\) and image-set\(\.\.\.\)/);
  assert.match(html, /<style>\.local\{background:url\("\.\/assets\/media\/[a-f0-9]{64}\.png"\)\}<\/style>/);
  assert.match(html, /style="background:url\(&quot;\.\/assets\/media\/[a-f0-9]{64}\.png&quot;\)"/);
});

test('external dependency count is the number of unique URLs across HTML and CSS', async (t) => {
  const skillRoot = await fakeSkillRoot(t);
  const project = await projectRoot(t);
  await initDeck({ projectDir: project, title: 'External count', theme: 'swiss', skillRoot });
  const configPath = path.join(project, 'deck.config.json');
  const config = await readJson(configPath);
  config.offlineRequired = false;
  config.designSystem.stylesheet = 'design-system.css';
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`);
  await write(project, 'design-system.css', '.remote{background:url("https://example.org/shared.png")}\n');
  const slidePath = path.join(project, 'src/slides/001-opening.html');
  const slide = await readFile(slidePath, 'utf8');
  await writeFile(slidePath, slide.replace('</section>', '<img alt="remote" src="https://example.org/shared.png"></section>'));
  const result = await buildDeck({ projectDir: project, skillRoot });
  assert.equal(result.manifest.externalDependencies, 1);
  assert.deepEqual(result.manifest.externalDependencyUrls, ['https://example.org/shared.png']);
});

test('resource manifest covers runtime files while excluding materializer-owned metadata', async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'web-slide-manifest-'));
  t.after(async () => {
    const { rm } = await import('node:fs/promises');
    await rm(root, { recursive: true, force: true });
  });
  await write(root, 'SKILL.md', '---\nname: sample\ndescription: sample\n---\nRead `references/contract.md`.\n');
  await write(root, 'package.json', '{"name":"sample"}\n');
  await write(root, 'references/contract.md', 'A\r\nB\r\n');
  await write(root, 'scripts/build.mjs', 'export {};\n');
  await write(root, 'tests/build.test.mjs', 'export {};\n');
  await write(root, 'agents/openai.yaml', 'interface: {}\n');
  await write(root, 'assets/icon.svg', '<svg/>\n');

  const manifest = await createResourceManifest(root);
  assert.equal(manifest.missing_declared_dependencies.length, 0);
  assert.ok(manifest.resource_file_hashes.some((entry) => entry.path === 'scripts/build.mjs'));
  assert.ok(manifest.resource_file_hashes.some((entry) => entry.path === 'tests/build.test.mjs'));
  assert.ok(!manifest.resource_file_hashes.some((entry) => entry.path === 'agents/openai.yaml'));
  assert.ok(!manifest.resource_file_hashes.some((entry) => entry.path === 'assets/icon.svg'));
  assert.equal(manifest.declared_local_dependencies[0].path, 'references/contract.md');
});

#!/usr/bin/env node

import { existsSync } from 'node:fs';
import { lstat, mkdir, realpath } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import {
  DEFAULT_SKILL_ROOT,
  DeckBuildError,
  getThemeDefinition,
  normalizeAspect,
  writeIfChanged,
} from './build-deck.mjs';
import {
  DELIVERY_PROFILES,
  parseDeliveryProfile,
  parseTargetBrowser,
  parseTargetOs,
  TARGET_BROWSERS,
  TARGET_OSES,
} from './lib/delivery-contract.mjs';

const MODES = new Set(['bundle', 'standalone']);
const EVIDENCE_POLICIES = new Set(['advisory', 'required']);

function fail(message) {
  throw new DeckBuildError(message);
}

function parseContractValue(parser, value) {
  try {
    return parser(value);
  } catch (error) {
    fail(error.message);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function inside(parent, child) {
  const relative = path.relative(parent, child);
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
}

async function safeInitTarget(projectRoot, target, label) {
  if (!inside(projectRoot, target) || target === projectRoot) fail(`${label} 路径越界`);
  const parent = path.dirname(target);
  let ancestor = parent;
  while (!existsSync(ancestor)) {
    const next = path.dirname(ancestor);
    if (next === ancestor) fail(`${label} 找不到安全父目录`);
    ancestor = next;
  }
  const ancestorReal = await realpath(ancestor);
  if (!inside(projectRoot, ancestorReal)) fail(`${label} 的既有父目录通过符号链接逃逸项目目录`);
  await mkdir(parent, { recursive: true });
  const parentReal = await realpath(parent);
  if (!inside(projectRoot, parentReal)) fail(`${label} 的父目录通过符号链接逃逸项目目录`);
  if (existsSync(target)) {
    const info = await lstat(target);
    if (info.isSymbolicLink()) fail(`${label} 是符号链接，拒绝覆盖`);
    const actual = await realpath(target);
    if (!inside(projectRoot, actual)) fail(`${label} 真实路径位于项目之外`);
  }
  return target;
}

function parseCli(argv) {
  const options = {
    projectDir: null,
    title: 'Presentation Title',
    theme: 'swiss',
    aspect: '16:9',
    mode: 'bundle',
    lang: 'zh-CN',
    evidencePolicy: 'advisory',
    profile: 'standard-client',
    targetBrowser: 'chromium',
    targetOs: 'current',
    width: 1920,
    height: null,
    force: false,
  };
  const valueOptions = new Map([
    ['--title', 'title'],
    ['--theme', 'theme'],
    ['--aspect', 'aspect'],
    ['--mode', 'mode'],
    ['--lang', 'lang'],
    ['--evidence-policy', 'evidencePolicy'],
    ['--profile', 'profile'],
    ['--target-browser', 'targetBrowser'],
    ['--target-os', 'targetOs'],
    ['--width', 'width'],
    ['--height', 'height'],
  ]);
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--help' || arg === '-h') return { ...options, help: true };
    if (arg === '--force') { options.force = true; continue; }
    if (valueOptions.has(arg)) {
      const value = argv[index + 1];
      if (!value || value.startsWith('--')) fail(`${arg} 缺少值`);
      options[valueOptions.get(arg)] = value;
      index += 1;
      continue;
    }
    if (arg.startsWith('--')) fail(`未知参数：${arg}`);
    if (options.projectDir) fail(`只能指定一个 projectDir：${arg}`);
    options.projectDir = arg;
  }
  return options;
}

function sampleSlide(title, evidencePolicy) {
  const evidence = evidencePolicy === 'required' ? 'required' : 'none';
  const evidencePlaceholder = evidencePolicy === 'required'
    ? '    <p class="source-note" data-source="" data-source-date="">待填写：真实来源名称、链接与发布日期；完成前 QA 将阻断交付。</p>\n'
    : '';
  return `<section class="slide hero" id="slide-opening" data-slide-id="opening" data-layout="hero" data-evidence="${evidence}">
  <div class="canvas-card layout-hero" style="display:flex;flex-direction:column">
    <div class="chrome">
      <div class="l">WEB SLIDE</div>
      <div class="r">01 / 01</div>
    </div>
    <div style="margin:auto 0">
      <p class="kicker">OPENING</p>
      <h1 class="h-xl-zh">${escapeHtml(title)}</h1>
      <p class="lead" style="margin-top:2vh">用一个清楚的结论开始。</p>
    </div>
${evidencePlaceholder}    <div class="foot"><span>LOCAL · OFFLINE</span><span class="nb">01</span></div>
  </div>
</section>
`;
}

export async function initDeck({
  projectDir = '.',
  title = 'Presentation Title',
  theme = 'swiss',
  aspect = '16:9',
  mode = 'bundle',
  lang = 'zh-CN',
  evidencePolicy = 'advisory',
  profile = 'standard-client',
  targetBrowser = 'chromium',
  targetOs = 'current',
  width = 1920,
  height = null,
  force = false,
  skillRoot = DEFAULT_SKILL_ROOT,
} = {}) {
  const projectCandidate = path.resolve(projectDir);
  if (typeof title !== 'string' || !title.trim()) fail('title 不能为空');
  if (!MODES.has(mode)) fail(`mode 必须是 bundle 或 standalone：${mode}`);
  if (!EVIDENCE_POLICIES.has(evidencePolicy)) fail(`evidencePolicy 必须是 advisory 或 required：${evidencePolicy}`);
  const normalizedProfile = parseContractValue(parseDeliveryProfile, profile);
  const normalizedTargetBrowser = parseContractValue(parseTargetBrowser, targetBrowser);
  const normalizedTargetOs = parseContractValue(parseTargetOs, targetOs);
  const effectiveEvidencePolicy = normalizedProfile === 'high-assurance' ? 'required' : evidencePolicy;
  if (!/^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(lang)) fail(`无效 lang：${lang}`);
  const normalizedAspect = normalizeAspect(aspect);
  const viewportWidth = Number(width);
  const viewportHeight = height === null ? Math.round(viewportWidth / normalizedAspect.ratio) : Number(height);
  if (!Number.isInteger(viewportWidth) || viewportWidth < 320 || viewportWidth > 7680
      || !Number.isInteger(viewportHeight) || viewportHeight < 320 || viewportHeight > 7680) {
    fail('width/height 必须是 320–7680 范围内的整数');
  }
  const ratioError = Math.abs((viewportWidth / viewportHeight) - normalizedAspect.ratio) / normalizedAspect.ratio;
  if (ratioError > 0.001) fail(`${viewportWidth}x${viewportHeight} 与 aspect ${normalizedAspect.label} 不一致`);
  await getThemeDefinition(theme, { skillRoot });
  await mkdir(projectCandidate, { recursive: true });
  const projectRoot = await realpath(projectCandidate);

  const configPath = await safeInitTarget(projectRoot, path.join(projectRoot, 'deck.config.json'), 'deck.config.json');
  const slidePath = await safeInitTarget(projectRoot, path.join(projectRoot, 'src', 'slides', '001-opening.html'), '示例 slide');
  const occupied = [configPath, slidePath].filter((filePath) => existsSync(filePath));
  if (occupied.length && !force) {
    fail(`目标已存在，未做覆盖：${occupied.map((filePath) => path.relative(projectRoot, filePath)).join(', ')}；确认后使用 --force`);
  }

  const config = {
    schemaVersion: '1.0.0',
    title: title.trim(),
    lang,
    theme,
    aspect: normalizedAspect.label,
    evidencePolicy: effectiveEvidencePolicy,
    offlineRequired: true,
    deliveryProfile: normalizedProfile,
    target: {
      browser: normalizedTargetBrowser,
      os: normalizedTargetOs,
      viewport: { width: viewportWidth, height: viewportHeight },
    },
    slides: {
      directory: 'src/slides',
      order: ['001-opening.html'],
    },
    designSystem: {
      stylesheet: null,
    },
    output: {
      mode,
      dir: 'dist',
    },
  };

  await mkdir(path.dirname(slidePath), { recursive: true });
  const changed = [];
  const unchanged = [];
  if (await writeIfChanged(configPath, `${JSON.stringify(config, null, 2)}\n`, { force })) changed.push('deck.config.json');
  else unchanged.push('deck.config.json');
  if (await writeIfChanged(slidePath, sampleSlide(config.title, effectiveEvidencePolicy), { force })) changed.push('src/slides/001-opening.html');
  else unchanged.push('src/slides/001-opening.html');

  const readyForQa = effectiveEvidencePolicy !== 'required';
  return {
    projectRoot,
    config,
    changed,
    unchanged,
    readyForQa,
    blockingActions: readyForQa ? [] : ['填写真实 source-note 的 data-source 与 data-source-date 后再运行 QA'],
  };
}

function usage() {
  return `Usage: node scripts/init-deck.mjs [projectDir] [options]\n\nOptions:\n  --title <title>               Presentation title\n  --theme <theme>               Theme ID from references/components.json\n  --aspect <width:height>       Canvas ratio (default: 16:9)\n  --mode <mode>                 bundle or standalone\n  --lang <language-tag>         HTML language (default: zh-CN)\n  --evidence-policy <policy>    advisory or required\n  --profile <profile>           ${DELIVERY_PROFILES.join('|')}\n  --target-browser <browser>    ${TARGET_BROWSERS.join('|')} (default: chromium)\n  --target-os <os>              ${TARGET_OSES.join('|')} (default: current)\n  --width <pixels>              Target viewport width (default: 1920)\n  --height <pixels>             Target viewport height (derived from aspect)\n  --force                       Replace initializer-owned files\n  -h, --help                    Show this help`;
}

async function main() {
  const options = parseCli(process.argv.slice(2));
  if (options.help) {
    process.stdout.write(`${usage()}\n`);
    return;
  }
  const result = await initDeck({ ...options, projectDir: options.projectDir ?? '.' });
  process.stdout.write(`${JSON.stringify({
    ok: true,
    projectRoot: result.projectRoot,
    changed: result.changed,
    unchanged: result.unchanged,
    readyForQa: result.readyForQa,
    blockingActions: result.blockingActions,
    next: `node scripts/build-deck.mjs ${result.projectRoot}`,
  }, null, 2)}\n`);
}

const isMain = process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;
if (isMain) {
  main().catch((error) => {
    process.stderr.write(`init-deck: ${error.message}\n`);
    process.exitCode = 1;
  });
}

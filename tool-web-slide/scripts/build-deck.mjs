#!/usr/bin/env node

import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import {
  mkdir,
  lstat,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rename,
  rm,
  stat,
  writeFile,
} from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import {
  DELIVERY_PROFILES,
  FETCH_RESOURCE_ATTRIBUTES,
  inspectCssResourceSyntax,
  parseDeliveryProfile,
  parseTargetBrowser,
  parseTargetOs,
  requiredGatesFor,
  SVG_FETCH_ELEMENTS,
  standaloneEngineSource,
  TARGET_BROWSERS,
  TARGET_OSES,
} from './lib/delivery-contract.mjs';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
export const DEFAULT_SKILL_ROOT = path.resolve(SCRIPT_DIR, '..');
const CONFIG_SCHEMA_VERSION = '1.0.0';
const DELIVERY_SCHEMA_VERSION = '1.0.0';
const MODES = new Set(['bundle', 'standalone']);
const EVIDENCE_POLICIES = new Set(['advisory', 'required']);
const MIME_TYPES = new Map([
  ['.avif', 'image/avif'],
  ['.css', 'text/css'],
  ['.gif', 'image/gif'],
  ['.jpeg', 'image/jpeg'],
  ['.jpg', 'image/jpeg'],
  ['.js', 'text/javascript'],
  ['.m4a', 'audio/mp4'],
  ['.mp3', 'audio/mpeg'],
  ['.mp4', 'video/mp4'],
  ['.oga', 'audio/ogg'],
  ['.ogg', 'audio/ogg'],
  ['.ogv', 'video/ogg'],
  ['.otf', 'font/otf'],
  ['.pdf', 'application/pdf'],
  ['.png', 'image/png'],
  ['.svg', 'image/svg+xml'],
  ['.ttf', 'font/ttf'],
  ['.wav', 'audio/wav'],
  ['.webm', 'video/webm'],
  ['.webp', 'image/webp'],
  ['.woff', 'font/woff'],
  ['.woff2', 'font/woff2'],
]);

export class DeckBuildError extends Error {
  constructor(message) {
    super(message);
    this.name = 'DeckBuildError';
  }
}

export function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function asBuffer(value) {
  return Buffer.isBuffer(value) ? value : Buffer.from(String(value), 'utf8');
}

export async function writeIfChanged(filePath, value, { force = false } = {}) {
  const next = asBuffer(value);
  if (!force && existsSync(filePath)) {
    const current = await readFile(filePath);
    if (current.length === next.length && sha256(current) === sha256(next)) {
      return false;
    }
  }
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, next);
  return true;
}

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

function readJsonText(text, label) {
  try {
    return JSON.parse(text);
  } catch (error) {
    fail(`${label} 不是有效 JSON：${error.message}`);
  }
}

async function readJson(filePath, label = filePath) {
  let text;
  try {
    text = await readFile(filePath, 'utf8');
  } catch (error) {
    fail(`无法读取 ${label}：${error.message}`);
  }
  return readJsonText(text, label);
}

function inside(parent, child) {
  const relative = path.relative(parent, child);
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
}

function resolveInside(root, relativePath, label) {
  if (typeof relativePath !== 'string' || !relativePath.trim()) {
    fail(`${label} 必须是非空路径`);
  }
  const resolved = path.resolve(root, relativePath);
  if (!inside(root, resolved)) fail(`${label} 必须位于项目目录内：${relativePath}`);
  return resolved;
}

async function realContainedPath(root, candidate, label, { kind = 'file' } = {}) {
  let actual;
  try {
    actual = await realpath(candidate);
  } catch (error) {
    fail(`${label} 不存在或无法解析真实路径：${error.message}`);
  }
  if (!inside(root, actual)) fail(`${label} 通过符号链接逃逸允许目录：${candidate}`);
  const info = await stat(actual);
  if (kind === 'file' && !info.isFile()) fail(`${label} 必须是普通文件`);
  if (kind === 'directory' && !info.isDirectory()) fail(`${label} 必须是目录`);
  return actual;
}

function pathsOverlap(left, right) {
  return inside(left, right) || inside(right, left);
}

async function nearestExistingAncestor(candidate) {
  let current = candidate;
  while (!existsSync(current)) {
    const parent = path.dirname(current);
    if (parent === current) fail(`找不到可写入路径的既有父目录：${candidate}`);
    current = parent;
  }
  return current;
}

async function prepareOutputDirectory(projectRoot, candidate, sourceDirectories, sourceFiles = []) {
  const ancestor = await nearestExistingAncestor(candidate);
  const ancestorReal = await realpath(ancestor);
  if (!inside(projectRoot, ancestorReal)) fail(`output.dir 通过符号链接逃逸项目目录：${candidate}`);
  const predicted = path.resolve(ancestorReal, path.relative(ancestor, candidate));
  if (!inside(projectRoot, predicted) || predicted === projectRoot) fail(`output.dir 真实路径不安全：${candidate}`);
  for (const sourceDirectory of sourceDirectories) {
    if (pathsOverlap(predicted, sourceDirectory)) {
      fail(`output.dir 不得与源目录重叠：${predicted} <-> ${sourceDirectory}`);
    }
  }
  for (const sourceFile of sourceFiles) {
    if (inside(predicted, sourceFile)) fail(`output.dir 不得覆盖源文件：${sourceFile}`);
  }
  await mkdir(candidate, { recursive: true });
  const outputRoot = await realpath(candidate);
  if (!inside(projectRoot, outputRoot)) fail(`output.dir 真实路径位于项目目录之外：${candidate}`);
  if (outputRoot === projectRoot) fail('output.dir 不得等于项目根目录');
  return outputRoot;
}

async function safeOutputTarget(outputRoot, relativePath) {
  const target = path.resolve(outputRoot, ...relativePath.split('/'));
  if (!inside(outputRoot, target) || target === outputRoot) fail(`输出文件路径越界：${relativePath}`);
  const parent = path.dirname(target);
  const ancestor = await nearestExistingAncestor(parent);
  const ancestorReal = await realpath(ancestor);
  if (!inside(outputRoot, ancestorReal)) fail(`输出父目录通过符号链接逃逸：${relativePath}`);
  await mkdir(parent, { recursive: true });
  const parentReal = await realpath(parent);
  if (!inside(outputRoot, parentReal)) fail(`输出父目录真实路径越界：${relativePath}`);
  if (existsSync(target)) {
    const info = await lstat(target);
    if (info.isSymbolicLink()) fail(`拒绝写入符号链接文件：${relativePath}`);
    const actual = await realpath(target);
    if (!inside(outputRoot, actual)) fail(`输出文件真实路径越界：${relativePath}`);
  }
  return target;
}

function normalizeAssetReference(reference, label) {
  if (typeof reference !== 'string' || !reference.trim()) fail(`${label} 必须是字符串`);
  const normalized = reference.trim().replaceAll('\\', '/').replace(/^\.\//, '');
  if (!normalized.startsWith('assets/') || normalized.includes('../')) {
    fail(`${label} 必须指向技能 canonical assets/：${reference}`);
  }
  return normalized;
}

function toArray(value) {
  if (value === null || value === undefined || value === '') return [];
  return Array.isArray(value) ? value : [value];
}

export function normalizeAspect(value) {
  if (typeof value !== 'string') fail('aspect 必须使用“宽:高”字符串');
  const match = value.trim().match(/^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/);
  if (!match) fail(`无效 aspect：${value}；应使用 16:9、16:10 或 4:3 等正数比例`);
  const width = Number(match[1]);
  const height = Number(match[2]);
  if (!(width > 0 && height > 0)) fail(`aspect 必须为正数比例：${value}`);
  return {
    label: `${match[1]}:${match[2]}`,
    width,
    height,
    ratio: width / height,
  };
}

function normalizeConfig(raw, projectRoot, overrides = {}) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) fail('deck.config.json 顶层必须是对象');
  if (raw.schemaVersion !== CONFIG_SCHEMA_VERSION) {
    fail(`不支持的 deck.config.json schemaVersion：${raw.schemaVersion ?? '(missing)'}；当前为 ${CONFIG_SCHEMA_VERSION}`);
  }

  const title = typeof raw.title === 'string' && raw.title.trim() ? raw.title.trim() : 'Untitled Presentation';
  const lang = typeof raw.lang === 'string' && /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(raw.lang)
    ? raw.lang
    : fail(`无效 lang：${raw.lang ?? '(missing)'}`);
  const theme = typeof raw.theme === 'string' && raw.theme.trim() ? raw.theme.trim() : fail('theme 不能为空');
  const aspect = normalizeAspect(raw.aspect ?? '16:9');
  const evidencePolicy = raw.evidencePolicy ?? 'advisory';
  if (!EVIDENCE_POLICIES.has(evidencePolicy)) fail(`evidencePolicy 必须是 advisory 或 required：${evidencePolicy}`);
  const offlineRequired = raw.offlineRequired ?? true;
  if (typeof offlineRequired !== 'boolean') fail('offlineRequired 必须是布尔值');
  const deliveryProfile = parseContractValue(parseDeliveryProfile, raw.deliveryProfile ?? 'standard-client');
  if (deliveryProfile === 'high-assurance' && (!offlineRequired || evidencePolicy !== 'required')) {
    fail('high-assurance 强制 offlineRequired=true 且 evidencePolicy=required');
  }

  const targetInput = raw.target ?? {};
  if (!targetInput || typeof targetInput !== 'object' || Array.isArray(targetInput)) fail('target 必须是对象');
  const browser = parseContractValue(parseTargetBrowser, targetInput.browser ?? 'chromium');
  const os = parseContractValue(parseTargetOs, targetInput.os ?? 'current');
  const viewportInput = targetInput.viewport ?? {};
  if (!viewportInput || typeof viewportInput !== 'object' || Array.isArray(viewportInput)) fail('target.viewport 必须是对象');
  const viewportWidth = viewportInput.width ?? 1920;
  const viewportHeight = viewportInput.height ?? Math.round(viewportWidth / aspect.ratio);
  if (!Number.isInteger(viewportWidth) || viewportWidth < 320 || viewportWidth > 7680
      || !Number.isInteger(viewportHeight) || viewportHeight < 320 || viewportHeight > 7680) {
    fail('target.viewport.width/height 必须是 320–7680 范围内的整数');
  }
  const ratioError = Math.abs((viewportWidth / viewportHeight) - aspect.ratio) / aspect.ratio;
  if (ratioError > 0.001) {
    fail(`target.viewport ${viewportWidth}x${viewportHeight} 与 aspect ${aspect.label} 不一致`);
  }

  const slides = raw.slides ?? {};
  if (!slides || typeof slides !== 'object' || Array.isArray(slides)) fail('slides 必须是对象');
  const slidesDirectory = slides.directory ?? 'src/slides';
  const slidesDir = resolveInside(projectRoot, slidesDirectory, 'slides.directory');
  const order = slides.order ?? [];
  if (!Array.isArray(order) || order.some((item) => typeof item !== 'string' || !item.endsWith('.html'))) {
    fail('slides.order 必须是 .html 文件名数组');
  }
  if (new Set(order).size !== order.length) fail('slides.order 包含重复文件名');

  const designSystem = raw.designSystem ?? {};
  if (designSystem !== null && (typeof designSystem !== 'object' || Array.isArray(designSystem))) {
    fail('designSystem 必须是对象或 null');
  }
  const designSystemReference = designSystem?.stylesheet ?? null;
  const designSystemPath = designSystemReference
    ? resolveInside(projectRoot, designSystemReference, 'designSystem.stylesheet')
    : null;

  const output = raw.output ?? {};
  if (!output || typeof output !== 'object' || Array.isArray(output)) fail('output 必须是对象');
  const mode = overrides.mode ?? output.mode ?? 'bundle';
  if (!MODES.has(mode)) fail(`output.mode 必须是 bundle 或 standalone：${mode}`);
  const outputReference = overrides.out ?? output.dir ?? 'dist';
  const outputDir = resolveInside(projectRoot, outputReference, 'output.dir');

  return {
    schemaVersion: CONFIG_SCHEMA_VERSION,
    title,
    lang,
    theme,
    aspect,
    evidencePolicy,
    offlineRequired,
    deliveryProfile,
    requiredGates: requiredGatesFor(deliveryProfile),
    target: {
      browser,
      os,
      viewport: { width: viewportWidth, height: viewportHeight },
    },
    slides: { directory: slidesDirectory, dir: slidesDir, order },
    designSystem: { reference: designSystemReference, path: designSystemPath },
    output: { mode, reference: outputReference, dir: outputDir },
  };
}

export async function getThemeDefinition(theme, { skillRoot = DEFAULT_SKILL_ROOT } = {}) {
  const registryPath = path.join(skillRoot, 'references', 'components.json');
  const registry = await readJson(registryPath, 'references/components.json');
  if (!registry.themes || typeof registry.themes !== 'object') fail('components.json 缺少 themes 对象');
  const definition = registry.themes[theme];
  if (!definition || typeof definition !== 'object') {
    fail(`未知主题“${theme}”；可用主题：${Object.keys(registry.themes).sort().join(', ') || '(none)'}`);
  }
  const references = [
    ...toArray(definition.baseStylesheet),
    ...toArray(definition.stylesheet),
  ].map((entry, index) => normalizeAssetReference(entry, `themes.${theme}.stylesheet[${index}]`));
  const stylesheets = [...new Set(references)];
  if (!stylesheets.length) fail(`主题“${theme}”没有声明 stylesheet`);
  return { registry, definition, stylesheets };
}

function slugFromFilename(filename) {
  const base = path.basename(filename, path.extname(filename))
    .toLowerCase()
    .replace(/^\d+[\s._-]*/, '')
    .normalize('NFKD')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return base || `slide-${sha256(filename).slice(0, 10)}`;
}

function extractAttribute(openingTag, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = openingTag.match(new RegExp(`\\s${escaped}\\s*=\\s*(["'])(.*?)\\1`, 'i'));
  return match ? match[2].trim() : null;
}

function hasSlideClass(openingTag) {
  const classes = extractAttribute(openingTag, 'class');
  return classes?.split(/\s+/).includes('slide') ?? false;
}

function injectSectionAttribute(fragment, name, value) {
  return fragment.replace(/<section\b/i, `<section ${name}="${value}"`);
}

function decodeHtmlEntities(value) {
  return String(value)
    .replace(/&#(?:x([0-9a-f]+)|(\d+));?/gi, (match, hex, decimal) => {
      const codePoint = Number.parseInt(hex ?? decimal, hex ? 16 : 10);
      try {
        return Number.isFinite(codePoint) ? String.fromCodePoint(codePoint) : match;
      } catch {
        return match;
      }
    })
    .replace(/&quot;/gi, '"')
    .replace(/&apos;|&#39;/gi, "'")
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&amp;/gi, '&')
    .replace(/&colon;/gi, ':')
    .replace(/&tab;/gi, '\t')
    .replace(/&newline;/gi, '\n');
}

function normalizedUrlForPolicy(value) {
  return decodeHtmlEntities(value).trim().replace(/[\u0000-\u0020]+/g, '').toLowerCase();
}

function ensureStaticReferenceAllowed(value, label) {
  const normalized = normalizedUrlForPolicy(value);
  if (normalized.startsWith('blob:')) fail(`${label}：禁止 blob: 静态资源；请使用受控本地文件或 data URI`);
  if (/^(?:javascript:|vbscript:|data:text\/html)/i.test(normalized)) fail(`${label}：禁止可执行 URL scheme`);
}

function attributeValue(tag, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = tag.match(new RegExp(`\\b${escaped}\\s*=\\s*(?:(["'])([\\s\\S]*?)\\1|([^\\s>]+))`, 'i'));
  return match ? (match[2] ?? match[3] ?? '') : null;
}

function validateFragmentUrls(fragment, filename) {
  const attributes = /\b(?:href|xlink:href|src|action|formaction|poster|data|ping)\s*=\s*(?:(["'])([\s\S]*?)\1|([^\s>]+))/gi;
  for (const match of fragment.matchAll(attributes)) {
    const value = match[2] ?? match[3] ?? '';
    ensureStaticReferenceAllowed(value, filename);
  }
}

function validateFragmentSafety(fragment, filename) {
  const checks = [
    [/<script\b/i, '禁止 <script>；运行时脚本只能由构建骨架注入'],
    [/<base\b/i, '禁止 <base> 重写全局资源基准'],
    [/<(?:object|embed)\b/i, '禁止可执行嵌入对象；请使用静态图片或受控媒体'],
    [/<iframe\b/i, '禁止 <iframe> 与 srcdoc 可执行嵌入'],
    [/<link\b/i, '禁止页面片段自行加载 link 资源；样式必须通过 designSystem 声明'],
    [/<form\b[^>]*\baction\s*=|\bformaction\s*=/i, '禁止表单外发入口'],
    [/<[^>]+\bping\s*=/i, '禁止 ping 外发入口'],
    [/<[^>]+\son[a-z0-9:_-]*\s*=/i, '禁止 on* 内联事件处理器'],
    [/<[^>]+\b(?:href|src|action|formaction|poster|data)\s*=\s*(["'])\s*(?:javascript:|vbscript:|data:text\/html)/i, '禁止可执行 URL scheme'],
    [/<[^>]+\b(?:href|src|action|formaction|poster|data)\s*=\s*(?:javascript:|vbscript:|data:text\/html)[^\s>]*/i, '禁止可执行 URL scheme'],
    [/<[^>]+\bsrcdoc\s*=/i, '禁止 iframe srcdoc'],
    [/<meta\b[^>]*\bhttp-equiv\s*=\s*(["'])?refresh\1/i, '禁止 meta refresh'],
    [/\bexpression\s*\(/i, '禁止 CSS expression()'],
    [/url\s*\(\s*(["'])?\s*javascript:/i, '禁止 CSS javascript: URL'],
  ];
  for (const [pattern, message] of checks) {
    if (pattern.test(fragment)) fail(`${filename}：${message}`);
  }
  for (const meta of fragment.matchAll(/<meta\b[^>]*>/gi)) {
    const directive = attributeValue(meta[0], 'http-equiv');
    if (directive !== null && decodeHtmlEntities(directive).trim().toLowerCase() === 'refresh') {
      fail(`${filename}：禁止 meta refresh`);
    }
  }
  validateFragmentUrls(fragment, filename);
}

function normalizeSlide(fragment, filename) {
  const withoutComments = fragment.replace(/<!--[\s\S]*?-->/g, '').trim();
  validateFragmentSafety(withoutComments, filename);
  const tags = [...withoutComments.matchAll(/<\/?section\b[^>]*>/gi)];
  let depth = 0;
  let topLevelCount = 0;
  let openingTag = null;
  let topStart = -1;
  let topEnd = -1;
  for (const match of tags) {
    const closing = /^<\/section/i.test(match[0]);
    if (!closing) {
      if (depth === 0) {
        topLevelCount += 1;
        openingTag ??= match[0];
        topStart = topStart === -1 ? match.index : topStart;
      }
      depth += 1;
    } else {
      depth -= 1;
      if (depth < 0) fail(`${filename} 的 section 标签未配对`);
      if (depth === 0) topEnd = match.index + match[0].length;
    }
  }
  if (depth !== 0 || topLevelCount !== 1 || topStart < 0
      || withoutComments.slice(0, topStart).trim()
      || withoutComments.slice(topEnd).trim()) {
    fail(`${filename} 必须只包含一个顶层 <section class="slide">；允许其内部嵌套 section`);
  }
  if (!hasSlideClass(openingTag)) fail(`${filename} 的顶层 section 必须包含 class="slide"`);

  let slideId = extractAttribute(openingTag, 'data-slide-id');
  let normalized = withoutComments;
  let generatedId = false;
  if (!slideId) {
    slideId = slugFromFilename(filename);
    normalized = injectSectionAttribute(normalized, 'data-slide-id', slideId);
    generatedId = true;
  }
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slideId)) {
    fail(`${filename} 的 data-slide-id 无效：${slideId}`);
  }
  const updatedOpening = normalized.match(/^<section\b[^>]*>/i)?.[0] ?? '';
  if (!extractAttribute(updatedOpening, 'id')) {
    normalized = injectSectionAttribute(normalized, 'id', `slide-${slideId}`);
  }
  return { id: slideId, html: normalized, generatedId };
}

async function listSlideFiles(slidesDir, order) {
  let entries;
  try {
    entries = await readdir(slidesDir, { withFileTypes: true });
  } catch (error) {
    fail(`无法读取 slides.directory：${error.message}`);
  }
  const available = entries
    .filter((entry) => (entry.isFile() || entry.isSymbolicLink()) && entry.name.endsWith('.html'))
    .map((entry) => entry.name)
    .sort((a, b) => a.localeCompare(b, 'en'));
  if (!available.length) fail('src/slides 中没有 .html 页面片段');
  if (!order.length) return available;

  const availableSet = new Set(available);
  const missing = order.filter((name) => !availableSet.has(name));
  const unlisted = available.filter((name) => !order.includes(name));
  if (missing.length) fail(`slides.order 引用了不存在的文件：${missing.join(', ')}`);
  if (unlisted.length) fail(`slides.order 未列出以下页面：${unlisted.join(', ')}`);
  return order;
}

async function loadSlides(config, projectRoot) {
  const files = await listSlideFiles(config.slides.dir, config.slides.order);
  const slides = [];
  const ids = new Set();
  for (const filename of files) {
    const candidate = resolveInside(config.slides.dir, filename, `slide ${filename}`);
    const fullPath = await realContainedPath(config.slides.dir, candidate, `slide ${filename}`);
    if (!inside(projectRoot, fullPath)) fail(`slide ${filename} 真实路径位于项目之外`);
    const raw = await readFile(fullPath, 'utf8');
    const normalized = normalizeSlide(raw, filename);
    if (ids.has(normalized.id)) fail(`重复 data-slide-id：${normalized.id}`);
    ids.add(normalized.id);
    slides.push({
      ...normalized,
      filename,
      fullPath,
      source: path.relative(projectRoot, fullPath).replaceAll(path.sep, '/'),
      sourceHash: sha256(Buffer.from(raw, 'utf8')),
    });
  }
  return slides;
}

async function replaceAsync(input, expression, replacer) {
  const regex = new RegExp(expression.source, expression.flags.includes('g') ? expression.flags : `${expression.flags}g`);
  let cursor = 0;
  let output = '';
  for (const match of input.matchAll(regex)) {
    output += input.slice(cursor, match.index);
    output += await replacer(match);
    cursor = match.index + match[0].length;
  }
  return output + input.slice(cursor);
}

function splitResourceReference(reference) {
  const match = reference.match(/^([^?#]*)([?#][\s\S]*)?$/);
  return { pathname: match?.[1] ?? reference, suffix: match?.[2] ?? '' };
}

function isNonLocalReference(reference) {
  return /^(?:data:|blob:|https?:|\/\/|#|mailto:|tel:|javascript:)/i.test(normalizedUrlForPolicy(reference));
}

async function resourceDataUri(reference, {
  baseDir,
  allowedRoot,
  label,
  cache,
  embedded,
}) {
  ensureStaticReferenceAllowed(reference, label);
  if (isNonLocalReference(reference)) return reference;
  const { pathname: rawPath, suffix } = splitResourceReference(reference.trim());
  let decoded;
  try {
    decoded = decodeURIComponent(rawPath);
  } catch {
    fail(`${label} 包含无法解码的本地资源路径：${reference}`);
  }
  const resolved = decoded.startsWith('/')
    ? path.resolve(allowedRoot, `.${decoded}`)
    : path.resolve(baseDir, decoded);
  if (!inside(allowedRoot, resolved)) fail(`${label} 的本地资源越界：${reference}`);
  const actual = await realContainedPath(allowedRoot, resolved, `${label} 的本地资源`);
  const source = path.relative(allowedRoot, actual).replaceAll(path.sep, '/');
  let item = cache.byPath.get(actual);
  if (!item) {
    let bytes;
    try {
      const info = await stat(actual);
      if (!info.isFile()) fail(`${label} 的本地资源不是文件：${reference}`);
      bytes = await readFile(actual);
    } catch (error) {
      if (error instanceof DeckBuildError) throw error;
      fail(`${label} 的本地资源不存在：${reference} (${error.message})`);
    }
    const extension = normalizedMediaExtension(actual);
    const mime = MIME_TYPES.get(extension) ?? 'application/octet-stream';
    const digest = sha256(bytes);
    const identity = `${digest}\0${mime}\0${extension}`;
    item = cache.byContent.get(identity);
    if (!item) {
      const manifestEntry = {
        sources: new Set(),
        bytes: bytes.length,
        sha256: digest,
        mime,
        extension,
      };
      item = {
        bytes: bytes.length,
        sha256: digest,
        mime,
        extension,
        dataUri: `data:${mime};base64,${bytes.toString('base64')}`,
        manifestEntry,
      };
      cache.byContent.set(identity, item);
      embedded.push(manifestEntry);
    }
    cache.byPath.set(actual, item);
  }
  item.manifestEntry.sources.add(source);
  return `${item.dataUri}${suffix}`;
}

function normalizedMediaExtension(filePath) {
  const extension = path.extname(filePath).toLowerCase();
  return /^\.[a-z0-9]{1,16}$/.test(extension) ? extension : '.bin';
}

async function resourceBundleUrl(reference, {
  baseDir,
  allowedRoot,
  label,
  cache,
  copied,
  generatedFiles,
  publicPrefix,
}) {
  ensureStaticReferenceAllowed(reference, label);
  if (isNonLocalReference(reference)) return reference;
  const { pathname: rawPath, suffix } = splitResourceReference(reference.trim());
  let decoded;
  try {
    decoded = decodeURIComponent(rawPath);
  } catch {
    fail(`${label} 包含无法解码的本地资源路径：${reference}`);
  }
  const resolved = decoded.startsWith('/')
    ? path.resolve(allowedRoot, `.${decoded}`)
    : path.resolve(baseDir, decoded);
  if (!inside(allowedRoot, resolved)) fail(`${label} 的本地资源越界：${reference}`);
  const actual = await realContainedPath(allowedRoot, resolved, `${label} 的本地资源`);
  const source = path.relative(allowedRoot, actual).replaceAll(path.sep, '/');
  let item = cache.byPath.get(actual);
  if (!item) {
    let bytes;
    try {
      const info = await stat(actual);
      if (!info.isFile()) fail(`${label} 的本地资源不是文件：${reference}`);
      bytes = await readFile(actual);
    } catch (error) {
      if (error instanceof DeckBuildError) throw error;
      fail(`${label} 的本地资源不存在：${reference} (${error.message})`);
    }
    const digest = sha256(bytes);
    const extension = normalizedMediaExtension(actual);
    const mime = MIME_TYPES.get(extension) ?? 'application/octet-stream';
    const identity = `${digest}\0${mime}\0${extension}`;
    item = cache.byContent.get(identity);
    if (!item) {
      const outputName = `${digest}${extension}`;
      const outputPath = `assets/media/${outputName}`;
      const manifestEntry = {
        sources: new Set(),
        output: outputPath,
        bytes: bytes.length,
        sha256: digest,
        mime,
        extension,
      };
      item = {
        output: outputPath,
        outputName,
        bytes: bytes.length,
        sha256: digest,
        mime,
        extension,
        content: bytes,
        manifestEntry,
      };
      cache.byContent.set(identity, item);
      copied.push(manifestEntry);
      const existing = generatedFiles.get(outputPath);
      if (existing && sha256(existing) !== digest) fail(`输出媒体 hash 路径碰撞：${outputPath}`);
      generatedFiles.set(outputPath, bytes);
    }
    cache.byPath.set(actual, item);
  }
  item.manifestEntry.sources.add(source);
  return `${publicPrefix}${item.outputName}${suffix}`;
}

function mediaManifestEntries(entries, sortKey) {
  return entries
    .map(({ sources, ...entry }) => {
      const orderedSources = [...sources].sort((a, b) => a.localeCompare(b, 'en'));
      return { source: orderedSources[0], sources: orderedSources, ...entry };
    })
    .sort((a, b) => a[sortKey].localeCompare(b[sortKey], 'en'));
}

async function inlineCssResources(css, context) {
  let syntax;
  try {
    syntax = inspectCssResourceSyntax(css);
  } catch (error) {
    fail(`${context.label} CSS 无法安全解析：${error.message}`);
  }
  for (const resource of syntax) {
    if (resource.kind === 'at-rule' && resource.name === 'import') {
      fail(`${context.label} 不允许使用 @import；请把字体和样式本地化到单一 CSS`);
    }
    if (resource.kind === 'function' && resource.name === 'url' && resource.obfuscated) {
      fail(`${context.label} 不允许转义、注释或空白混淆的 CSS url()；请使用显式 url(...)`);
    }
    if (resource.kind === 'function' && resource.name !== 'url') {
      fail(`${context.label} 不支持 CSS ${resource.name}() 资源函数；请改为可审计的 url(...)`);
    }
  }
  return replaceAsync(css, /url\(\s*(?:(['"])(.*?)\1|([^)'"\s]+))\s*\)/gi, async (match) => {
    const resolver = context.resolver ?? resourceDataUri;
    const next = await resolver(match[2] ?? match[3], context);
    return `url("${next}")`;
  });
}

function escapeStyleAttribute(value, quote) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll(quote, quote === '"' ? '&quot;' : '&#39;');
}

function htmlTagEnd(html, start) {
  let quote = null;
  for (let index = start + 1; index < html.length; index += 1) {
    const character = html[index];
    if (quote) {
      if (character === quote) quote = null;
    } else if (character === '"' || character === "'") quote = character;
    else if (character === '>') return index;
  }
  fail('HTML 片段包含未闭合的标签');
}

async function rewriteTagStyleAttribute(tag, context) {
  return replaceAsync(
    tag,
    /(\sstyle\s*=\s*)(?:(["'])([\s\S]*?)\2|([^\s"'=<>`]+))/gi,
    async (match) => {
      const css = decodeHtmlEntities(match[3] ?? match[4] ?? '');
      const rewritten = await inlineCssResources(css, context);
      const quote = match[2] ?? '"';
      return `${match[1]}${quote}${escapeStyleAttribute(rewritten, quote)}${quote}`;
    },
  );
}

async function rewriteTagResourceAttributes(tag, context) {
  const tagName = tag.match(/^<\s*([A-Za-z][A-Za-z0-9:-]*)/)?.[1]?.toLowerCase();
  const allowed = tagName ? FETCH_RESOURCE_ATTRIBUTES[tagName] : null;
  if (!allowed?.length) return tag;
  return replaceAsync(
    tag,
    /(\s)([A-Za-z_:][A-Za-z0-9_.:-]*)(\s*=\s*)(?:(["'])([\s\S]*?)\4|([^\s"'=<>`]+))/g,
    async (match) => {
      const attribute = match[2].toLowerCase();
      if (!allowed.includes(attribute)) return match[0];
      const raw = decodeHtmlEntities(match[5] ?? match[6] ?? '');
      let rewritten;
      if (attribute === 'srcset' || attribute === 'imagesrcset') {
        const candidates = [];
        for (const candidate of parseSrcsetCandidates(raw)) {
          const url = await (context.resolver ?? resourceDataUri)(candidate.url, context);
          candidates.push(`${url}${candidate.descriptor ? ` ${candidate.descriptor}` : ''}`);
        }
        rewritten = candidates.join(', ');
      } else {
        rewritten = await (context.resolver ?? resourceDataUri)(raw, context);
      }
      const quote = match[4] ?? '"';
      return `${match[1]}${match[2]}${match[3]}${quote}${escapeStyleAttribute(rewritten, quote)}${quote}`;
    },
  );
}

async function inlineHtmlCssResources(html, context) {
  let output = '';
  let cursor = 0;
  const lower = html.toLowerCase();
  while (cursor < html.length) {
    const start = html.indexOf('<', cursor);
    if (start < 0) return output + html.slice(cursor);
    output += html.slice(cursor, start);
    if (html.startsWith('<!--', start)) {
      const close = html.indexOf('-->', start + 4);
      if (close < 0) fail('HTML 片段包含未闭合的注释');
      output += html.slice(start, close + 3);
      cursor = close + 3;
      continue;
    }
    const end = htmlTagEnd(html, start);
    const tag = html.slice(start, end + 1);
    const withResources = await rewriteTagResourceAttributes(tag, context);
    output += await rewriteTagStyleAttribute(withResources, context);
    cursor = end + 1;
    if (/^<style\b/i.test(tag)) {
      const closeStart = lower.indexOf('</style', cursor);
      if (closeStart < 0) fail('HTML 片段包含未闭合的 <style>');
      const closeEnd = htmlTagEnd(html, closeStart);
      output += await inlineCssResources(html.slice(cursor, closeStart), context);
      output += html.slice(closeStart, closeEnd + 1);
      cursor = closeEnd + 1;
    }
  }
  return output;
}

function parseSrcsetCandidates(value) {
  const candidates = [];
  let index = 0;
  while (index < value.length) {
    while (index < value.length && /[\s,]/.test(value[index])) index += 1;
    if (index >= value.length) break;

    const urlStart = index;
    // The HTML algorithm consumes the URL through the next ASCII whitespace.
    // This is what keeps commas inside data URLs and ordinary URL paths intact.
    while (index < value.length && !/\s/.test(value[index])) index += 1;
    let url = value.slice(urlStart, index);
    if (!url) fail(`srcset 候选缺少 URL：${value}`);

    // A trailing comma terminates a descriptor-less candidate. Strip only
    // trailing separators; commas inside the URL remain part of the URL.
    if (url.endsWith(',')) {
      url = url.replace(/,+$/, '');
      if (!url) fail(`srcset 候选缺少 URL：${value}`);
      candidates.push({ url, descriptor: '' });
      continue;
    }
    while (index < value.length && /\s/.test(value[index])) index += 1;
    const descriptorStart = index;
    let parentheses = 0;
    while (index < value.length) {
      const character = value[index];
      if (character === '(') parentheses += 1;
      else if (character === ')' && parentheses > 0) parentheses -= 1;
      else if (character === ',' && parentheses === 0) break;
      index += 1;
    }
    const descriptor = value.slice(descriptorStart, index).trim();
    candidates.push({ url, descriptor });
    if (value[index] === ',') index += 1;
  }
  return candidates;
}

async function inlineHtmlResources(html, context) {
  return inlineHtmlCssResources(html, context);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function replaceToken(template, token, value) {
  return template.replaceAll(`{{${token}}}`, String(value));
}

function aspectStyle(aspect, target) {
  const slideWidth = target.viewport.width;
  const slideHeight = target.viewport.height;
  return `:root{--deck-aspect-width:${aspect.width};--deck-aspect-height:${aspect.height};--deck-aspect-ratio:${aspect.ratio};--slide-aspect:${aspect.width}/${aspect.height};--slide-width:${slideWidth}px;--slide-height:${slideHeight}px;}`;
}

function styleTag(label, css, { assetMarker = true } = {}) {
  const safe = css.replace(/<\/style/gi, '<\\/style');
  const marker = assetMarker ? ` data-web-slide-asset="${escapeHtml(label)}"` : '';
  return `<style${marker}>\n${safe}\n</style>`;
}

function scriptTag(label, js, { module = false } = {}) {
  const safe = js.replace(/<\/script/gi, '<\\/script');
  return `<script${module ? ' type="module"' : ''} data-web-slide-asset="${escapeHtml(label)}">\n${safe}\n</script>`;
}

function detectRemoteDependencies(text, label, type = 'mixed') {
  const fetchElements = [
    'script', 'img', 'video', 'audio', 'source', 'iframe', 'link', 'object', 'embed',
    ...SVG_FETCH_ELEMENTS,
  ].join('|');
  const patterns = [];
  if (type === 'css' || type === 'mixed') {
    patterns.push(
      /@import\s+(?:url\()?\s*(["'])((?:https?:)?\/\/[^"']+)\1/gi,
      /url\(\s*(["']?)((?:https?:)?\/\/[^)'"\s]+)\1\s*\)/gi,
    );
  }
  if (type === 'js' || type === 'mixed') {
    patterns.push(/\b(?:import|fetch)\(\s*(["'])((?:https?:)?\/\/[^"']+)\1\s*\)/gi);
  }
  const results = [];
  for (const pattern of patterns) {
    for (const match of text.matchAll(pattern)) {
      const url = match[2];
      results.push({ file: label, url });
    }
  }
  if (type === 'html' || type === 'mixed') {
    const encodedAttributes = new RegExp(
      `<(?:${fetchElements})\\b[^>]*\\b(src|srcset|href|xlink:href|poster|data)\\s*=\\s*(["'])(.*?)\\2`,
      'gi',
    );
    for (const match of text.matchAll(encodedAttributes)) {
      const candidates = match[1].toLowerCase() === 'srcset'
        ? parseSrcsetCandidates(match[3] ?? '').map((candidate) => candidate.url)
        : [match[3] ?? ''];
      for (const raw of candidates) {
        const decoded = decodeHtmlEntities(raw).trim();
        if (/^(?:https?:)?\/\//i.test(decoded)) results.push({ file: label, url: decoded });
      }
    }
    for (const match of text.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style\s*>/gi)) {
      results.push(...detectRemoteDependencies(match[1], label, 'css'));
    }
    for (const match of text.matchAll(/<[^>]+\sstyle\s*=\s*(["'])([\s\S]*?)\1[^>]*>/gi)) {
      results.push(...detectRemoteDependencies(decodeHtmlEntities(match[2]), label, 'css'));
    }
    for (const match of text.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script\s*>/gi)) {
      results.push(...detectRemoteDependencies(match[1], label, 'js'));
    }
  }
  return [...new Map(results.map((item) => [`${item.file}\0${item.url}`, item])).values()];
}

async function loadCanonicalAsset(skillRoot, reference) {
  const normalized = normalizeAssetReference(reference, 'canonical asset');
  const candidate = path.resolve(skillRoot, normalized);
  const assetsRoot = await realpath(path.resolve(skillRoot, 'assets'));
  if (!inside(assetsRoot, candidate)) fail(`canonical asset 越界：${reference}`);
  const fullPath = await realContainedPath(assetsRoot, candidate, `canonical asset ${normalized}`);
  let content;
  try {
    content = await readFile(fullPath);
  } catch (error) {
    fail(`canonical asset 不存在：${normalized} (${error.message})`);
  }
  return { reference: normalized, name: path.basename(normalized), fullPath, content };
}

async function loadRuntimeAssets(skillRoot, mode) {
  const icon = await loadCanonicalAsset(skillRoot, 'assets/icon-runtime.js');
  const engine = await loadCanonicalAsset(skillRoot, 'assets/slide-engine.js');
  const result = [icon, engine];
  const engineText = engine.content.toString('utf8');
  if (mode === 'bundle' && /(?:\.\/)?motion\.min\.js/.test(engineText)) {
    result.push(await loadCanonicalAsset(skillRoot, 'assets/motion.min.js'));
  }
  return result;
}

function trustedDeliveryManifest(prior, expectedGenerator) {
  return prior?.schemaVersion === DELIVERY_SCHEMA_VERSION
    && prior?.generator?.name === expectedGenerator.name
    && Array.isArray(prior.files);
}

async function readPreviousManifest(outputDir, expectedGenerator, { force = false } = {}) {
  const manifestPath = await safeOutputTarget(outputDir, 'delivery-manifest.json');
  if (!existsSync(manifestPath)) return null;
  let prior;
  try {
    prior = JSON.parse(await readFile(manifestPath, 'utf8'));
  } catch {
    if (force) return null;
    fail('输出目录已有无法解析的 delivery-manifest.json；使用新的输出目录或确认后 --force');
  }
  if (!trustedDeliveryManifest(prior, expectedGenerator)) {
    if (force) return null;
    fail('输出目录已有不受信任的 delivery-manifest.json；拒绝接管既有文件，确认后可使用 --force');
  }
  return prior;
}

async function preflightManagedOutputs(outputDir, files, prior, { force = false } = {}) {
  const ownership = new Map((prior?.files ?? []).map((file) => [file.path, file]));
  const changed = [];
  const unchanged = [];
  const currentHashes = new Map();
  for (const [relative, content] of [...files.entries()].sort(([a], [b]) => a.localeCompare(b, 'en'))) {
    const target = await safeOutputTarget(outputDir, relative);
    if (!existsSync(target)) {
      changed.push(relative);
      currentHashes.set(relative, null);
      continue;
    }
    const current = await readFile(target);
    const currentHash = sha256(current);
    currentHashes.set(relative, currentHash);
    if (!force && relative !== 'delivery-manifest.json') {
      const owner = ownership.get(relative);
      if (!owner || !/^[a-f0-9]{64}$/.test(owner.sha256 ?? '')) {
        fail(`拒绝接管未由构建器管理的输出：${relative}；请换输出目录或确认后 --force`);
      }
      if (owner.sha256 !== currentHash) {
        fail(`拒绝覆盖用户修改过的输出：${relative}；请保留修改、换输出目录或确认后 --force`);
      }
    }
    if (current.length === asBuffer(content).length && currentHash === sha256(asBuffer(content))) {
      unchanged.push(relative);
      continue;
    }
    changed.push(relative);
  }
  return { changed, unchanged, currentHashes };
}

export async function commitStagedOutputs(
  outputDir,
  files,
  changedPaths,
  expectedCurrentHashes,
  { beforeRename = null } = {},
) {
  if (!changedPaths.length) return;
  const staging = await mkdtemp(path.join(outputDir, '.web-slide-stage-'));
  const orderedPaths = [
    ...changedPaths.filter((relative) => relative !== 'delivery-manifest.json'),
    ...changedPaths.filter((relative) => relative === 'delivery-manifest.json'),
  ];
  const committed = [];
  try {
    for (const relative of orderedPaths) {
      const staged = path.join(staging, ...relative.split('/'));
      await mkdir(path.dirname(staged), { recursive: true });
      await writeFile(staged, asBuffer(files.get(relative)));
    }
    // Recheck every destination before the first rename so a detected race leaves the prior build intact.
    for (const relative of orderedPaths) {
      const target = await safeOutputTarget(outputDir, relative);
      const expected = expectedCurrentHashes.get(relative);
      if (!existsSync(target)) {
        if (expected !== null) fail(`输出在提交前被删除：${relative}`);
      } else {
        const currentHash = sha256(await readFile(target));
        if (expected === null || currentHash !== expected) fail(`输出在提交前发生变化：${relative}`);
      }
    }
    for (const relative of orderedPaths) {
      const staged = path.join(staging, ...relative.split('/'));
      const target = await safeOutputTarget(outputDir, relative);
      if (beforeRename) await beforeRename(relative);
      const backup = path.join(staging, '.previous', ...relative.split('/'));
      const hadPrevious = existsSync(target);
      if (hadPrevious) {
        await mkdir(path.dirname(backup), { recursive: true });
        await rename(target, backup);
      }
      try {
        await rename(staged, target);
      } catch (error) {
        if (hadPrevious && existsSync(backup)) await rename(backup, target);
        throw error;
      }
      committed.push({ relative, target, backup, hadPrevious });
    }
  } catch (error) {
    const rollbackErrors = [];
    for (const entry of committed.reverse()) {
      try {
        if (existsSync(entry.target)) await rm(entry.target);
        if (entry.hadPrevious && existsSync(entry.backup)) await rename(entry.backup, entry.target);
      } catch (rollbackError) {
        rollbackErrors.push(`${entry.relative}: ${rollbackError.message}`);
      }
    }
    if (rollbackErrors.length) {
      fail(`构建提交失败，且回滚不完整：${rollbackErrors.join('; ')}；原始错误：${error.message}`);
    }
    throw error;
  } finally {
    await rm(staging, { recursive: true, force: true });
  }
}

async function prunePreviousBuild(outputDir, expectedPaths, expectedGenerator, prior) {
  if (!trustedDeliveryManifest(prior, expectedGenerator)) return [];
  const removed = [];
  for (const file of prior.files) {
    if (!file || typeof file.path !== 'string' || expectedPaths.has(file.path)) continue;
    if (!/^[a-f0-9]{64}$/.test(file.sha256 ?? '')) continue;
    if (!(file.path === 'index.html' || file.path.startsWith('assets/'))
        || file.path.includes('\\') || file.path.split('/').includes('..')) continue;
    const target = await safeOutputTarget(outputDir, file.path);
    if (!existsSync(target)) continue;
    try {
      const current = await readFile(target);
      if (file.sha256 && sha256(current) !== file.sha256) continue;
      await rm(target);
      removed.push(file.path);
    } catch {
      // A stale generated file that became unreadable is left untouched.
    }
  }
  return removed;
}

function renderSkeleton(skeleton, config, slides, styles, scripts) {
  if (!skeleton.includes('<!-- WEB_SLIDE_STYLES -->')
      || !skeleton.includes('<!-- WEB_SLIDE_SLIDES -->')
      || !skeleton.includes('<!-- WEB_SLIDE_SCRIPTS -->')) {
    fail('starter-components/index-skeleton.html 缺少构建标记');
  }
  let html = skeleton;
  const tokens = {
    LANG: escapeHtml(config.lang),
    THEME: escapeHtml(config.theme),
    ASPECT: escapeHtml(config.aspect.label),
    EVIDENCE_POLICY: escapeHtml(config.evidencePolicy),
    OFFLINE_REQUIRED: String(config.offlineRequired),
    DELIVERY_PROFILE: escapeHtml(config.deliveryProfile),
    TITLE: escapeHtml(config.title),
    SLIDE_COUNT: String(slides.length),
    DECK_WIDTH: String(config.target.viewport.width),
    DECK_HEIGHT: String(config.target.viewport.height),
    TARGET_BROWSER: escapeHtml(config.target.browser),
    TARGET_OS: escapeHtml(config.target.os),
  };
  for (const [token, value] of Object.entries(tokens)) html = replaceToken(html, token, value);
  html = html.replace('<!-- WEB_SLIDE_STYLES -->', styles);
  html = html.replace('<!-- WEB_SLIDE_SLIDES -->', slides.map((slide) => slide.html).join('\n\n'));
  html = html.replace('<!-- WEB_SLIDE_SCRIPTS -->', scripts);
  if (/{{[A-Z0-9_]+}}/.test(html)) fail('HTML 骨架仍有未解析占位符');
  return `${html.trim()}\n`;
}

function parseCli(argv) {
  const options = { projectDir: null, config: null, out: null, mode: null, force: false };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--help' || arg === '-h') return { ...options, help: true };
    if (arg === '--force') { options.force = true; continue; }
    if (arg === '--config' || arg === '--out' || arg === '--mode') {
      const value = argv[index + 1];
      if (!value || value.startsWith('--')) fail(`${arg} 缺少值`);
      options[arg.slice(2)] = value;
      index += 1;
      continue;
    }
    if (arg.startsWith('--')) fail(`未知参数：${arg}`);
    if (options.projectDir) fail(`只能指定一个 projectDir：${arg}`);
    options.projectDir = arg;
  }
  return options;
}

export async function buildDeck({
  projectDir = '.',
  config: configOverride = null,
  out = null,
  mode = null,
  force = false,
  skillRoot = DEFAULT_SKILL_ROOT,
} = {}) {
  let projectRoot;
  try {
    projectRoot = await realpath(path.resolve(projectDir));
  } catch (error) {
    fail(`项目目录不存在或无法解析真实路径：${error.message}`);
  }
  if (!(await stat(projectRoot)).isDirectory()) fail('projectDir 必须是目录');
  let canonicalSkillRoot;
  try {
    canonicalSkillRoot = await realpath(path.resolve(skillRoot));
  } catch (error) {
    fail(`技能目录不存在或无法解析真实路径：${error.message}`);
  }
  const configCandidate = configOverride
    ? resolveInside(projectRoot, configOverride, '--config')
    : path.join(projectRoot, 'deck.config.json');
  const configPath = await realContainedPath(projectRoot, configCandidate, 'deck.config.json');
  const rawConfig = await readJson(configPath, path.relative(projectRoot, configPath) || 'deck.config.json');
  const config = normalizeConfig(rawConfig, projectRoot, { out, mode });
  config.slides.dir = await realContainedPath(projectRoot, config.slides.dir, 'slides.directory', { kind: 'directory' });
  if (config.designSystem.path) {
    config.designSystem.path = await realContainedPath(projectRoot, config.designSystem.path, 'designSystem.stylesheet');
  }
  const sourceDirectories = [config.slides.dir];
  const sourceFiles = config.designSystem.path ? [config.designSystem.path] : [];
  config.output.dir = await prepareOutputDirectory(projectRoot, config.output.dir, sourceDirectories, sourceFiles);

  const { stylesheets } = await getThemeDefinition(config.theme, { skillRoot: canonicalSkillRoot });
  const themeAssets = [];
  for (const reference of stylesheets) themeAssets.push(await loadCanonicalAsset(canonicalSkillRoot, reference));
  const runtimeAssets = await loadRuntimeAssets(canonicalSkillRoot, config.output.mode);
  const slides = await loadSlides(config, projectRoot);
  const skeletonPath = await realContainedPath(canonicalSkillRoot, path.join(canonicalSkillRoot, 'starter-components', 'index-skeleton.html'), 'starter skeleton');
  const packagePath = await realContainedPath(canonicalSkillRoot, path.join(canonicalSkillRoot, 'package.json'), 'package.json');
  const skeleton = await readFile(skeletonPath, 'utf8');
  const packageInfo = await readJson(packagePath, 'package.json');

  let designSystemAsset = null;
  if (config.designSystem.path) {
    try {
      designSystemAsset = {
        reference: config.designSystem.reference,
        name: 'design-system.css',
        fullPath: config.designSystem.path,
        content: await readFile(config.designSystem.path),
      };
    } catch (error) {
      fail(`无法读取 designSystem.stylesheet：${error.message}`);
    }
  }

  const canonicalRemote = [
    ...themeAssets.flatMap((asset) => detectRemoteDependencies(asset.content.toString('utf8'), asset.reference, 'css')),
    ...runtimeAssets.flatMap((asset) => detectRemoteDependencies(asset.content.toString('utf8'), asset.reference, 'js')),
  ];
  if (canonicalRemote.length) {
    fail(`canonical assets 包含远程运行时依赖：${canonicalRemote.map((item) => `${item.file} -> ${item.url}`).join(', ')}`);
  }

  const generatedFiles = new Map();
  const embeddedAssets = [];
  const embeddedCache = { byPath: new Map(), byContent: new Map() };
  const copiedAssets = [];
  const copiedCache = { byPath: new Map(), byContent: new Map() };
  let outputSlides = slides;
  let styleMarkup;
  let scriptMarkup;
  if (config.output.mode === 'bundle') {
    outputSlides = [];
    for (const slide of slides) {
      outputSlides.push({
        ...slide,
        html: await inlineHtmlResources(slide.html, {
          baseDir: path.dirname(slide.fullPath),
          allowedRoot: projectRoot,
          label: slide.source,
          cache: copiedCache,
          copied: copiedAssets,
          generatedFiles,
          publicPrefix: './assets/media/',
          resolver: resourceBundleUrl,
        }),
      });
    }
    const linkedStyles = [];
    for (const asset of themeAssets) {
      linkedStyles.push({
        ...asset,
        content: Buffer.from(await inlineCssResources(asset.content.toString('utf8'), {
          baseDir: path.dirname(asset.fullPath),
          allowedRoot: canonicalSkillRoot,
          label: asset.reference,
          cache: copiedCache,
          copied: copiedAssets,
          generatedFiles,
          publicPrefix: './media/',
          resolver: resourceBundleUrl,
        }), 'utf8'),
      });
    }
    if (designSystemAsset) {
      linkedStyles.push({
        ...designSystemAsset,
        content: Buffer.from(await inlineCssResources(designSystemAsset.content.toString('utf8'), {
          baseDir: path.dirname(designSystemAsset.fullPath),
          allowedRoot: projectRoot,
          label: designSystemAsset.reference,
          cache: copiedCache,
          copied: copiedAssets,
          generatedFiles,
          publicPrefix: './media/',
          resolver: resourceBundleUrl,
        }), 'utf8'),
      });
    }
    styleMarkup = [
      ...linkedStyles.map((asset) => `<link rel="stylesheet" href="./assets/${escapeHtml(asset.name)}">`),
      styleTag('deck-aspect', aspectStyle(config.aspect, config.target), { assetMarker: false }),
    ].join('\n  ');
    scriptMarkup = [
      '<script src="./assets/icon-runtime.js"></script>',
      '<script type="module" src="./assets/slide-engine.js"></script>',
    ].join('\n  ');
    for (const asset of [...linkedStyles, ...runtimeAssets]) {
      const relative = `assets/${asset.name}`;
      const existing = generatedFiles.get(relative);
      if (existing && sha256(existing) !== sha256(asset.content)) fail(`输出资产重名且内容不同：${relative}`);
      generatedFiles.set(relative, asset.content);
    }
  } else {
    outputSlides = [];
    for (const slide of slides) {
      outputSlides.push({
        ...slide,
        html: await inlineHtmlResources(slide.html, {
          baseDir: path.dirname(slide.fullPath),
          allowedRoot: projectRoot,
          label: slide.source,
          cache: embeddedCache,
          embedded: embeddedAssets,
        }),
      });
    }
    const inlineThemeStyles = [];
    for (const asset of themeAssets) {
      inlineThemeStyles.push(styleTag(
        asset.reference,
        await inlineCssResources(asset.content.toString('utf8'), {
          baseDir: path.dirname(asset.fullPath),
          allowedRoot: canonicalSkillRoot,
          label: asset.reference,
          cache: embeddedCache,
          embedded: embeddedAssets,
        }),
      ));
    }
    const inlineDesignSystem = designSystemAsset
      ? styleTag(
        designSystemAsset.reference,
        await inlineCssResources(designSystemAsset.content.toString('utf8'), {
          baseDir: path.dirname(designSystemAsset.fullPath),
          allowedRoot: projectRoot,
          label: designSystemAsset.reference,
          cache: embeddedCache,
          embedded: embeddedAssets,
        }),
        { assetMarker: false },
      )
      : null;
    styleMarkup = [
      ...inlineThemeStyles,
      ...(inlineDesignSystem ? [inlineDesignSystem] : []),
      styleTag('deck-aspect', aspectStyle(config.aspect, config.target), { assetMarker: false }),
    ].join('\n  ');
    const icon = runtimeAssets.find((asset) => asset.name === 'icon-runtime.js');
    const engine = runtimeAssets.find((asset) => asset.name === 'slide-engine.js');
    scriptMarkup = [
      scriptTag(icon.reference, icon.content.toString('utf8')),
      scriptTag(engine.reference, standaloneEngineSource(engine.content.toString('utf8')), { module: true }),
    ].join('\n  ');
  }

  const html = renderSkeleton(skeleton, config, outputSlides, styleMarkup, scriptMarkup);
  const externalDependencies = [
    ...detectRemoteDependencies(html, 'index.html', 'html'),
    ...(designSystemAsset ? detectRemoteDependencies(designSystemAsset.content.toString('utf8'), designSystemAsset.reference, 'css') : []),
  ];
  const externalDependencyUrls = [...new Set(externalDependencies.map((item) => item.url))].sort();
  if ((config.offlineRequired || config.output.mode === 'standalone') && externalDependencies.length) {
    const reason = config.output.mode === 'standalone' ? 'standalone 必须自包含' : 'offlineRequired=true';
    fail(`${reason}，但发现远程运行时依赖：${externalDependencies.map((item) => `${item.file} -> ${item.url}`).join(', ')}`);
  }
  generatedFiles.set('index.html', Buffer.from(html, 'utf8'));

  const generator = {
    name: packageInfo.name ?? 'tool-web-slide',
    version: packageInfo.version ?? 'unknown',
  };
  const fileEntries = [...generatedFiles.entries()]
    .sort(([a], [b]) => a.localeCompare(b, 'en'))
    .map(([relative, content]) => ({
      path: relative,
      bytes: asBuffer(content).length,
      sha256: sha256(asBuffer(content)),
    }));
  const manifest = {
    schemaVersion: DELIVERY_SCHEMA_VERSION,
    generator,
    mode: config.output.mode,
    theme: config.theme,
    aspect: config.aspect.label,
    evidencePolicy: config.evidencePolicy,
    offlineRequired: config.offlineRequired,
    deliveryProfile: config.deliveryProfile,
    requiredGates: config.requiredGates,
    target: config.target,
    externalDependencies: externalDependencyUrls.length,
    externalDependencyUrls,
    embeddedAssets: mediaManifestEntries(embeddedAssets, 'source'),
    copiedAssets: mediaManifestEntries(copiedAssets, 'output'),
    slides: slides.map((slide, index) => ({
      index: index + 1,
      id: slide.id,
      source: slide.source,
      sourceSha256: slide.sourceHash,
      generatedId: slide.generatedId,
    })),
    files: fileEntries,
  };
  const manifestText = `${JSON.stringify(manifest, null, 2)}\n`;
  const manifestRelative = 'delivery-manifest.json';
  const commitFiles = new Map(generatedFiles);
  commitFiles.set(manifestRelative, Buffer.from(manifestText, 'utf8'));
  const previousManifest = await readPreviousManifest(config.output.dir, generator, { force });
  const preflight = await preflightManagedOutputs(config.output.dir, commitFiles, previousManifest, { force });
  await commitStagedOutputs(config.output.dir, commitFiles, preflight.changed, preflight.currentHashes);
  const expectedPaths = new Set(generatedFiles.keys());
  const removed = await prunePreviousBuild(config.output.dir, expectedPaths, generator, previousManifest);
  const changed = preflight.changed;
  const unchanged = preflight.unchanged;

  return {
    projectRoot,
    outputDir: config.output.dir,
    mode: config.output.mode,
    theme: config.theme,
    aspect: config.aspect.label,
    slideCount: slides.length,
    changed,
    unchanged,
    removed,
    generatedIds: slides.filter((slide) => slide.generatedId).map((slide) => ({ file: slide.source, id: slide.id })),
    manifest,
  };
}

function usage() {
  return `Usage: node scripts/build-deck.mjs [projectDir] [options]\n\nOptions:\n  --config <path>       Config path inside project (default: deck.config.json)\n  --out <path>          Override output.dir for this build\n  --mode <mode>         bundle or standalone\n  --force               Allow replacing unmanaged or modified output files\n  -h, --help            Show this help\n\ndeck.config.json enums:\n  deliveryProfile       ${DELIVERY_PROFILES.join('|')}\n  target.browser        ${TARGET_BROWSERS.join('|')}\n  target.os             ${TARGET_OSES.join('|')}`;
}

async function main() {
  const options = parseCli(process.argv.slice(2));
  if (options.help) {
    process.stdout.write(`${usage()}\n`);
    return;
  }
  const result = await buildDeck({
    projectDir: options.projectDir ?? '.',
    config: options.config,
    out: options.out,
    mode: options.mode,
    force: options.force,
  });
  process.stdout.write(`${JSON.stringify({
    ok: true,
    outputDir: result.outputDir,
    mode: result.mode,
    slides: result.slideCount,
    changed: result.changed,
    unchanged: result.unchanged,
    removed: result.removed,
    generatedIds: result.generatedIds,
  }, null, 2)}\n`);
}

const isMain = process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;
if (isMain) {
  main().catch((error) => {
    process.stderr.write(`build-deck: ${error.message}\n`);
    process.exitCode = 1;
  });
}

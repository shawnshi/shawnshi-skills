import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, isAbsolute, join, normalize, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  DELIVERY_PROFILES as CONTRACT_DELIVERY_PROFILES,
  FETCH_RESOURCE_ATTRIBUTES,
  TARGET_BROWSERS,
  TARGET_OSES,
  decodeCssEscapes,
  requiredGatesFor,
  standaloneEngineSource,
} from './delivery-contract.mjs';

export const REPORT_SCHEMA_VERSION = '1.0.0';
export const VALIDATOR_VERSION = '1.0.0';

const MODULE_DIR = dirname(fileURLToPath(import.meta.url));
const DEFAULT_SKILL_ROOT = resolve(MODULE_DIR, '..', '..');
const VOID_ELEMENTS = new Set([
  'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
  'param', 'source', 'track', 'wbr',
]);
const OPTIONAL_END_TAGS = new Set([
  'dd', 'dt', 'li', 'option', 'p', 'tbody', 'td', 'tfoot', 'th', 'thead', 'tr',
]);
const SAFE_INLINE_SCRIPT_TYPES = new Set([
  'application/json', 'application/ld+json',
]);
const TRUSTED_RUNTIME_SCRIPTS = new Set(['assets/icon-runtime.js', 'assets/slide-engine.js']);

export class DeckEnvironmentError extends Error {
  constructor(message, code = 'ENVIRONMENT_ERROR') {
    super(message);
    this.name = 'DeckEnvironmentError';
    this.code = code;
  }
}

function positionAt(source, index) {
  const before = source.slice(0, Math.max(0, index));
  const lines = before.split('\n');
  return { line: lines.length, column: lines.at(-1).length + 1, offset: index };
}

function makeNode(type, properties = {}) {
  return { type, parent: null, children: [], ...properties };
}

function appendChild(parent, child) {
  child.parent = parent;
  parent.children.push(child);
}

function parseStartTag(raw, source, offset, parserIssues) {
  let cursor = 1;
  while (/\s/.test(raw[cursor] ?? '')) cursor += 1;
  const nameStart = cursor;
  while (/[A-Za-z0-9:-]/.test(raw[cursor] ?? '')) cursor += 1;
  const tagName = raw.slice(nameStart, cursor).toLowerCase();
  const attributes = new Map();
  const attributeLocations = new Map();

  while (cursor < raw.length) {
    while (/\s/.test(raw[cursor] ?? '')) cursor += 1;
    if (cursor >= raw.length || raw[cursor] === '>' || raw.slice(cursor, cursor + 2) === '/>') break;
    const attrStart = cursor;
    while (cursor < raw.length && !/[\s=/>]/.test(raw[cursor])) cursor += 1;
    const rawName = raw.slice(attrStart, cursor);
    if (!rawName) {
      cursor += 1;
      continue;
    }
    const attrName = rawName.toLowerCase();
    while (/\s/.test(raw[cursor] ?? '')) cursor += 1;
    let value = '';
    if (raw[cursor] === '=') {
      cursor += 1;
      while (/\s/.test(raw[cursor] ?? '')) cursor += 1;
      const quote = raw[cursor];
      if (quote === '"' || quote === "'") {
        cursor += 1;
        const valueStart = cursor;
        while (cursor < raw.length && raw[cursor] !== quote) cursor += 1;
        value = raw.slice(valueStart, cursor);
        if (raw[cursor] === quote) cursor += 1;
      } else {
        const valueStart = cursor;
        while (cursor < raw.length && !/[\s>]/.test(raw[cursor])) cursor += 1;
        value = raw.slice(valueStart, cursor).replace(/\/$/, '');
      }
    }
    const location = positionAt(source, offset + attrStart);
    if (attributes.has(attrName)) {
      parserIssues.push({
        severity: 'error',
        code: 'HTML_DUPLICATE_ATTRIBUTE',
        message: `Attribute "${attrName}" is repeated on <${tagName}>.`,
        location,
      });
    }
    attributes.set(attrName, value);
    attributeLocations.set(attrName, location);
  }
  return { tagName, attributes, attributeLocations };
}

function findTagEnd(source, start) {
  let quote = null;
  for (let cursor = start + 1; cursor < source.length; cursor += 1) {
    const char = source[cursor];
    if (quote) {
      if (char === quote) quote = null;
      continue;
    }
    if (char === '"' || char === "'") quote = char;
    else if (char === '>') return cursor;
  }
  return -1;
}

/** Build a DOM-like tree so comments and string fragments never satisfy gates. */
export function parseHtml(source, file = '<memory>') {
  const root = makeNode('document', { file, location: { line: 1, column: 1, offset: 0 } });
  const stack = [root];
  const issues = [];
  let cursor = 0;
  while (cursor < source.length) {
    if (source[cursor] !== '<') {
      const next = source.indexOf('<', cursor);
      const end = next === -1 ? source.length : next;
      appendChild(stack.at(-1), makeNode('text', { value: source.slice(cursor, end), location: positionAt(source, cursor) }));
      cursor = end;
      continue;
    }
    if (source.startsWith('<!--', cursor)) {
      const end = source.indexOf('-->', cursor + 4);
      if (end === -1) {
        issues.push({ severity: 'error', code: 'HTML_UNCLOSED_COMMENT', message: 'HTML comment is not closed.', location: positionAt(source, cursor) });
        break;
      }
      appendChild(stack.at(-1), makeNode('comment', { value: source.slice(cursor + 4, end), location: positionAt(source, cursor) }));
      cursor = end + 3;
      continue;
    }
    if (/^<!doctype\b/i.test(source.slice(cursor, cursor + 12))) {
      const end = findTagEnd(source, cursor);
      if (end === -1) break;
      appendChild(stack.at(-1), makeNode('doctype', { location: positionAt(source, cursor) }));
      cursor = end + 1;
      continue;
    }
    if (source.startsWith('</', cursor)) {
      const end = findTagEnd(source, cursor);
      if (end === -1) {
        issues.push({ severity: 'error', code: 'HTML_UNCLOSED_END_TAG', message: 'Closing tag is not terminated.', location: positionAt(source, cursor) });
        break;
      }
      const closeName = source.slice(cursor + 2, end).trim().split(/\s+/)[0]?.toLowerCase();
      let matchIndex = -1;
      for (let index = stack.length - 1; index > 0; index -= 1) {
        if (stack[index].tagName === closeName) { matchIndex = index; break; }
      }
      if (matchIndex === -1) {
        issues.push({ severity: 'error', code: 'HTML_UNMATCHED_END_TAG', message: `Closing tag </${closeName}> has no matching start tag.`, location: positionAt(source, cursor) });
      } else {
        for (let index = stack.length - 1; index > matchIndex; index -= 1) {
          const unclosed = stack[index];
          if (!OPTIONAL_END_TAGS.has(unclosed.tagName)) {
            issues.push({ severity: 'error', code: 'HTML_MISNESTED_TAG', message: `<${unclosed.tagName}> is implicitly closed by </${closeName}>.`, location: unclosed.location });
          }
        }
        stack.length = matchIndex;
      }
      cursor = end + 1;
      continue;
    }
    if (source.startsWith('<!', cursor) || source.startsWith('<?', cursor)) {
      const end = findTagEnd(source, cursor);
      if (end === -1) break;
      cursor = end + 1;
      continue;
    }
    const end = findTagEnd(source, cursor);
    if (end === -1) {
      issues.push({ severity: 'error', code: 'HTML_UNCLOSED_START_TAG', message: 'Start tag is not terminated.', location: positionAt(source, cursor) });
      break;
    }
    const raw = source.slice(cursor, end + 1);
    const { tagName, attributes, attributeLocations } = parseStartTag(raw, source, cursor, issues);
    if (!tagName) {
      issues.push({ severity: 'error', code: 'HTML_INVALID_START_TAG', message: 'Invalid start tag.', location: positionAt(source, cursor) });
      cursor = end + 1;
      continue;
    }
    const element = makeNode('element', { tagName, attributes, attributeLocations, location: positionAt(source, cursor) });
    appendChild(stack.at(-1), element);
    const selfClosing = /\/\s*>$/.test(raw) || VOID_ELEMENTS.has(tagName);
    cursor = end + 1;
    if (!selfClosing) {
      stack.push(element);
      if (tagName === 'script' || tagName === 'style') {
        const closeStart = source.toLowerCase().indexOf(`</${tagName}`, cursor);
        if (closeStart !== -1) {
          appendChild(element, makeNode('text', { value: source.slice(cursor, closeStart), location: positionAt(source, cursor) }));
          cursor = closeStart;
        }
      }
    }
  }
  for (let index = stack.length - 1; index > 0; index -= 1) {
    const unclosed = stack[index];
    if (!OPTIONAL_END_TAGS.has(unclosed.tagName)) {
      issues.push({ severity: 'error', code: 'HTML_UNCLOSED_ELEMENT', message: `<${unclosed.tagName}> is not closed.`, location: unclosed.location });
    }
  }
  return { root, issues };
}

function walk(node, visit) {
  visit(node);
  for (const child of node.children ?? []) walk(child, visit);
}

function elements(root, predicate = () => true) {
  const result = [];
  walk(root, (node) => { if (node.type === 'element' && predicate(node)) result.push(node); });
  return result;
}

function descendants(node, predicate = () => true) {
  const result = [];
  for (const child of node.children ?? []) {
    walk(child, (candidate) => { if (candidate.type === 'element' && predicate(candidate)) result.push(candidate); });
  }
  return result;
}

function getAttr(node, name) { return node?.attributes?.get(name.toLowerCase()); }
function hasAttr(node, name) { return node?.attributes?.has(name.toLowerCase()) ?? false; }
function classTokens(node) { return (getAttr(node, 'class') ?? '').split(/\s+/).filter(Boolean); }
function hasClass(node, className) { return classTokens(node).includes(className); }

function textContent(node) {
  let value = '';
  walk(node, (candidate) => { if (candidate.type === 'text') value += candidate.value; });
  return value.replace(/\s+/g, ' ').trim();
}

function rawTextContent(node) {
  let value = '';
  walk(node, (candidate) => { if (candidate.type === 'text') value += candidate.value; });
  return value;
}

function normalizedAssetText(value) {
  return value.replace(/\r\n?/g, '\n').trim();
}

function digestText(value) {
  return createHash('sha256').update(normalizedAssetText(value)).digest('hex');
}

function remoteStrings(value, found = []) {
  if (typeof value === 'string' && /^(?:https?:)?\/\//i.test(value.trim())) found.push(value.trim());
  else if (Array.isArray(value)) value.forEach((item) => remoteStrings(item, found));
  else if (value && typeof value === 'object') Object.values(value).forEach((item) => remoteStrings(item, found));
  return found;
}

function evidencePlaceholder(value) {
  return /^(?:tbd|todo|unknown|n\/?a|待补充|待核验|待定|未知)$/i.test(value.trim());
}

function validSource(value) {
  return Boolean(value?.trim()) && !evidencePlaceholder(value);
}

function validSourceDate(value) {
  return Boolean(value?.trim()) && !evidencePlaceholder(value) && /(?:19|20)\d{2}/.test(value);
}

function nearestSlide(node) {
  let current = node;
  while (current) {
    if (current.type === 'element' && current.tagName === 'section' && hasClass(current, 'slide')) return current;
    current = current.parent;
  }
  return null;
}

function issueFor(node, severity, code, message, extra = {}) {
  const slide = nearestSlide(node);
  return {
    severity, code, message,
    location: {
      ...(node?.location ?? { line: 1, column: 1 }),
      ...(slide ? { slideId: getAttr(slide, 'data-slide-id') || undefined } : {}),
      ...extra,
    },
  };
}

function stripCssComments(css) {
  let output = '';
  let cursor = 0;
  while (cursor < css.length) {
    if (css[cursor] === '/' && css[cursor + 1] === '*') {
      const end = css.indexOf('*/', cursor + 2);
      if (end === -1) return output;
      output += ' '.repeat(end + 2 - cursor);
      cursor = end + 2;
    } else output += css[cursor++];
  }
  return output;
}

function scanBalancedCss(css, start, open = '(', close = ')') {
  let depth = 0;
  let quote = null;
  for (let cursor = start; cursor < css.length; cursor += 1) {
    const char = css[cursor];
    if (quote) {
      if (char === '\\') cursor += 1;
      else if (char === quote) quote = null;
      continue;
    }
    if (char === '"' || char === "'") quote = char;
    else if (char === open) depth += 1;
    else if (char === close && --depth === 0) return cursor;
  }
  return -1;
}

export function scanCss(css, file = '<inline>') {
  const clean = decodeCssEscapes(stripCssComments(css));
  const classes = new Set();
  const classDeclarations = new Map();
  const definitions = new Set();
  const uses = [];
  const urls = [];
  const imports = [];
  for (let cursor = 0; cursor < clean.length;) {
    if (clean[cursor] === '"' || clean[cursor] === "'") {
      const quote = clean[cursor++];
      while (cursor < clean.length && clean[cursor] !== quote) {
        if (clean[cursor] === '\\') cursor += 1;
        cursor += 1;
      }
      cursor += 1;
      continue;
    }
    if (clean.slice(cursor, cursor + 4).toLowerCase() === 'var(') {
      const end = scanBalancedCss(clean, cursor + 3);
      const inside = end === -1 ? clean.slice(cursor + 4) : clean.slice(cursor + 4, end);
      const match = inside.match(/^\s*(--[A-Za-z0-9_-]+)\s*(,([\s\S]*))?$/);
      if (match) uses.push({ name: match[1], hasFallback: Boolean(match[2]), file, ...positionAt(clean, cursor) });
      cursor = end === -1 ? clean.length : end + 1;
      continue;
    }
    if (clean.slice(cursor, cursor + 4).toLowerCase() === 'url(') {
      const end = scanBalancedCss(clean, cursor + 3);
      let value = end === -1 ? clean.slice(cursor + 4) : clean.slice(cursor + 4, end);
      value = value.trim().replace(/^(['"])([\s\S]*)\1$/, '$2').trim();
      urls.push({ value, file, ...positionAt(clean, cursor) });
      cursor = end === -1 ? clean.length : end + 1;
      continue;
    }
    cursor += 1;
  }
  for (const match of clean.matchAll(/(^|[;{]\s*)(--[A-Za-z0-9_-]+)\s*:/gm)) definitions.add(match[2]);
  for (const match of clean.matchAll(/@import\s+(?:url\(\s*)?["']([^"']+)["']\s*\)?/gi)) {
    imports.push({ value: match[1], file, ...positionAt(clean, match.index) });
  }
  for (const imageSet of clean.matchAll(/(?:-webkit-)?image-set\s*\(/gi)) {
    const openIndex = imageSet.index + imageSet[0].lastIndexOf('(');
    const end = scanBalancedCss(clean, openIndex);
    if (end === -1) continue;
    const inside = clean.slice(openIndex + 1, end);
    let start = 0;
    let depth = 0;
    let quote = null;
    const candidates = [];
    for (let cursor = 0; cursor <= inside.length; cursor += 1) {
      const char = inside[cursor];
      if (quote) {
        if (char === '\\') cursor += 1;
        else if (char === quote) quote = null;
        continue;
      }
      if (char === '"' || char === "'") quote = char;
      else if (char === '(') depth += 1;
      else if (char === ')' && depth > 0) depth -= 1;
      else if ((char === ',' && depth === 0) || cursor === inside.length) {
        candidates.push(inside.slice(start, cursor).trim());
        start = cursor + 1;
      }
    }
    for (const candidate of candidates) {
      const direct = candidate.match(/^(["'])(.*?)\1/);
      if (direct) urls.push({ value: direct[2], file, ...positionAt(clean, imageSet.index) });
    }
  }
  // A declared component needs a real declaration; `.foo {}` is not an implementation.
  for (const rule of clean.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selector = rule[1].trim();
    if (!selector || selector.startsWith('@')) continue;
    const substantive = /(?:^|;)\s*(?:--)?[A-Za-z_-][A-Za-z0-9_-]*\s*:/.test(rule[2]);
    for (const match of selector.matchAll(/\.(-?[_A-Za-z]+[_A-Za-z0-9-]*)/g)) {
      classDeclarations.set(match[1], (classDeclarations.get(match[1]) ?? false) || substantive);
    }
  }
  let preludeStart = 0;
  let quote = null;
  for (let cursor = 0; cursor < clean.length; cursor += 1) {
    const char = clean[cursor];
    if (quote) {
      if (char === '\\') cursor += 1;
      else if (char === quote) quote = null;
      continue;
    }
    if (char === '"' || char === "'") { quote = char; continue; }
    if (char === ';' || char === '}') preludeStart = cursor + 1;
    if (char !== '{') continue;
    const prelude = clean.slice(preludeStart, cursor).trim();
    if (prelude && !prelude.startsWith('@')) {
      for (const match of prelude.matchAll(/\.(-?[_A-Za-z]+[_A-Za-z0-9-]*)/g)) classes.add(match[1]);
    }
    preludeStart = cursor + 1;
  }
  return { classes, classDeclarations, definitions, uses, urls, imports };
}

const SECURITY_ENTITY_MAP = new Map([
  ['amp', '&'], ['colon', ':'], ['tab', '\t'], ['newline', '\n'], ['sol', '/'], ['bsol', '\\'],
  ['period', '.'], ['quest', '?'], ['num', '#'], ['semi', ';'], ['equals', '='],
  ['lpar', '('], ['rpar', ')'], ['apos', "'"], ['quot', '"'],
]);

function decodeHtmlEntities(value) {
  return String(value)
    .replace(/&#(?:x([0-9a-f]+)|([0-9]+));?/gi, (match, hex, decimal) => {
      const codePoint = Number.parseInt(hex ?? decimal, hex ? 16 : 10);
      try { return codePoint > 0 && codePoint <= 0x10ffff ? String.fromCodePoint(codePoint) : match; }
      catch { return match; }
    })
    .replace(/&(amp|colon|tab|newline|sol|bsol|period|quest|num|semi|equals|lpar|rpar|apos|quot);?/gi,
      (match, name) => SECURITY_ENTITY_MAP.get(name.toLowerCase()) ?? match);
}

function sanitizeReference(value) {
  return decodeHtmlEntities(value).trim().replace(/^(['"])([\s\S]*)\1$/, '$2').trim();
}

function schemeComparable(value) {
  return sanitizeReference(value).replace(/[\u0000-\u0020\u007f]+/g, '');
}

function isRemoteReference(value) { return /^(?:https?:)?\/\//i.test(schemeComparable(value)); }
function isIgnoredReference(value) { return !value || /^(?:about:|mailto:|tel:|#)/i.test(schemeComparable(value)); }
function stripQueryAndFragment(value) { return value.split('#', 1)[0].split('?', 1)[0]; }

function resolveLocalReference(value, baseDir, deckRoot) {
  const clean = stripQueryAndFragment(sanitizeReference(value));
  if (!clean) return { ignored: true };
  let decoded;
  try { decoded = decodeURIComponent(clean); }
  catch { return { error: `Resource path is not valid URI encoding: ${value}` }; }
  if (isAbsolute(decoded)) return { absolute: true, path: normalize(decoded) };
  const absolute = resolve(baseDir, decoded);
  const relativePath = relative(deckRoot, absolute);
  return {
    path: absolute,
    relativePath: relativePath.split('\\').join('/'),
    outside: relativePath === '..' || relativePath.startsWith('../') || relativePath.startsWith('..\\'),
  };
}

// Implements the URL-token portion of the HTML srcset algorithm. In
// particular, commas inside data: URLs are URL data, not candidate separators.
export function srcsetCandidates(value) {
  const candidates = [];
  let cursor = 0;
  while (cursor < value.length) {
    while (cursor < value.length && /[\t\n\f\r ,]/.test(value[cursor])) cursor += 1;
    if (cursor >= value.length) break;
    const start = cursor;
    while (cursor < value.length && !/[\t\n\f\r ]/.test(value[cursor])) cursor += 1;
    let url = value.slice(start, cursor);
    let endedWithComma = false;
    while (url.endsWith(',')) {
      endedWithComma = true;
      url = url.slice(0, -1);
    }
    if (url) candidates.push(url);
    if (endedWithComma) continue;

    // Consume descriptors until a top-level comma. Parentheses are permitted
    // by the grammar and may themselves contain commas.
    let parenDepth = 0;
    while (cursor < value.length) {
      const char = value[cursor];
      if (char === '(') parenDepth += 1;
      else if (char === ')' && parenDepth > 0) parenDepth -= 1;
      else if (char === ',' && parenDepth === 0) { cursor += 1; break; }
      cursor += 1;
    }
  }
  return candidates;
}
function normalizeHref(value) { return stripQueryAndFragment(value).replace(/^\.\//, '').replace(/\\/g, '/'); }

function snapshotLedgerFile(deckRoot, deckRootReal, relativePath) {
  if (typeof relativePath !== 'string' || !relativePath || relativePath.includes('\\')
      || relativePath.startsWith('/') || /^[A-Za-z]:/.test(relativePath)
      || relativePath.split('/').some((part) => !part || part === '.' || part === '..')) return null;
  const filePath = resolve(deckRoot, ...relativePath.split('/'));
  const lexicalRelative = relative(deckRoot, filePath);
  if (lexicalRelative === '..' || lexicalRelative.startsWith('../') || lexicalRelative.startsWith('..\\')) return null;
  if (!existsSync(filePath)) return null;
  const info = lstatSync(filePath);
  if (info.isSymbolicLink() || !info.isFile()) return null;
  const physicalRelative = relative(deckRootReal, realpathSync(filePath));
  if (physicalRelative === '..' || physicalRelative.startsWith('../') || physicalRelative.startsWith('..\\')) return null;
  const bytes = readFileSync(filePath);
  return { path: relativePath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') };
}

function captureValidationSnapshot(input) {
  const deckRoot = dirname(input);
  const deckRootReal = realpathSync(deckRoot);
  const inputBytes = readFileSync(input);
  const inputFile = relative(deckRoot, input).split('\\').join('/');
  const inputReceipt = {
    path: inputFile,
    bytes: inputBytes.length,
    sha256: createHash('sha256').update(inputBytes).digest('hex'),
  };
  const manifestPath = join(deckRoot, 'delivery-manifest.json');
  let manifestBytes = null;
  let manifestSha256 = null;
  let files = [inputReceipt];
  let manifestSafe = false;
  if (existsSync(manifestPath)) {
    const info = lstatSync(manifestPath);
    const physicalRelative = info.isSymbolicLink() ? '..' : relative(deckRootReal, realpathSync(manifestPath));
    manifestSafe = info.isFile() && !info.isSymbolicLink()
      && physicalRelative !== '..' && !physicalRelative.startsWith('../') && !physicalRelative.startsWith('..\\');
    if (manifestSafe) {
      manifestBytes = readFileSync(manifestPath);
      manifestSha256 = createHash('sha256').update(manifestBytes).digest('hex');
      try {
        const manifest = JSON.parse(manifestBytes.toString('utf8'));
        if (Array.isArray(manifest.files)) {
          const seen = new Set();
          files = [];
          for (const entry of manifest.files) {
            if (!entry || typeof entry.path !== 'string' || seen.has(entry.path)) continue;
            seen.add(entry.path);
            const receipt = snapshotLedgerFile(deckRoot, deckRootReal, entry.path);
            if (receipt) files.push(receipt);
          }
        }
      } catch {
        // The validator reports malformed JSON; the stable raw manifest hash is still retained.
      }
    }
  }
  files.sort((left, right) => left.path.localeCompare(right.path, 'en'));
  return {
    inputBytes,
    manifestBytes,
    manifestSafe,
    receipt: {
      inputFile,
      inputSha256: inputReceipt.sha256,
      manifestFile: manifestBytes ? 'delivery-manifest.json' : null,
      manifestSha256,
      files,
    },
  };
}

function sameValidationSnapshot(left, right) {
  return JSON.stringify(left.receipt) === JSON.stringify(right.receipt)
    && left.manifestSafe === right.manifestSafe;
}

function readJson(file, label) {
  if (!existsSync(file)) throw new DeckEnvironmentError(`${label} not found: ${file}`, 'MISSING_CONTRACT');
  try { return JSON.parse(readFileSync(file, 'utf8')); }
  catch (error) { throw new DeckEnvironmentError(`${label} is invalid JSON: ${error.message}`, 'INVALID_CONTRACT'); }
}

function loadContracts(contractDir) {
  const layoutsFile = join(contractDir, 'layouts.json');
  const componentsFile = join(contractDir, 'components.json');
  const layouts = readJson(layoutsFile, 'Layout contract');
  const components = readJson(componentsFile, 'Component contract');
  if (!Array.isArray(layouts.layouts) || !Array.isArray(layouts.modifiers)) {
    throw new DeckEnvironmentError('layouts.json must contain layouts[] and modifiers[].', 'INVALID_CONTRACT');
  }
  if (!components.themes || typeof components.themes !== 'object' || Array.isArray(components.themes)) {
    throw new DeckEnvironmentError('components.json must contain a themes object.', 'INVALID_CONTRACT');
  }
  if (!Array.isArray(components.runtimeClasses)) {
    throw new DeckEnvironmentError('components.json must contain runtimeClasses[].', 'INVALID_CONTRACT');
  }
  return { layouts, components, files: { layoutsFile, componentsFile } };
}

function addResourceIssue(context, node, code, message, severity = 'error') {
  context.issues.push(issueFor(node, severity, code, message));
}

function checkReference(context, { value, node, baseDir, kind, fromCss = false }) {
  const cleaned = sanitizeReference(value);
  const comparable = schemeComparable(cleaned);
  if (isIgnoredReference(cleaned)) return null;
  if (/^(?:javascript:|vbscript:)/i.test(comparable)) {
    addResourceIssue(context, node, 'DANGEROUS_URL', `${kind} uses a dangerous URL scheme.`);
    return null;
  }
  if (/^data:/i.test(comparable)) {
    const mime = comparable.slice(5).split(/[;,]/, 1)[0].toLowerCase();
    const prohibitedElement = !fromCss && ['script', 'link', 'iframe', 'object', 'embed'].includes(node?.tagName);
    const dangerousMime = /(?:html|xhtml|javascript|ecmascript)/i.test(mime);
    const allowedMime = /^(?:image\/(?:png|jpeg|gif|webp|avif|svg\+xml)|audio\/[a-z0-9.+-]+|video\/[a-z0-9.+-]+|font\/(?:woff2?|ttf|otf)|application\/(?:font-woff|octet-stream))$/i.test(mime);
    if (prohibitedElement || dangerousMime || (!fromCss && !['img', 'image', 'audio', 'video', 'source'].includes(node?.tagName)) || !allowedMime) {
      addResourceIssue(context, node, dangerousMime ? 'DANGEROUS_DATA_MIME' : 'DATA_URL_NOT_ALLOWED', `${kind} uses a prohibited data: MIME type or element context (${mime || 'unspecified'}).`);
    }
    return null;
  }
  if (/^blob:/i.test(comparable)) {
    addResourceIssue(context, node, 'BLOB_URL_NOT_ALLOWED', `${kind} uses blob:, which is prohibited in static delivery.`);
    return null;
  }
  if (isRemoteReference(cleaned)) {
    context.resources.remote.push({ kind, value: cleaned });
    if (context.offlineRequired) {
      addResourceIssue(context, node, 'REMOTE_RESOURCE_OFFLINE', `${kind} references remote resource ${cleaned} while offline delivery is required.`);
    } else if (!context.allowRemote) {
      addResourceIssue(context, node, 'REMOTE_RESOURCE', `${kind} references remote resource ${cleaned}; offline rendering is not guaranteed.`, 'warning');
    }
    return null;
  }
  const resolved = resolveLocalReference(cleaned, baseDir, context.deckRoot);
  if (resolved.error) { addResourceIssue(context, node, 'RESOURCE_INVALID_PATH', resolved.error); return null; }
  if (resolved.ignored) return null;
  if (resolved.absolute || resolved.outside) {
    addResourceIssue(context, node, 'RESOURCE_NOT_PORTABLE', `${kind} resolves outside the deck directory: ${cleaned}.`);
    return null;
  }
  context.resources.checked.push({ kind, value: cleaned, path: resolved.relativePath, fromCss });
  if (!existsSync(resolved.path) || !statSync(resolved.path).isFile()) {
    context.resources.missing.push({ kind, value: cleaned, path: resolved.relativePath });
    addResourceIssue(context, node, 'RESOURCE_MISSING', `${kind} not found: ${resolved.relativePath}.`);
    return null;
  }
  const physicalRoot = realpathSync(context.deckRoot);
  const physicalPath = realpathSync(resolved.path);
  const physicalRelative = relative(physicalRoot, physicalPath);
  if (physicalRelative === '..' || physicalRelative.startsWith('../') || physicalRelative.startsWith('..\\')) {
    context.resources.missing.push({ kind, value: cleaned, path: resolved.relativePath, reason: 'symlink-outside-deck' });
    addResourceIssue(context, node, 'RESOURCE_NOT_PORTABLE', `${kind} resolves through a symlink outside the deck directory: ${cleaned}.`);
    return null;
  }
  return resolved.path;
}

function readCssGraph(context, cssPath, displayPath, ownerNode, visited = new Set()) {
  const realPath = resolve(cssPath);
  if (visited.has(realPath)) return;
  visited.add(realPath);
  let css;
  try { css = readFileSync(realPath, 'utf8'); }
  catch (error) { addResourceIssue(context, ownerNode, 'CSS_READ_FAILED', `Cannot read stylesheet ${displayPath}: ${error.message}`); return; }
  const scan = scanCss(css, displayPath);
  context.css.files.set(normalizeHref(displayPath), scan);
  for (const name of scan.classes) context.css.classes.add(name);
  for (const name of scan.definitions) context.css.variables.add(name);
  context.css.uses.push(...scan.uses);
  for (const cssUrl of scan.urls) {
    checkReference(context, { value: cssUrl.value, node: ownerNode, baseDir: dirname(realPath), kind: `CSS url() in ${displayPath}`, fromCss: true });
  }
  for (const imported of scan.imports) {
    const importedPath = checkReference(context, { value: imported.value, node: ownerNode, baseDir: dirname(realPath), kind: `CSS @import in ${displayPath}`, fromCss: true });
    if (importedPath) {
      const importedDisplay = relative(context.deckRoot, importedPath).split('\\').join('/');
      readCssGraph(context, importedPath, importedDisplay, ownerNode, visited);
    }
  }
}

function checkContractShape(context, contracts) {
  const { layouts, components } = contracts;
  const layoutIds = new Set();
  const modifierIds = new Set();
  const themeIds = new Set(Object.keys(components.themes));
  const contractNode = { location: { line: 1, column: 1 } };
  for (const layout of layouts.layouts) {
    if (!layout || typeof layout.id !== 'string' || !layout.id.trim()) {
      context.issues.push(issueFor(contractNode, 'error', 'CONTRACT_LAYOUT_ID', 'Every layout contract entry must have a non-empty id.'));
      continue;
    }
    if (layoutIds.has(layout.id)) context.issues.push(issueFor(contractNode, 'error', 'CONTRACT_LAYOUT_DUPLICATE', `Layout id "${layout.id}" is duplicated.`));
    layoutIds.add(layout.id);
    if (!Array.isArray(layout.themes) || layout.themes.some((theme) => !themeIds.has(theme))) {
      context.issues.push(issueFor(contractNode, 'error', 'CONTRACT_LAYOUT_THEME', `Layout "${layout.id}" references an unknown or invalid themes list.`));
    }
    if (typeof layout.componentClass !== 'string' || !layout.componentClass.trim()) {
      context.issues.push(issueFor(contractNode, 'error', 'CONTRACT_LAYOUT_CLASS', `Layout "${layout.id}" must declare componentClass.`));
    }
  }
  for (const modifier of layouts.modifiers) {
    if (!modifier || typeof modifier.id !== 'string' || !modifier.id.trim()) {
      context.issues.push(issueFor(contractNode, 'error', 'CONTRACT_MODIFIER_ID', 'Every modifier contract entry must have a non-empty id.'));
      continue;
    }
    if (modifierIds.has(modifier.id)) context.issues.push(issueFor(contractNode, 'error', 'CONTRACT_MODIFIER_DUPLICATE', `Modifier id "${modifier.id}" is duplicated.`));
    modifierIds.add(modifier.id);
    if (!Array.isArray(modifier.themes) || modifier.themes.some((theme) => !themeIds.has(theme))) {
      context.issues.push(issueFor(contractNode, 'error', 'CONTRACT_MODIFIER_THEME', `Modifier "${modifier.id}" references an unknown or invalid themes list.`));
    }
    if (typeof modifier.componentClass !== 'string' || !modifier.componentClass.trim()) {
      context.issues.push(issueFor(contractNode, 'error', 'CONTRACT_MODIFIER_CLASS', `Modifier "${modifier.id}" must declare componentClass.`));
    }
  }
  for (const [themeId, theme] of Object.entries(components.themes)) {
    if (!theme || typeof theme.stylesheet !== 'string' || !Array.isArray(theme.classes)) {
      context.issues.push(issueFor(contractNode, 'error', 'CONTRACT_THEME_SHAPE', `Theme "${themeId}" must declare stylesheet and classes[].`));
    }
    if (theme?.baseStylesheet !== undefined && typeof theme.baseStylesheet !== 'string') {
      context.issues.push(issueFor(contractNode, 'error', 'CONTRACT_THEME_BASE_STYLESHEET', `Theme "${themeId}" baseStylesheet must be a string.`));
    }
  }
}

function checkActiveContractCss(context, contracts, themeId) {
  const theme = contracts.components.themes[themeId];
  if (!theme) return;
  const requiredStylesheets = [theme.baseStylesheet, theme.stylesheet].filter(Boolean).map(normalizeHref);
  for (const stylesheet of requiredStylesheets) {
    if (!context.css.linkedHrefs.has(stylesheet)) {
      context.issues.push({ severity: 'error', code: 'THEME_STYLESHEET_NOT_LINKED', message: `Theme "${themeId}" requires linked stylesheet "${stylesheet}".`, location: { file: context.input, line: 1, column: 1 } });
    }
  }
  const themeScan = context.css.files.get(normalizeHref(theme.stylesheet));
  if (themeScan) {
    for (const className of theme.classes) {
      if (!themeScan.classes.has(className) || !themeScan.classDeclarations.get(className)) {
        context.issues.push({ severity: 'error', code: 'CONTRACT_CLASS_NOT_IMPLEMENTED', message: `Theme contract class ".${className}" is not implemented by ${theme.stylesheet}.`, location: { file: context.input, line: 1, column: 1 } });
      }
    }
  }
  if (theme.baseStylesheet) {
    const baseScan = context.css.files.get(normalizeHref(theme.baseStylesheet));
    if (baseScan) {
      for (const className of contracts.components.runtimeClasses) {
        if (!baseScan.classes.has(className) || !baseScan.classDeclarations.get(className)) {
          context.issues.push({ severity: 'error', code: 'CONTRACT_RUNTIME_CLASS_NOT_IMPLEMENTED', message: `Runtime class ".${className}" is not implemented by ${theme.baseStylesheet}.`, location: { file: context.input, line: 1, column: 1 } });
        }
      }
    }
  }
}

function parseDeckConfig(deckRoot, issues) {
  const localConfig = join(deckRoot, 'deck.config.json');
  const parentConfig = join(dirname(deckRoot), 'deck.config.json');
  let configPath = existsSync(localConfig) ? localConfig : null;
  if (!configPath && existsSync(parentConfig)) {
    try {
      const candidate = JSON.parse(readFileSync(parentConfig, 'utf8'));
      const declaredOutput = resolve(dirname(parentConfig), candidate?.output?.dir ?? 'dist');
      if (declaredOutput === deckRoot) configPath = parentConfig;
    } catch {
      // The selected parser below reports malformed local configs; an unrelated
      // malformed parent file must not be adopted as this deck's config.
    }
  }
  if (!configPath) return { path: null, value: {} };
  try {
    const value = JSON.parse(readFileSync(configPath, 'utf8'));
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('root must be an object');
    return { path: configPath, value };
  } catch (error) {
    issues.push({ severity: 'error', code: 'CONFIG_INVALID', message: `deck.config.json is invalid: ${error.message}`, location: { file: configPath, line: 1, column: 1 } });
    return { path: configPath, value: {} };
  }
}

function dataBoolean(value) {
  if (value === undefined) return undefined;
  return value === 'true' ? true : value === 'false' ? false : undefined;
}

function checkDeliveryManifest(context) {
  const manifestPath = join(context.deckRoot, 'delivery-manifest.json');
  const snapshot = context.deliveryStart;
  if (!snapshot?.manifestBytes) {
    const code = existsSync(manifestPath) ? 'DELIVERY_MANIFEST_UNSAFE' : 'DELIVERY_MANIFEST_MISSING';
    const message = existsSync(manifestPath)
      ? 'delivery-manifest.json must be a regular non-symlink file inside the delivery root.'
      : 'Formal static delivery requires delivery-manifest.json.';
    context.issues.push({ severity: 'error', code, message, location: { file: context.input, line: 1, column: 1 } });
    return;
  }
  const manifestBytes = snapshot.manifestBytes;
  context.manifestSha256 = snapshot.receipt.manifestSha256;
  let manifest;
  try { manifest = JSON.parse(manifestBytes.toString('utf8')); }
  catch (error) {
    context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_INVALID', message: `delivery-manifest.json is invalid JSON: ${error.message}`, location: { file: manifestPath, line: 1, column: 1 } });
    return;
  }
  if (manifest.schemaVersion !== '1.0.0' || !Array.isArray(manifest.files)) {
    context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_SCHEMA', message: 'delivery-manifest.json must use schemaVersion 1.0.0 and contain files[].', location: { file: manifestPath, line: 1, column: 1 } });
    return;
  }
  if (manifest.mode !== context.actualMode) {
    context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_MODE_MISMATCH', message: `Manifest mode "${manifest.mode}" does not match detected runtime mode "${context.actualMode}".`, location: { file: manifestPath, line: 1, column: 1 } });
  }
  if (!Array.isArray(manifest.slides)) {
    context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_SLIDES_INVALID', message: 'Manifest must contain slides[] in rendered order.', location: { file: manifestPath, line: 1, column: 1 } });
  } else {
    const manifestSlideIds = manifest.slides.map((slide) => slide?.id);
    const validIndices = manifest.slides.every((slide, index) => slide?.index === index + 1);
    if (!validIndices || JSON.stringify(manifestSlideIds) !== JSON.stringify(context.slideIds)) {
      context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_SLIDES_MISMATCH', message: 'Manifest slide IDs/order do not match rendered HTML.', location: { file: manifestPath, line: 1, column: 1 } });
    }
  }
  const scannedExternalUrls = [...new Set(context.resources.remote.map((entry) => sanitizeReference(entry.value)))].sort();
  const declaredExternalUrls = Array.isArray(manifest.externalDependencyUrls) ? [...new Set(manifest.externalDependencyUrls)].sort() : null;
  if (manifest.externalDependencies !== scannedExternalUrls.length
    || !declaredExternalUrls
    || JSON.stringify(declaredExternalUrls) !== JSON.stringify(scannedExternalUrls)) {
    context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_EXTERNAL_MISMATCH', message: 'Manifest external dependency count/URLs do not match the static scan.', location: { file: manifestPath, line: 1, column: 1 } });
  }
  if (!manifest.deliveryProfile) {
    context.issues.push({ severity: 'warning', code: 'DELIVERY_MANIFEST_PROFILE_LEGACY', message: 'Manifest has no deliveryProfile; standard-client compatibility is assumed.', location: { file: manifestPath, line: 1, column: 1 } });
  } else {
    if (manifest.deliveryProfile !== context.deliveryProfile) {
      context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_PROFILE_MISMATCH', message: 'Manifest deliveryProfile does not match HTML/config.', location: { file: manifestPath, line: 1, column: 1 } });
    }
    if (JSON.stringify(manifest.requiredGates) !== JSON.stringify(context.requiredGates)) {
      context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_GATES_MISMATCH', message: 'Manifest requiredGates do not match the delivery profile.', location: { file: manifestPath, line: 1, column: 1 } });
    }
  }
  if (manifest.theme !== undefined && manifest.theme !== context.themeId) {
    context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_THEME_MISMATCH', message: 'Manifest theme does not match HTML.', location: { file: manifestPath, line: 1, column: 1 } });
  }
  if (manifest.aspect !== undefined && manifest.aspect !== context.aspect) {
    context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_TARGET_MISMATCH', message: 'Manifest aspect does not match HTML.', location: { file: manifestPath, line: 1, column: 1 } });
  }
  if (manifest.target !== undefined && JSON.stringify(manifest.target) !== JSON.stringify(context.target)) {
    context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_TARGET_MISMATCH', message: 'Manifest target does not match HTML.', location: { file: manifestPath, line: 1, column: 1 } });
  }
  if (manifest.offlineRequired !== undefined && manifest.offlineRequired !== context.offlineRequired) {
    context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_POLICY_MISMATCH', message: 'Manifest offlineRequired does not match HTML/config.', location: { file: manifestPath, line: 1, column: 1 } });
  }
  if (manifest.evidencePolicy !== undefined && manifest.evidencePolicy !== context.evidencePolicy) {
    context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_POLICY_MISMATCH', message: 'Manifest evidencePolicy does not match HTML/config.', location: { file: manifestPath, line: 1, column: 1 } });
  }
  const declared = new Set();
  const physicalRoot = realpathSync(context.deckRoot);
  for (const entry of manifest.files) {
    if (!entry || typeof entry.path !== 'string' || typeof entry.bytes !== 'number' || !/^[a-f0-9]{64}$/i.test(entry.sha256 ?? '')) {
      context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_ENTRY', message: 'Each manifest file needs path, numeric bytes, and a SHA-256 digest.', location: { file: manifestPath, line: 1, column: 1 } });
      continue;
    }
    const normalizedPath = normalizeHref(entry.path);
    const resolved = resolve(context.deckRoot, normalizedPath);
    const lexicalRelative = relative(context.deckRoot, resolved);
    if (isAbsolute(entry.path) || lexicalRelative === '..' || lexicalRelative.startsWith('../') || lexicalRelative.startsWith('..\\')) {
      context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_PATH', message: `Manifest path is outside the deck: ${entry.path}.`, location: { file: manifestPath, line: 1, column: 1 } });
      continue;
    }
    if (declared.has(normalizedPath)) {
      context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_DUPLICATE', message: `Manifest path is duplicated: ${normalizedPath}.`, location: { file: manifestPath, line: 1, column: 1 } });
      continue;
    }
    declared.add(normalizedPath);
    if (!existsSync(resolved) || !statSync(resolved).isFile()) {
      context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_FILE_MISSING', message: `Manifest file is missing: ${normalizedPath}.`, location: { file: manifestPath, line: 1, column: 1 } });
      continue;
    }
    const physical = realpathSync(resolved);
    const physicalRelative = relative(physicalRoot, physical);
    if (physicalRelative === '..' || physicalRelative.startsWith('../') || physicalRelative.startsWith('..\\')) {
      context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_PATH', message: `Manifest file resolves outside the deck: ${normalizedPath}.`, location: { file: manifestPath, line: 1, column: 1 } });
      continue;
    }
    const bytes = readFileSync(resolved);
    const digest = createHash('sha256').update(bytes).digest('hex');
    if (bytes.length !== entry.bytes || digest !== entry.sha256.toLowerCase()) {
      context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_MISMATCH', message: `Manifest integrity mismatch for ${normalizedPath}.`, location: { file: manifestPath, line: 1, column: 1 } });
    }
  }
  const used = new Set(['index.html', ...context.resources.checked.map((entry) => normalizeHref(entry.path))]);
  for (const resource of used) {
    if (!declared.has(resource)) {
      context.issues.push({ severity: 'error', code: 'DELIVERY_MANIFEST_RESOURCE_UNLISTED', message: `Loaded resource is not listed in delivery-manifest.json: ${resource}.`, location: { file: manifestPath, line: 1, column: 1 } });
    }
  }
}

function sortIssues(issues) {
  const rank = { error: 0, warning: 1, info: 2 };
  return [...issues].sort((a, b) =>
    (rank[a.severity] ?? 9) - (rank[b.severity] ?? 9)
    || String(a.location?.file ?? '').localeCompare(String(b.location?.file ?? ''))
    || (a.location?.line ?? 0) - (b.location?.line ?? 0)
    || (a.location?.column ?? 0) - (b.location?.column ?? 0)
    || a.code.localeCompare(b.code));
}

export function validateDeck(inputFile, options = {}) {
  if (!inputFile) throw new DeckEnvironmentError('No HTML input file was provided.', 'ARGUMENT_ERROR');
  const input = resolve(inputFile);
  if (!existsSync(input)) throw new DeckEnvironmentError(`HTML input file not found: ${input}`, 'INPUT_NOT_FOUND');
  const inputInfo = lstatSync(input);
  if (inputInfo.isSymbolicLink() || !inputInfo.isFile()) {
    throw new DeckEnvironmentError(`HTML input must be a regular non-symlink file: ${input}`, 'INPUT_NOT_PORTABLE');
  }
  const deckRoot = dirname(input);
  const deliveryStart = captureValidationSnapshot(input);
  const html = deliveryStart.inputBytes.toString('utf8');
  const parsed = parseHtml(html, input);
  const issues = parsed.issues.map((entry) => ({ ...entry, location: { file: input, ...entry.location } }));
  const contracts = loadContracts(options.contractDir ?? join(DEFAULT_SKILL_ROOT, 'references'));
  const config = parseDeckConfig(deckRoot, issues);
  const htmlElement = elements(parsed.root, (node) => node.tagName === 'html')[0];
  const head = elements(parsed.root, (node) => node.tagName === 'head')[0];
  const body = elements(parsed.root, (node) => node.tagName === 'body')[0];
  const themeId = getAttr(body, 'data-theme') ?? getAttr(htmlElement, 'data-theme');
  const htmlOffline = dataBoolean(getAttr(body, 'data-offline-required') ?? getAttr(htmlElement, 'data-offline-required'));
  const configOffline = typeof config.value.offlineRequired === 'boolean' ? config.value.offlineRequired : undefined;
  const offlineRequired = options.offlineRequired ?? configOffline ?? htmlOffline ?? false;
  const evidencePolicy = options.evidencePolicy ?? config.value.evidencePolicy
    ?? getAttr(body, 'data-evidence-policy') ?? getAttr(htmlElement, 'data-evidence-policy') ?? 'advisory';
  const htmlProfile = getAttr(htmlElement, 'data-delivery-profile');
  const bodyProfile = getAttr(body, 'data-delivery-profile');
  const deliveryProfile = config.value.deliveryProfile ?? bodyProfile ?? htmlProfile ?? 'standard-client';
  const requiredGates = CONTRACT_DELIVERY_PROFILES.includes(deliveryProfile) ? requiredGatesFor(deliveryProfile) : null;
  const context = {
    input, deckRoot, issues, themeId, allowRemote: Boolean(options.allowRemote), offlineRequired, evidencePolicy,
    deliveryProfile, requiredGates,
    deliveryStart,
    resources: { checked: [], missing: [], remote: [] },
    css: { classes: new Set(), variables: new Set(), uses: [], files: new Map(), linkedHrefs: new Set() },
  };
  checkContractShape(context, contracts);
  if (!htmlElement) issues.push({ severity: 'error', code: 'HTML_ROOT_MISSING', message: 'Document must contain an <html> element.', location: { file: input, line: 1, column: 1 } });
  if (!body) issues.push({ severity: 'error', code: 'HTML_BODY_MISSING', message: 'Document must contain a <body> element.', location: { file: input, line: 1, column: 1 } });
  if (!themeId) issues.push({ severity: 'error', code: 'THEME_MISSING', message: 'Set an explicit data-theme on <body> (or <html>).', location: { file: input, line: 1, column: 1 } });
  else if (!contracts.components.themes[themeId]) issues.push(issueFor(body ?? htmlElement, 'error', 'THEME_UNKNOWN', `Theme "${themeId}" is not registered in components.json.`));
  if (htmlOffline !== undefined && configOffline !== undefined && htmlOffline !== configOffline) {
    issues.push(issueFor(body ?? htmlElement, 'error', 'CONFIG_OFFLINE_MISMATCH', 'data-offline-required does not match deck.config.json offlineRequired.'));
  }
  if (!['advisory', 'required'].includes(evidencePolicy)) issues.push(issueFor(body ?? htmlElement, 'error', 'EVIDENCE_POLICY_INVALID', 'Evidence policy must be "advisory" or "required".'));
  if (!requiredGates) issues.push(issueFor(body ?? htmlElement, 'error', 'DELIVERY_PROFILE_INVALID', `Unknown delivery profile "${deliveryProfile}".`));
  if (!htmlProfile || !bodyProfile) {
    issues.push(issueFor(body ?? htmlElement, 'warning', 'DELIVERY_PROFILE_LEGACY', 'data-delivery-profile is missing on html/body; standard-client compatibility mode is assumed.'));
  } else if (htmlProfile !== bodyProfile) {
    issues.push(issueFor(body, 'error', 'DELIVERY_PROFILE_MISMATCH', 'html and body data-delivery-profile values must match.'));
  }
  if (config.value.deliveryProfile && (htmlProfile !== config.value.deliveryProfile || bodyProfile !== config.value.deliveryProfile)) {
    issues.push(issueFor(body ?? htmlElement, 'error', 'DELIVERY_PROFILE_CONFIG_MISMATCH', 'HTML delivery profile does not match deck.config.json.'));
  }
  if (deliveryProfile === 'high-assurance' && (!offlineRequired || evidencePolicy !== 'required')) {
    issues.push(issueFor(body ?? htmlElement, 'error', 'HIGH_ASSURANCE_POLICY', 'high-assurance requires offlineRequired=true and evidencePolicy=required.'));
  }

  const pairedAttribute = (name, code) => {
    const htmlValue = getAttr(htmlElement, name);
    const bodyValue = getAttr(body, name);
    if (!htmlValue || !bodyValue) {
      issues.push(issueFor(body ?? htmlElement, 'error', `${code}_MISSING`, `${name} must be present on both html and body.`));
      return htmlValue ?? bodyValue;
    }
    if (htmlValue !== bodyValue) issues.push(issueFor(body, 'error', `${code}_MISMATCH`, `${name} must match on html and body.`));
    return bodyValue;
  };
  const aspectValue = pairedAttribute('data-aspect', 'TARGET_ASPECT');
  const widthValue = pairedAttribute('data-deck-width', 'TARGET_WIDTH');
  const heightValue = pairedAttribute('data-deck-height', 'TARGET_HEIGHT');
  const browserValue = pairedAttribute('data-target-browser', 'TARGET_BROWSER');
  const osValue = pairedAttribute('data-target-os', 'TARGET_OS');
  const aspectMatch = aspectValue?.match(/^([0-9]+(?:\.[0-9]+)?):([0-9]+(?:\.[0-9]+)?)$/);
  if (!aspectMatch || Number(aspectMatch?.[1]) <= 0 || Number(aspectMatch?.[2]) <= 0) {
    issues.push(issueFor(body ?? htmlElement, 'error', 'TARGET_ASPECT_INVALID', 'data-aspect must be a positive width:height ratio.'));
  }
  const deckWidth = Number(widthValue);
  const deckHeight = Number(heightValue);
  if (!Number.isInteger(deckWidth) || deckWidth < 320 || deckWidth > 7680) issues.push(issueFor(body ?? htmlElement, 'error', 'TARGET_WIDTH_INVALID', 'data-deck-width must be an integer from 320 to 7680.'));
  if (!Number.isInteger(deckHeight) || deckHeight < 320 || deckHeight > 7680) issues.push(issueFor(body ?? htmlElement, 'error', 'TARGET_HEIGHT_INVALID', 'data-deck-height must be an integer from 320 to 7680.'));
  if (aspectMatch && Number.isFinite(deckWidth) && Number.isFinite(deckHeight)
    && Math.abs(deckWidth / deckHeight - Number(aspectMatch[1]) / Number(aspectMatch[2])) > 0.001) {
    issues.push(issueFor(body ?? htmlElement, 'error', 'TARGET_RATIO_MISMATCH', 'Viewport width/height does not match data-aspect.'));
  }
  if (!browserValue?.trim()) issues.push(issueFor(body ?? htmlElement, 'error', 'TARGET_BROWSER_INVALID', 'data-target-browser must be non-empty.'));
  else if (!TARGET_BROWSERS.includes(browserValue.trim().toLowerCase())) issues.push(issueFor(body ?? htmlElement, 'error', 'TARGET_BROWSER_UNSUPPORTED', `Unsupported target browser "${browserValue}"; expected ${TARGET_BROWSERS.join(', ')}.`));
  if (!osValue?.trim()) issues.push(issueFor(body ?? htmlElement, 'error', 'TARGET_OS_INVALID', 'data-target-os must be non-empty.'));
  else if (!TARGET_OSES.includes(osValue.trim().toLowerCase())) issues.push(issueFor(body ?? htmlElement, 'error', 'TARGET_OS_UNSUPPORTED', `Unsupported target OS "${osValue}"; expected ${TARGET_OSES.join(', ')}.`));
  if (config.path) {
    const target = config.value.target;
    if (config.value.aspect !== aspectValue
      || target?.browser !== browserValue || target?.os !== osValue
      || target?.viewport?.width !== deckWidth || target?.viewport?.height !== deckHeight) {
      issues.push(issueFor(body ?? htmlElement, 'error', 'TARGET_CONFIG_MISMATCH', 'HTML target/aspect attributes do not match deck.config.json.'));
    }
  }
  context.aspect = aspectValue;
  context.target = { browser: browserValue, os: osValue, viewport: { width: deckWidth, height: deckHeight } };

  const allElements = elements(parsed.root);
  const allowedBundledStylesheets = new Set(Object.values(contracts.components.themes)
    .flatMap((theme) => [theme.baseStylesheet, theme.stylesheet]).filter(Boolean).map(normalizeHref));
  for (const node of allElements) {
    if (node.tagName === 'base') issues.push(issueFor(node, 'error', 'BASE_ELEMENT_PROHIBITED', '<base> is prohibited because it changes resolution of every relative resource.'));
    if (hasAttr(node, 'ping')) {
      const pingValue = sanitizeReference(getAttr(node, 'ping'));
      issues.push(issueFor(node, 'error', 'PING_ATTRIBUTE_PROHIBITED', `The ping attribute is prohibited in static delivery${pingValue ? `: ${pingValue}` : ''}.`));
    }
    for (const [name, value] of node.attributes ?? []) {
      if (/^on/i.test(name)) issues.push(issueFor(node, 'error', 'INLINE_EVENT_HANDLER', `Inline event handler "${name}" is prohibited; bind it in the local runtime instead.`));
      if (typeof value === 'string' && /^(?:href|src|action|formaction|poster|data)$/i.test(name)
        && /^(?:javascript:|vbscript:|data:(?:text\/html|application\/(?:xhtml\+xml|javascript)|text\/javascript))/i.test(schemeComparable(value))) {
        issues.push(issueFor(node, 'error', 'DANGEROUS_URL', `Attribute "${name}" uses a dangerous URL scheme.`));
      }
      if (((node.tagName === 'form' && name === 'action')
        || (['button', 'input'].includes(node.tagName) && name === 'formaction'))
        && isRemoteReference(value)) {
        issues.push(issueFor(node, offlineRequired ? 'error' : 'warning', offlineRequired ? 'REMOTE_FORM_TARGET_OFFLINE' : 'REMOTE_FORM_TARGET', `Form submission target is remote: ${value}`));
      }
    }
    const inlineStyle = getAttr(node, 'style');
    if (inlineStyle) {
      if (/expression\s*\(|url\s*\(\s*['"]?javascript:/i.test(inlineStyle)) issues.push(issueFor(node, 'error', 'DANGEROUS_INLINE_STYLE', 'Inline style contains executable or unsafe content.'));
      const scan = scanCss(`x{${inlineStyle}}`, `${input}:inline-style`);
      for (const name of scan.definitions) context.css.variables.add(name);
      context.css.uses.push(...scan.uses);
      for (const url of scan.urls) checkReference(context, { value: url.value, node, baseDir: deckRoot, kind: 'inline CSS url()', fromCss: true });
    }
    if (['iframe', 'object', 'embed'].includes(node.tagName)) issues.push(issueFor(node, 'error', 'EMBED_ELEMENT_PROHIBITED', `<${node.tagName}> is prohibited in a static deck.`));
    if (node.tagName === 'iframe' && hasAttr(node, 'srcdoc')) issues.push(issueFor(node, 'error', 'IFRAME_SRCDOC', 'iframe srcdoc is prohibited in a portable deck.'));
    if (node.tagName === 'meta' && schemeComparable(getAttr(node, 'http-equiv') ?? '').toLowerCase() === 'refresh') issues.push(issueFor(node, 'error', 'META_REFRESH', 'Automatic meta refresh is prohibited.'));
  }
  const inlineScriptAssets = new Map();
  for (const script of allElements.filter((node) => node.tagName === 'script')) {
    const scriptType = (getAttr(script, 'type') ?? '').toLowerCase().trim();
    if (nearestSlide(script)) issues.push(issueFor(script, 'error', 'SCRIPT_INSIDE_SLIDE', 'Slides may not contain script elements.'));
    const validScriptParent = SAFE_INLINE_SCRIPT_TYPES.has(scriptType)
      ? script.parent === head || script.parent === body
      : script.parent === body;
    if (!validScriptParent) issues.push(issueFor(script, 'error', 'SCRIPT_LOCATION_INVALID', 'Runtime scripts must be direct children of <body>; JSON data scripts may also be direct children of <head>.'));
    if (hasAttr(script, 'src')) {
      const src = getAttr(script, 'src');
      const normalizedSrc = normalizeHref(sanitizeReference(src ?? ''));
      if (!TRUSTED_RUNTIME_SCRIPTS.has(normalizedSrc)) {
        issues.push(issueFor(script, 'error', 'SCRIPT_SRC_NOT_ALLOWED', `Runtime script "${src}" is not an approved canonical asset.`));
      } else {
        const count = (inlineScriptAssets.get(`src:${normalizedSrc}`) ?? 0) + 1;
        inlineScriptAssets.set(`src:${normalizedSrc}`, count);
        if (count > 1) issues.push(issueFor(script, 'error', 'SCRIPT_RUNTIME_DUPLICATE', `Runtime script "${normalizedSrc}" is included more than once.`));
        const local = resolve(deckRoot, normalizedSrc);
        const canonical = resolve(DEFAULT_SKILL_ROOT, normalizedSrc);
        if (existsSync(local) && existsSync(canonical)
          && digestText(readFileSync(local, 'utf8')) !== digestText(readFileSync(canonical, 'utf8'))) {
          issues.push(issueFor(script, 'error', 'SCRIPT_ASSET_CONTENT_MISMATCH', `Runtime script "${normalizedSrc}" does not match the canonical asset.`));
        }
      }
      if (hasAttr(script, 'data-web-slide-asset')) issues.push(issueFor(script, 'error', 'SCRIPT_ASSET_MARKER_WITH_SRC', 'External scripts must not use data-web-slide-asset.'));
    } else {
      const type = scriptType;
      const bundledAsset = getAttr(script, 'data-web-slide-asset');
      const trustedBundledAsset = new Set(['assets/icon-runtime.js', 'assets/slide-engine.js']).has(bundledAsset);
      if (trustedBundledAsset) {
        const count = (inlineScriptAssets.get(`inline:${bundledAsset}`) ?? 0) + 1;
        inlineScriptAssets.set(`inline:${bundledAsset}`, count);
        if (count > 1) issues.push(issueFor(script, 'error', 'SCRIPT_RUNTIME_DUPLICATE', `Inline runtime "${bundledAsset}" is included more than once.`));
        const canonical = readFileSync(resolve(DEFAULT_SKILL_ROOT, bundledAsset), 'utf8');
        const expected = bundledAsset === 'assets/slide-engine.js' ? standaloneEngineSource(canonical) : canonical;
        if (digestText(rawTextContent(script)) !== digestText(expected)) {
          issues.push(issueFor(script, 'error', 'INLINE_ASSET_CONTENT_MISMATCH', `Inline runtime "${bundledAsset}" does not match its canonical standalone content.`));
        }
        if (bundledAsset === 'assets/slide-engine.js' && /['"]\.\/motion\.min\.js['"]/.test(rawTextContent(script))) {
          issues.push(issueFor(script, 'error', 'STANDALONE_MOTION_REFERENCE', 'Standalone runtime must not contain ./motion.min.js references.'));
        }
      }
      if (!SAFE_INLINE_SCRIPT_TYPES.has(type) && textContent(script) && !trustedBundledAsset) {
        issues.push(issueFor(script, 'error', 'INLINE_EXECUTABLE_SCRIPT', 'Executable inline scripts are prohibited; use a reviewed local script file.'));
      }
      if (bundledAsset && !trustedBundledAsset) {
        issues.push(issueFor(script, 'error', 'INLINE_ASSET_MARKER_INVALID', `Inline script asset marker "${bundledAsset}" is not an approved runtime asset.`));
      }
      if (SAFE_INLINE_SCRIPT_TYPES.has(type) && textContent(script)) {
        try {
          const data = JSON.parse(rawTextContent(script));
          const remotes = remoteStrings(data);
          if (remotes.length && offlineRequired) issues.push(issueFor(script, 'error', 'JSON_REMOTE_REFERENCE_OFFLINE', `Inline JSON contains remote references while offline delivery is required: ${remotes[0]}`));
          else if (remotes.length) issues.push(issueFor(script, 'warning', 'JSON_REMOTE_REFERENCE', `Inline JSON contains remote references: ${remotes[0]}`));
        } catch (error) {
          issues.push(issueFor(script, 'error', 'INLINE_JSON_INVALID', `Inline ${type} is invalid JSON: ${error.message}`));
        }
      }
    }
  }
  const externalRuntimeCount = [...TRUSTED_RUNTIME_SCRIPTS].reduce((sum, asset) => sum + (inlineScriptAssets.get(`src:${asset}`) ?? 0), 0);
  const inlineRuntimeCount = [...TRUSTED_RUNTIME_SCRIPTS].reduce((sum, asset) => sum + (inlineScriptAssets.get(`inline:${asset}`) ?? 0), 0);
  if (externalRuntimeCount && inlineRuntimeCount) {
    issues.push(issueFor(body, 'error', 'SCRIPT_RUNTIME_MODE_MIXED', 'Do not mix bundle script[src] assets with standalone inline runtime assets.'));
  }
  const runtimeMode = inlineRuntimeCount ? 'inline' : 'src';
  context.actualMode = runtimeMode === 'inline' ? 'standalone' : 'bundle';
  for (const asset of TRUSTED_RUNTIME_SCRIPTS) {
    if ((inlineScriptAssets.get(`${runtimeMode}:${asset}`) ?? 0) !== 1) {
      issues.push(issueFor(body, 'error', 'SCRIPT_RUNTIME_MISSING', `${runtimeMode === 'inline' ? 'Standalone' : 'Bundle'} deck requires exactly one canonical ${asset}.`));
    }
  }
  for (const node of allElements) {
    const attrs = FETCH_RESOURCE_ATTRIBUTES[node.tagName];
    if (!attrs) continue;
    for (const attr of attrs) {
      const value = getAttr(node, attr);
      if (!value) continue;
      const candidates = attr === 'srcset' || attr === 'imagesrcset' ? srcsetCandidates(value) : [value];
      for (const candidate of candidates) {
        const localPath = checkReference(context, { value: candidate, node, baseDir: deckRoot, kind: `${node.tagName}[${attr}]` });
        if (localPath && node.tagName === 'link' && attr === 'href'
          && (getAttr(node, 'rel') ?? '').toLowerCase().split(/\s+/).includes('stylesheet')) {
          const displayPath = relative(deckRoot, localPath).split('\\').join('/');
          context.css.linkedHrefs.add(normalizeHref(displayPath));
          readCssGraph(context, localPath, displayPath, node);
        }
      }
    }
  }
  const inlineStyleAssets = new Map();
  for (const style of allElements.filter((node) => node.tagName === 'style')) {
    const bundledAsset = getAttr(style, 'data-web-slide-asset');
    const isCanonicalStylesheet = bundledAsset && allowedBundledStylesheets.has(normalizeHref(bundledAsset));
    const displayPath = isCanonicalStylesheet ? normalizeHref(bundledAsset) : `${input}:style`;
    if (bundledAsset && !isCanonicalStylesheet) {
      issues.push(issueFor(style, 'error', 'INLINE_ASSET_MARKER_INVALID', `Inline style asset marker "${bundledAsset}" is invalid.`));
    }
    if (isCanonicalStylesheet) {
      const count = (inlineStyleAssets.get(displayPath) ?? 0) + 1;
      inlineStyleAssets.set(displayPath, count);
      if (count > 1) issues.push(issueFor(style, 'error', 'STYLE_ASSET_DUPLICATE', `Inline stylesheet "${displayPath}" is included more than once.`));
      if (style.parent !== head) issues.push(issueFor(style, 'error', 'STYLE_ASSET_LOCATION_INVALID', `Inline stylesheet "${displayPath}" must be a direct child of <head>.`));
      const canonical = readFileSync(resolve(DEFAULT_SKILL_ROOT, displayPath), 'utf8');
      if (digestText(rawTextContent(style)) !== digestText(canonical)) {
        issues.push(issueFor(style, 'error', 'INLINE_STYLE_CONTENT_MISMATCH', `Inline stylesheet "${displayPath}" does not match the canonical asset.`));
      }
    }
    const scan = scanCss(textContent(style), displayPath);
    if (isCanonicalStylesheet) {
      context.css.linkedHrefs.add(displayPath);
      context.css.files.set(displayPath, scan);
    }
    for (const name of scan.classes) context.css.classes.add(name);
    for (const name of scan.definitions) context.css.variables.add(name);
    context.css.uses.push(...scan.uses);
    for (const url of scan.urls) checkReference(context, { value: url.value, node: style, baseDir: deckRoot, kind: 'style CSS url()', fromCss: true });
  }
  if (themeId && contracts.components.themes[themeId]) checkActiveContractCss(context, contracts, themeId);
  for (const use of context.css.uses) {
    if (!context.css.variables.has(use.name) && !use.hasFallback) {
      issues.push({ severity: 'error', code: 'CSS_VARIABLE_UNDEFINED', message: `CSS variable var(${use.name}) is used but not defined in loaded styles.`, location: { file: use.file, line: use.line, column: use.column } });
    }
  }
  const classUsage = new Map();
  for (const node of allElements) for (const className of classTokens(node)) if (!classUsage.has(className)) classUsage.set(className, node);
  for (const [className, node] of classUsage) {
    if (!context.css.classes.has(className)) issues.push(issueFor(node, 'error', 'CSS_CLASS_UNDEFINED', `Class ".${className}" is used in HTML but not defined in loaded stylesheets or <style> blocks.`));
  }
  const idOwners = new Map();
  for (const node of allElements) {
    const id = getAttr(node, 'id');
    if (!id) continue;
    if (idOwners.has(id)) issues.push(issueFor(node, 'error', 'DOM_ID_DUPLICATE', `DOM id "${id}" is duplicated.`));
    else idOwners.set(id, node);
  }

  const deckRoots = allElements.filter((node) => getAttr(node, 'id') === 'deck');
  if (deckRoots.length !== 1) {
    issues.push({ severity: 'error', code: 'DECK_ROOT_INVALID', message: `Document must contain exactly one #deck root; found ${deckRoots.length}.`, location: { file: input, line: 1, column: 1 } });
  }
  const slides = allElements.filter((node) => node.tagName === 'section' && hasClass(node, 'slide'));
  if (!slides.length) issues.push({ severity: 'error', code: 'SLIDES_MISSING', message: 'No <section class="slide"> elements were found.', location: { file: input, line: 1, column: 1 } });
  const slideIds = new Map();
  const layoutMap = new Map(contracts.layouts.layouts.map((layout) => [layout.id, layout]));
  const modifierMap = new Map(contracts.layouts.modifiers.map((modifier) => [modifier.id, modifier]));
  for (const [index, slide] of slides.entries()) {
    const ordinal = index + 1;
    const slideId = getAttr(slide, 'data-slide-id');
    if (!slideId) issues.push(issueFor(slide, 'error', 'SLIDE_ID_MISSING', `Slide ${ordinal} must declare data-slide-id.`));
    else if (slideIds.has(slideId)) issues.push(issueFor(slide, 'error', 'SLIDE_ID_DUPLICATE', `data-slide-id "${slideId}" is duplicated.`));
    else {
      slideIds.set(slideId, slide);
      if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slideId)) issues.push(issueFor(slide, 'error', 'SLIDE_ID_INVALID', `data-slide-id "${slideId}" must use lower-kebab-case.`));
    }
    if (deckRoots.length === 1 && slide.parent !== deckRoots[0]) {
      issues.push(issueFor(slide, 'error', 'SLIDE_NOT_DIRECT_DECK_CHILD', `Slide ${slideId || ordinal} must be a direct child of #deck.`));
    }
    const directElementChildren = slide.children.filter((node) => node.type === 'element');
    const canvasCards = directElementChildren.filter((node) => node.tagName === 'div' && hasClass(node, 'canvas-card'));
    const layoutId = getAttr(slide, 'data-layout');
    if (!layoutId) issues.push(issueFor(slide, 'error', 'LAYOUT_MISSING', `Slide ${slideId || ordinal} must declare data-layout.`));
    else {
      const layout = layoutMap.get(layoutId);
      if (!layout) issues.push(issueFor(slide, 'error', 'LAYOUT_UNKNOWN', `Layout "${layoutId}" is not registered in layouts.json.`));
      else {
        if (themeId && !layout.themes.includes(themeId)) issues.push(issueFor(slide, 'error', 'LAYOUT_THEME_MISMATCH', `Layout "${layoutId}" is not available for theme "${themeId}".`));
        if (layout.componentClass && !(canvasCards.length === 1 && hasClass(canvasCards[0], layout.componentClass))) {
          issues.push(issueFor(slide, 'error', 'LAYOUT_CLASS_MISSING', `Layout "${layoutId}" requires class ".${layout.componentClass}" on the direct canvas-card.`));
        }
      }
    }
    const modifierValue = getAttr(slide, 'data-modifiers');
    if (modifierValue) {
      for (const modifierId of modifierValue.split(/[\s,]+/).filter(Boolean)) {
        const modifier = modifierMap.get(modifierId);
        if (!modifier) { issues.push(issueFor(slide, 'error', 'MODIFIER_UNKNOWN', `Modifier "${modifierId}" is not registered in layouts.json.`)); continue; }
        if (themeId && !modifier.themes.includes(themeId)) issues.push(issueFor(slide, 'error', 'MODIFIER_THEME_MISMATCH', `Modifier "${modifierId}" is not available for theme "${themeId}".`));
        if (modifier.componentClass && ![slide, ...descendants(slide)].some((node) => hasClass(node, modifier.componentClass))) {
          issues.push(issueFor(slide, 'error', 'MODIFIER_CLASS_MISSING', `Modifier "${modifierId}" requires class ".${modifier.componentClass}".`));
        }
      }
    }
    if (canvasCards.length !== 1) issues.push(issueFor(slide, 'error', 'CANVAS_CARD_INVALID', `Slide ${slideId || ordinal} must have exactly one direct <div class="canvas-card ..."> child.`));
    if (directElementChildren.some((node) => !canvasCards.includes(node))) issues.push(issueFor(slide, 'error', 'SLIDE_CONTENT_OUTSIDE_CANVAS', `Slide ${slideId || ordinal} has element content outside its canvas-card.`));
    if (!descendants(slide, (node) => /^h[1-3]$/.test(node.tagName)).length) issues.push(issueFor(slide, 'error', 'SLIDE_HEADING_MISSING', `Slide ${slideId || ordinal} needs at least one h1, h2, or h3 heading.`));
    const evidence = getAttr(slide, 'data-evidence');
    if (!['none', 'required'].includes(evidence)) issues.push(issueFor(slide, 'error', 'EVIDENCE_DECLARATION_MISSING', `Slide ${slideId || ordinal} must set data-evidence="none|required".`));
    if (evidencePolicy === 'required' && evidence === 'none') issues.push(issueFor(slide, 'error', 'EVIDENCE_POLICY_VIOLATION', `Slide ${slideId || ordinal} cannot use data-evidence="none" under required evidence policy.`));
    const sourceNotes = descendants(slide, (node) => hasClass(node, 'source-note'));
    for (const note of sourceNotes) {
      if (!validSource(getAttr(note, 'data-source')) || !validSourceDate(getAttr(note, 'data-source-date'))) {
        issues.push(issueFor(note, 'error', 'SOURCE_NOTE_FIELDS_MISSING', 'Every .source-note needs a real data-source and a data-source-date containing a four-digit year; placeholders are rejected.'));
      }
    }
    if (evidence === 'required' && !sourceNotes.some((note) =>
      validSource(getAttr(note, 'data-source')) && validSourceDate(getAttr(note, 'data-source-date')))) {
      issues.push(issueFor(slide, 'error', 'SOURCE_NOTE_REQUIRED', `Slide ${slideId || ordinal} requires a valid .source-note[data-source][data-source-date].`));
    }
    if (evidence === 'none' && sourceNotes.length) issues.push(issueFor(slide, 'warning', 'EVIDENCE_DECLARATION_MISMATCH', `Slide ${slideId || ordinal} declares no evidence but contains source notes.`));
    const animate = (getAttr(slide, 'data-animate') ?? '').split(/\s+/).filter(Boolean);
    const animationRequirements = { pipeline: ['step', 'arrow'], list: ['item'], grid: ['cell'], hero: ['hero-text', 'hero-bg'] };
    for (const animation of animate) {
      const roles = animationRequirements[animation];
      if (roles && !descendants(slide, (node) => roles.includes(getAttr(node, 'data-anim'))).length) {
        issues.push(issueFor(slide, 'error', 'ANIMATION_TARGET_MISSING', `Animation "${animation}" has no matching data-anim target (${roles.join(' or ')}).`));
      }
    }
  }
  context.slideIds = slides.map((slide) => getAttr(slide, 'data-slide-id') ?? null);
  context.layouts = slides.map((slide) => getAttr(slide, 'data-layout') ?? null);
  for (const image of allElements.filter((node) => node.tagName === 'img')) {
    if (!hasAttr(image, 'alt')) issues.push(issueFor(image, 'error', 'IMAGE_ALT_MISSING', 'Every img must have an alt attribute.'));
    else if (getAttr(image, 'alt') === '' && (getAttr(image, 'role') ?? '').toLowerCase() !== 'presentation') {
      issues.push(issueFor(image, 'error', 'IMAGE_DECORATIVE_ROLE_MISSING', 'An empty img alt requires role="presentation".'));
    }
  }
  for (const button of allElements.filter((node) => node.tagName === 'button')) {
    if (!textContent(button) && !(getAttr(button, 'aria-label') ?? '').trim()) issues.push(issueFor(button, 'error', 'BUTTON_NAME_MISSING', 'Every button needs visible text or a non-empty aria-label.'));
  }
  checkDeliveryManifest(context);
  if (typeof options._beforeSnapshotRecheck === 'function') options._beforeSnapshotRecheck();
  const deliveryEnd = captureValidationSnapshot(input);
  if (!sameValidationSnapshot(deliveryStart, deliveryEnd)) {
    issues.push({
      severity: 'error',
      code: 'DELIVERY_CHANGED_DURING_QA',
      message: 'Delivery files changed while static QA was running; refusing to publish a stale success receipt.',
      location: { file: input, line: 1, column: 1 },
    });
  }
  const sortedIssues = sortIssues(issues);
  const errorCount = sortedIssues.filter((entry) => entry.severity === 'error').length;
  const warningCount = sortedIssues.filter((entry) => entry.severity === 'warning').length;
  const report = {
    schemaVersion: REPORT_SCHEMA_VERSION,
    validator: { name: 'tool-web-slide/deck-validator', version: VALIDATOR_VERSION },
    generatedAt: new Date().toISOString(),
    input,
    inputSha256: deliveryStart.receipt.inputSha256,
    manifestSha256: deliveryStart.receipt.manifestSha256,
    deliverySnapshot: deliveryStart.receipt,
    slideIds: context.slideIds,
    layouts: context.layouts,
    deckRoot,
    valid: errorCount === 0,
    exitCode: errorCount === 0 ? 0 : 1,
    configuration: {
      theme: themeId ?? null,
      deliveryProfile,
      requiredGates,
      aspect: aspectValue ?? null,
      target: context.target,
      offlineRequired,
      evidencePolicy,
      configFile: config.path,
    },
    summary: {
      slides: slides.length, errors: errorCount, warnings: warningCount,
      resourcesChecked: context.resources.checked.length,
      resourcesMissing: context.resources.missing.length,
      remoteResources: context.resources.remote.length,
    },
    resources: context.resources,
    contracts: { layouts: contracts.files.layoutsFile, components: contracts.files.componentsFile },
    issues: sortedIssues,
  };
  if (options.writeReport !== false) {
    const reportPath = resolve(options.reportPath ?? join(deckRoot, 'qa-report', 'qa-report.json'));
    try {
      mkdirSync(dirname(reportPath), { recursive: true });
      writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
      report.reportPath = reportPath;
    } catch (error) {
      throw new DeckEnvironmentError(`Unable to write QA report ${reportPath}: ${error.message}`, 'REPORT_WRITE_FAILED');
    }
  }
  return report;
}

export function validateComponentContracts(options = {}) {
  const rootDir = resolve(options.rootDir ?? DEFAULT_SKILL_ROOT);
  const contractDir = resolve(options.contractDir ?? join(rootDir, 'references'));
  const contracts = loadContracts(contractDir);
  const issues = [];
  const fakeContext = {
    input: contracts.files.componentsFile, deckRoot: rootDir, issues, allowRemote: false, offlineRequired: true,
    resources: { checked: [], missing: [], remote: [] },
    css: { classes: new Set(), variables: new Set(), uses: [], files: new Map(), linkedHrefs: new Set() },
  };
  checkContractShape(fakeContext, contracts);
  const scans = new Map();
  const scanFile = (reference) => {
    if (!reference) return null;
    const normalized = normalizeHref(reference);
    if (scans.has(normalized)) return scans.get(normalized);
    const file = resolve(rootDir, normalized);
    if (!existsSync(file)) {
      issues.push({ severity: 'error', code: 'CONTRACT_STYLESHEET_MISSING', message: `Contract stylesheet not found: ${normalized}.`, location: { file, line: 1, column: 1 } });
      scans.set(normalized, null);
      return null;
    }
    const scan = scanCss(readFileSync(file, 'utf8'), normalized);
    scans.set(normalized, scan);
    return scan;
  };
  for (const [themeId, theme] of Object.entries(contracts.components.themes)) {
    const themeScan = scanFile(theme.stylesheet);
    if (themeScan) {
      for (const className of theme.classes ?? []) {
        if (!themeScan.classes.has(className) || !themeScan.classDeclarations.get(className)) issues.push({ severity: 'error', code: 'CONTRACT_CLASS_NOT_IMPLEMENTED', message: `Theme "${themeId}" class ".${className}" is absent or has no declarations in ${theme.stylesheet}.`, location: { file: resolve(rootDir, theme.stylesheet), line: 1, column: 1 } });
      }
    }
    const baseScan = scanFile(theme.baseStylesheet);
    if (baseScan) {
      for (const className of contracts.components.runtimeClasses) {
        if (!baseScan.classes.has(className) || !baseScan.classDeclarations.get(className)) issues.push({ severity: 'error', code: 'CONTRACT_RUNTIME_CLASS_NOT_IMPLEMENTED', message: `Runtime class ".${className}" is absent or has no declarations in ${theme.baseStylesheet}.`, location: { file: resolve(rootDir, theme.baseStylesheet), line: 1, column: 1 } });
      }
    }
  }
  const declaredClasses = new Set([
    ...contracts.components.runtimeClasses,
    ...Object.values(contracts.components.themes).flatMap((theme) => theme.classes ?? []),
  ]);
  for (const entry of [...contracts.layouts.layouts, ...contracts.layouts.modifiers]) {
    if (entry.componentClass && !declaredClasses.has(entry.componentClass)) {
      issues.push({ severity: 'error', code: 'CONTRACT_LAYOUT_CLASS_UNDECLARED', message: `${entry.id} references undeclared component class ".${entry.componentClass}".`, location: { file: contracts.files.layoutsFile, line: 1, column: 1 } });
    }
  }
  const sorted = sortIssues(issues);
  return { valid: !sorted.some((issue) => issue.severity === 'error'), issues: sorted, contracts };
}

export function writeJsonReport(report, reportPath) {
  const output = resolve(reportPath);
  mkdirSync(dirname(output), { recursive: true });
  writeFileSync(output, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  return output;
}

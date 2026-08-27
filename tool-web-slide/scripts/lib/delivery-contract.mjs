export const TARGET_BROWSERS = Object.freeze(['chromium', 'chrome', 'edge']);
export const TARGET_OSES = Object.freeze(['current', 'linux', 'macos', 'windows']);

export const REQUIRED_GATES = Object.freeze({
  'quick-internal': Object.freeze({ static: true, visual: 'sample', pdf: 'optional' }),
  'standard-client': Object.freeze({ static: true, visual: 'layouts', pdf: 'optional' }),
  'high-assurance': Object.freeze({ static: true, visual: 'all', pdf: 'required' }),
});

export const DELIVERY_PROFILES = Object.freeze(Object.keys(REQUIRED_GATES));

export class DeliveryContractError extends Error {
  constructor(message) {
    super(message);
    this.name = 'DeliveryContractError';
  }
}

function parseEnum(value, allowed, label, fallback) {
  const candidate = value === undefined || value === null ? fallback : value;
  if (typeof candidate !== 'string' || !candidate.trim()) {
    throw new DeliveryContractError(`${label} must be one of: ${allowed.join(', ')}`);
  }
  const normalized = candidate.trim().toLowerCase();
  if (!allowed.includes(normalized)) {
    throw new DeliveryContractError(`${label} "${candidate}" is unsupported; expected one of: ${allowed.join(', ')}`);
  }
  return normalized;
}

export function parseTargetBrowser(value = 'chromium') {
  return parseEnum(value, TARGET_BROWSERS, 'target.browser', 'chromium');
}

export function parseTargetOs(value = 'current') {
  return parseEnum(value, TARGET_OSES, 'target.os', 'current');
}

export function parseDeliveryProfile(value = 'standard-client') {
  return parseEnum(value, DELIVERY_PROFILES, 'deliveryProfile', 'standard-client');
}

export function requiredGatesFor(profile = 'standard-client') {
  return REQUIRED_GATES[parseDeliveryProfile(profile)];
}

export const SVG_FETCH_ELEMENTS = Object.freeze([
  'image',
  'use',
  'feimage',
  'mpath',
  'tref',
  'textpath',
  'cursor',
  'pattern',
  'lineargradient',
  'radialgradient',
]);
export const FETCH_RESOURCE_ATTRIBUTES = Object.freeze({
  audio: Object.freeze(['src']),
  embed: Object.freeze(['src']),
  iframe: Object.freeze(['src']),
  img: Object.freeze(['src', 'srcset']),
  input: Object.freeze(['src']),
  link: Object.freeze(['href', 'imagesrcset']),
  object: Object.freeze(['data']),
  script: Object.freeze(['src']),
  source: Object.freeze(['src', 'srcset']),
  track: Object.freeze(['src']),
  video: Object.freeze(['src', 'poster']),
  ...Object.fromEntries(SVG_FETCH_ELEMENTS.map((element) => [element, Object.freeze(['href', 'xlink:href'])])),
});
export const CSS_RESOURCE_FUNCTIONS = Object.freeze([
  'url',
  'image-set',
  '-webkit-image-set',
  'image',
  'cross-fade',
  'src',
]);

function cssEscapeAt(source, start) {
  if (source[start] !== '\\') return null;
  let index = start + 1;
  if (index >= source.length) return { value: '\uFFFD', end: index };
  if (source[index] === '\r' && source[index + 1] === '\n') return { value: '', end: index + 2 };
  if (/[\n\r\f]/.test(source[index])) return { value: '', end: index + 1 };
  if (/[0-9a-f]/i.test(source[index])) {
    const begin = index;
    while (index < source.length && index - begin < 6 && /[0-9a-f]/i.test(source[index])) index += 1;
    const codePoint = Number.parseInt(source.slice(begin, index), 16);
    if (source[index] === '\r' && source[index + 1] === '\n') index += 2;
    else if (/[\t\n\f\r ]/.test(source[index] ?? '')) index += 1;
    const safeCodePoint = codePoint === 0 || codePoint > 0x10ffff ? 0xfffd : codePoint;
    return { value: String.fromCodePoint(safeCodePoint), end: index };
  }
  return { value: source[index], end: index + 1 };
}

export function decodeCssEscapes(source) {
  if (typeof source !== 'string') throw new DeliveryContractError('CSS source must be a string');
  let output = '';
  let index = 0;
  while (index < source.length) {
    const escape = cssEscapeAt(source, index);
    if (!escape) {
      output += source[index];
      index += 1;
    } else {
      output += escape.value;
      index = escape.end;
    }
  }
  return output;
}

function cssIdentifierAt(source, start) {
  let raw = '';
  let decoded = '';
  let index = start;
  while (index < source.length) {
    const character = source[index];
    if (/[A-Za-z0-9_-]/.test(character)) {
      raw += character;
      decoded += character;
      index += 1;
      continue;
    }
    const escape = cssEscapeAt(source, index);
    if (!escape) break;
    raw += source.slice(index, escape.end);
    decoded += escape.value;
    index = escape.end;
  }
  return raw ? { raw, decoded, end: index } : null;
}

function cssTriviaEnd(source, start) {
  let index = start;
  let obfuscated = false;
  while (index < source.length) {
    if (/\s/.test(source[index])) {
      obfuscated = true;
      index += 1;
    } else if (source[index] === '/' && source[index + 1] === '*') {
      const close = source.indexOf('*/', index + 2);
      if (close < 0) throw new DeliveryContractError('CSS contains an unterminated comment');
      obfuscated = true;
      index = close + 2;
    } else break;
  }
  return { end: index, obfuscated };
}

function cssCodeView(source) {
  let output = '';
  let index = 0;
  while (index < source.length) {
    if (source[index] === '/' && source[index + 1] === '*') {
      const close = source.indexOf('*/', index + 2);
      if (close < 0) throw new DeliveryContractError('CSS contains an unterminated comment');
      index = close + 2;
      continue;
    }
    if (source[index] === '"' || source[index] === "'") {
      const quote = source[index];
      output += quote;
      index += 1;
      while (index < source.length) {
        if (source[index] === '\\') {
          const escape = cssEscapeAt(source, index);
          output += ' ';
          index = escape?.end ?? index + 1;
        } else if (source[index] === quote) {
          output += quote;
          index += 1;
          break;
        } else {
          output += ' ';
          index += 1;
        }
      }
      continue;
    }
    const escape = cssEscapeAt(source, index);
    if (escape) {
      output += escape.value;
      index = escape.end;
    } else {
      output += source[index];
      index += 1;
    }
  }
  return output;
}

function countCssToken(view, name, kind) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const expression = kind === 'at-rule'
    ? new RegExp(`@\\s*${escaped}(?![A-Za-z0-9_-])`, 'gi')
    : new RegExp(`(?:^|[^A-Za-z0-9_-])${escaped}\\s*\\(`, 'gi');
  return [...view.matchAll(expression)].length;
}

export function inspectCssResourceSyntax(source) {
  if (typeof source !== 'string') throw new DeliveryContractError('CSS source must be a string');
  const resources = [];
  let index = 0;
  while (index < source.length) {
    if (source[index] === '/' && source[index + 1] === '*') {
      const close = source.indexOf('*/', index + 2);
      if (close < 0) throw new DeliveryContractError('CSS contains an unterminated comment');
      index = close + 2;
      continue;
    }
    if (source[index] === '"' || source[index] === "'") {
      const quote = source[index];
      index += 1;
      while (index < source.length) {
        if (source[index] === '\\') {
          const escape = cssEscapeAt(source, index);
          index = escape?.end ?? index + 1;
        } else if (source[index] === quote) {
          index += 1;
          break;
        } else index += 1;
      }
      continue;
    }
    if (source[index] === '@') {
      const trivia = cssTriviaEnd(source, index + 1);
      const identifier = cssIdentifierAt(source, trivia.end);
      if (identifier?.decoded.toLowerCase() === 'import') {
        resources.push({
          kind: 'at-rule',
          name: 'import',
          rawName: identifier.raw,
          obfuscated: trivia.obfuscated || identifier.raw.toLowerCase() !== 'import',
        });
      }
      index = identifier?.end ?? index + 1;
      continue;
    }
    const identifier = cssIdentifierAt(source, index);
    if (!identifier) {
      index += 1;
      continue;
    }
    const trivia = cssTriviaEnd(source, identifier.end);
    const name = identifier.decoded.toLowerCase();
    if (source[trivia.end] === '(' && CSS_RESOURCE_FUNCTIONS.includes(name)) {
      resources.push({
        kind: 'function',
        name,
        rawName: identifier.raw,
        obfuscated: trivia.obfuscated || identifier.raw.toLowerCase() !== name,
      });
    }
    index = identifier.end;
  }
  const canonicalView = cssCodeView(source);
  for (const name of CSS_RESOURCE_FUNCTIONS) {
    const detected = resources.filter((entry) => entry.kind === 'function' && entry.name === name).length;
    const canonical = countCssToken(canonicalView, name, 'function');
    for (let extra = detected; extra < canonical; extra += 1) {
      resources.push({ kind: 'function', name, rawName: '(escaped-or-commented)', obfuscated: true });
    }
  }
  const imports = resources.filter((entry) => entry.kind === 'at-rule' && entry.name === 'import').length;
  const canonicalImports = countCssToken(canonicalView, 'import', 'at-rule');
  for (let extra = imports; extra < canonicalImports; extra += 1) {
    resources.push({ kind: 'at-rule', name: 'import', rawName: '(escaped-or-commented)', obfuscated: true });
  }
  return resources;
}

function dynamicImportRanges(source) {
  const ranges = [];
  let index = 0;
  let state = 'code';
  let quote = null;
  while (index < source.length) {
    const current = source[index];
    const next = source[index + 1];
    if (state === 'line-comment') {
      if (current === '\n' || current === '\r') state = 'code';
      index += 1;
      continue;
    }
    if (state === 'block-comment') {
      if (current === '*' && next === '/') {
        state = 'code';
        index += 2;
      } else index += 1;
      continue;
    }
    if (state === 'string') {
      if (current === '\\') index += 2;
      else if (current === quote) {
        state = 'code';
        index += 1;
      } else index += 1;
      continue;
    }
    if (current === '/' && next === '/') {
      state = 'line-comment';
      index += 2;
      continue;
    }
    if (current === '/' && next === '*') {
      state = 'block-comment';
      index += 2;
      continue;
    }
    if (current === '"' || current === "'" || current === '`') {
      state = 'string';
      quote = current;
      index += 1;
      continue;
    }
    if (source.startsWith('import', index)
        && !/[A-Za-z0-9_$]/.test(source[index - 1] ?? '')
        && !/[A-Za-z0-9_$]/.test(source[index + 6] ?? '')) {
      let open = index + 6;
      while (/\s/.test(source[open] ?? '')) open += 1;
      if (source[open] === '(') {
        let cursor = open + 1;
        let depth = 1;
        let innerState = 'code';
        let innerQuote = null;
        while (cursor < source.length && depth > 0) {
          const character = source[cursor];
          const following = source[cursor + 1];
          if (innerState === 'line-comment') {
            if (character === '\n' || character === '\r') innerState = 'code';
            cursor += 1;
            continue;
          }
          if (innerState === 'block-comment') {
            if (character === '*' && following === '/') {
              innerState = 'code';
              cursor += 2;
            } else cursor += 1;
            continue;
          }
          if (innerState === 'string') {
            if (character === '\\') cursor += 2;
            else if (character === innerQuote) {
              innerState = 'code';
              cursor += 1;
            } else cursor += 1;
            continue;
          }
          if (character === '/' && following === '/') {
            innerState = 'line-comment';
            cursor += 2;
          } else if (character === '/' && following === '*') {
            innerState = 'block-comment';
            cursor += 2;
          } else if (character === '"' || character === "'" || character === '`') {
            innerState = 'string';
            innerQuote = character;
            cursor += 1;
          } else {
            if (character === '(') depth += 1;
            else if (character === ')') depth -= 1;
            cursor += 1;
          }
        }
        if (depth !== 0) throw new DeliveryContractError('slide-engine.js contains an unterminated dynamic import()');
        ranges.push([index, cursor]);
        index = cursor;
        continue;
      }
    }
    index += 1;
  }
  return ranges;
}

export function standaloneEngineSource(engine) {
  if (typeof engine !== 'string') throw new DeliveryContractError('slide-engine source must be a string');
  const replacement = 'Promise.reject(new Error("Dynamic imports are disabled in standalone mode"))';
  const ranges = dynamicImportRanges(engine);
  let transformed = engine;
  for (const [start, end] of ranges.reverse()) {
    transformed = `${transformed.slice(0, start)}${replacement}${transformed.slice(end)}`;
  }
  transformed = transformed.replaceAll('./motion.min.js', 'standalone-motion-disabled');
  if (/\bimport\b/.test(transformed) || transformed.includes('./motion.min.js')) {
    throw new DeliveryContractError('standalone slide-engine still contains a local dynamic import');
  }
  const prefix = 'window.__WEB_SLIDE_STANDALONE__ = true;\n';
  return transformed.startsWith(prefix) ? transformed : `${prefix}${transformed}`;
}

#!/usr/bin/env node
import { existsSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { assertTargetOs, inspectBrowserRuntime, normalizeTargetBrowser, normalizeTargetOs, readDeckExecutionConfig } from './lib/browser-runtime.mjs';

function localReference(value) {
  return value && !/^(?:https?:|data:|blob:|mailto:|tel:|#|\/\/)/i.test(value);
}

function extractReferences(html) {
  const references = [];
  const regex = /<(script|link|img|source|video)\b[^>]*?\b(src|href|poster)\s*=\s*["']([^"']+)["'][^>]*>/gi;
  for (const match of html.matchAll(regex)) {
    references.push({ tag: match[1].toLowerCase(), attribute: match[2].toLowerCase(), value: match[3] });
  }
  return references;
}

export function browserGateSeverity(deliveryProfile = 'standard-client', requireBrowser = false, draft = false) {
  return !draft || requireBrowser || deliveryProfile === 'high-assurance' ? 'error' : 'warning';
}

export async function runPreflight(options = {}) {
  const checks = [];
  const errors = [];
  const warnings = [];
  const nodeMajor = Number(process.versions.node.split('.')[0]);
  checks.push({ name: 'node', ok: nodeMajor >= 18, detail: process.versions.node });
  if (nodeMajor < 18) errors.push('Node.js 18 or newer is required.');

  let htmlPath = null;
  let executionConfig = {
    targetBrowser: normalizeTargetBrowser(options.targetBrowser || 'chromium'),
    targetOs: normalizeTargetOs(options.targetOs || 'current'),
    deliveryProfile: 'standard-client',
    requiredGates: { static: true, visual: 'layouts', pdf: 'optional' },
    offlineRequired: false
  };
  if (options.htmlPath) {
    htmlPath = resolve(options.htmlPath);
    if (existsSync(htmlPath)) {
      try {
        executionConfig = await readDeckExecutionConfig(htmlPath);
        if ((options.targetBrowser && normalizeTargetBrowser(options.targetBrowser) !== executionConfig.targetBrowser)
            || (options.targetOs && normalizeTargetOs(options.targetOs) !== executionConfig.targetOs)) {
          throw new Error('Preflight target overrides cannot contradict the existing deck target.');
        }
        const osGate = assertTargetOs(executionConfig.targetOs);
        checks.push({ name: 'execution-target', ok: true, detail: { ...executionConfig, ...osGate } });
      } catch (error) {
        checks.push({ name: 'execution-target', ok: false, detail: error.message });
        errors.push(error.message);
      }
    }
  }

  if (!options.htmlPath) {
    try {
      checks.push({ name: 'execution-target', ok: true, detail: assertTargetOs(executionConfig.targetOs) });
    } catch (error) {
      checks.push({ name: 'execution-target', ok: false, detail: error.message });
      errors.push(error.message);
    }
  }
  const browser = await inspectBrowserRuntime({ targetBrowser: executionConfig.targetBrowser });
  const browserSeverity = browserGateSeverity(executionConfig.deliveryProfile, options.requireBrowser === true, options.draft === true);
  checks.push({ name: 'browser-runtime', ok: browser.ok, severity: browserSeverity, detail: browser });
  if (!browser.ok) {
    const message = `${browser.error} Browser rendering is ${browserSeverity === 'error' ? 'required' : 'recommended'} for deliveryProfile=${executionConfig.deliveryProfile}.`;
    (browserSeverity === 'error' ? errors : warnings).push(message);
  }

  if (options.htmlPath) {
    if (!existsSync(htmlPath)) {
      errors.push(`HTML file not found: ${htmlPath}`);
    } else {
      const html = await readFile(htmlPath, 'utf8');
      const base = dirname(htmlPath);
      const references = extractReferences(html);
      const remoteRuntime = references.filter(reference =>
        /^(?:https?:)?\/\//i.test(reference.value)
        && (reference.tag === 'script' || reference.tag === 'link')
      );
      if (remoteRuntime.length) {
        errors.push(`External runtime dependencies are not allowed: ${remoteRuntime.map(item => item.value).join(', ')}`);
      }
      const remoteMedia = references.filter(reference =>
        /^(?:https?:)?\/\//i.test(reference.value)
        && !remoteRuntime.includes(reference)
      );
      if (remoteMedia.length) warnings.push(`Remote media prevents a fully offline deck: ${remoteMedia.map(item => item.value).join(', ')}`);

      for (const reference of references.filter(item => localReference(item.value))) {
        const clean = reference.value.split(/[?#]/, 1)[0];
        const target = resolve(base, clean);
        if (!existsSync(target)) errors.push(`Missing local asset: ${reference.value}`);
      }
      if (!/#deck\b|id=["']deck["']/i.test(html)) errors.push('Deck root #deck is missing.');
      if (!/class=["'][^"']*\bslide\b/i.test(html)) errors.push('No .slide element was found.');
      checks.push({ name: 'html-assets', ok: !errors.some(error => /asset|runtime dependenc|#deck|\.slide/.test(error)), detail: htmlPath });
    }
  }

  return { ok: errors.length === 0, purpose: options.draft === true ? 'draft' : 'delivery', executionConfig, checks, errors, warnings };
}

function printResult(result) {
  for (const check of result.checks) {
    const status = check.ok ? 'PASS' : check.severity === 'warning' ? 'WARN' : 'FAIL';
    console.log(`${status} ${check.name}`);
  }
  result.warnings.forEach(message => console.warn(`WARN ${message}`));
  result.errors.forEach(message => console.error(`ERROR ${message}`));
  console.log(result.ok
    ? result.purpose === 'draft' ? 'Draft preflight passed; browser delivery remains unverified.' : 'Delivery prerequisites passed; actual rendering still requires QA.'
    : 'Preflight failed.');
}

const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  if (process.argv.includes('--help') || process.argv.includes('-h')) {
    console.log('Usage: node scripts/preflight.mjs [--draft | --require-browser] [--target-browser chromium|chrome|edge] [--target-os current|linux|macos|windows] [index.html]');
    process.exit(0);
  }
  try {
    const raw = process.argv.slice(2);
    const options = {};
    const positional = [];
    for (let index = 0; index < raw.length; index++) {
      const argument = raw[index];
      if (argument === '--require-browser') options.requireBrowser = true;
      else if (argument === '--draft') options.draft = true;
      else if (['--target-browser', '--target-os'].includes(argument)) {
        const value = raw[++index];
        if (!value || value.startsWith('-')) throw new Error(`Missing value for ${argument}`);
        options[argument === '--target-browser' ? 'targetBrowser' : 'targetOs'] = value;
      } else if (argument.startsWith('-')) throw new Error(`Unknown option: ${argument}`);
      else positional.push(argument);
    }
    if (options.draft && options.requireBrowser) throw new Error('--draft and --require-browser are mutually exclusive.');
    if (positional.length > 1) throw new Error(`Unexpected argument: ${positional[1]}`);
    const result = await runPreflight({ ...options, htmlPath: positional[0] });
    printResult(result);
    process.exitCode = result.ok ? 0 : 1;
  } catch (error) {
    console.error(`Preflight failed: ${error.message}`);
    process.exitCode = 1;
  }
}

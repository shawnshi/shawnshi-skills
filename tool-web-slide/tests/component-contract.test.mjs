import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { validateComponentContracts } from '../scripts/lib/deck-validator.mjs';

const skillRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

test('published component and layout contracts match implemented CSS', () => {
  const result = validateComponentContracts({ rootDir: skillRoot });
  assert.equal(result.valid, true, JSON.stringify(result.issues, null, 2));
});

test('an empty selector is not a component implementation', () => {
  const root = mkdtempSync(join(tmpdir(), 'web-slide-contract-'));
  mkdirSync(join(root, 'assets'));
  mkdirSync(join(root, 'references'));
  writeFileSync(join(root, 'assets', 'core.css'), '.slide{display:block}.canvas-card{display:block}.layout-hero{}');
  writeFileSync(join(root, 'assets', 'theme.css'), '.component{}');
  writeFileSync(join(root, 'references', 'components.json'), JSON.stringify({
    schemaVersion: '1.0.0',
    themes: { test: { baseStylesheet: 'assets/core.css', stylesheet: 'assets/theme.css', classes: ['component'] } },
    runtimeClasses: ['slide', 'canvas-card', 'layout-hero'],
  }));
  writeFileSync(join(root, 'references', 'layouts.json'), JSON.stringify({
    schemaVersion: '1.0.0',
    layouts: [{ id: 'hero', themes: ['test'], componentClass: 'layout-hero' }],
    modifiers: [],
  }));
  const result = validateComponentContracts({ rootDir: root });
  assert.equal(result.valid, false);
  assert.ok(result.issues.some((issue) => issue.code === 'CONTRACT_CLASS_NOT_IMPLEMENTED'));
});

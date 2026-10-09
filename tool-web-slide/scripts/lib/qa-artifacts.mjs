import { createHash, randomUUID } from 'node:crypto';
import { existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';

const LEDGER = '.web-slide-qa-manifest.json';
const GENERATOR = 'tool-web-slide/qa-artifacts';
const sha256 = value => createHash('sha256').update(value).digest('hex');
const inside = (root, target) => {
  const path = relative(root, target);
  return path !== '' && !path.startsWith('..') && !isAbsolute(path);
};

function safeTarget(root, rootReal, target) {
  const path = resolve(target);
  if (!inside(root, path)) throw new Error(`QA artifact must be inside the delivery root: ${path}`);
  let ancestor = path;
  while (!existsSync(ancestor)) ancestor = dirname(ancestor);
  const canonical = realpathSync(ancestor);
  if (canonical !== rootReal && !inside(rootReal, canonical)) throw new Error(`QA artifact escapes through a symlink: ${path}`);
  if (existsSync(path) && (lstatSync(path).isSymbolicLink() || !lstatSync(path).isFile())) {
    throw new Error(`QA artifact must be a regular non-symlink file: ${path}`);
  }
  return path;
}

export function inspectQaArtifacts(deckRoot, paths) {
  const root = resolve(deckRoot);
  const rootReal = realpathSync(root);
  const ledgerPath = safeTarget(root, rootReal, join(root, LEDGER));
  const ledgerBytes = existsSync(ledgerPath) ? readFileSync(ledgerPath) : null;
  let ledger = { schemaVersion: '1.0.0', generator: GENERATOR, files: {} };
  if (ledgerBytes) {
    ledger = JSON.parse(ledgerBytes.toString('utf8'));
    if (ledger.schemaVersion !== '1.0.0' || ledger.generator !== GENERATOR || !ledger.files
        || Array.isArray(ledger.files) || typeof ledger.files !== 'object'
        || Object.values(ledger.files).some(hash => !/^[a-f0-9]{64}$/.test(hash))) {
      throw new Error('Unrecognized QA ownership manifest; preserve it and use a new delivery directory.');
    }
  }
  const targets = paths.map(path => safeTarget(root, rootReal, path));
  const existing = new Map();
  for (const target of targets) {
    if (target === ledgerPath) throw new Error('QA artifacts cannot replace their ownership manifest.');
    const key = relative(root, target).split('\\').join('/');
    const bytes = existsSync(target) ? readFileSync(target) : null;
    if (bytes && ledger.files[key] !== sha256(bytes)) {
      throw new Error(`Refusing to overwrite unmanaged or user-modified QA artifact: ${key}. Preserve it and use a new delivery directory.`);
    }
    existing.set(target, bytes);
  }
  return { root, rootReal, ledgerPath, ledgerBytes, ledger, targets, existing };
}

export function publishQaArtifacts(deckRoot, artifacts) {
  const entries = [...artifacts].map(([path, bytes]) => [resolve(path), Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes)]);
  if (new Set(entries.map(([path]) => path)).size !== entries.length) throw new Error('Duplicate QA artifact targets.');
  const state = inspectQaArtifacts(deckRoot, entries.map(([path]) => path));
  const files = { ...state.ledger.files };
  for (const [path, bytes] of entries) files[relative(state.root, path).split('\\').join('/')] = sha256(bytes);
  const ledger = Buffer.from(`${JSON.stringify({ ...state.ledger, files }, null, 2)}\n`);
  const outputs = [...entries, [state.ledgerPath, ledger]];
  const previous = new Map([...state.existing, [state.ledgerPath, state.ledgerBytes]]);
  const staged = new Map();
  const committed = [];
  try {
    for (const [path, bytes] of outputs) {
      mkdirSync(dirname(path), { recursive: true });
      safeTarget(state.root, state.rootReal, path);
      const temp = join(dirname(path), `.${randomUUID()}.web-slide.tmp`);
      staged.set(path, temp);
      writeFileSync(temp, bytes, { flag: 'wx' });
    }
    // A stale report must never authorize replacement of a concurrently edited artifact.
    for (const [path] of outputs) {
      safeTarget(state.root, state.rootReal, path);
      const expected = previous.get(path);
      const actual = existsSync(path) ? readFileSync(path) : null;
      if ((expected === null) !== (actual === null) || (expected && !expected.equals(actual))) {
        throw new Error(`QA artifact changed before publication: ${path}`);
      }
    }
    for (const [path] of outputs) {
      renameSync(staged.get(path), path);
      committed.push(path);
    }
  } catch (error) {
    const rollbackErrors = [];
    for (const path of committed.reverse()) {
      try {
        const bytes = previous.get(path);
        if (bytes === null) rmSync(path);
        else {
          const temp = join(dirname(path), `.${randomUUID()}.web-slide-restore.tmp`);
          staged.set(`${path}:restore`, temp);
          writeFileSync(temp, bytes, { flag: 'wx' });
          renameSync(temp, path);
        }
      } catch (rollbackError) { rollbackErrors.push(rollbackError.message); }
    }
    if (rollbackErrors.length) throw new AggregateError([error, ...rollbackErrors.map(message => new Error(message))], 'QA publication failed and rollback was incomplete.');
    throw error;
  } finally {
    for (const temp of staged.values()) if (existsSync(temp)) rmSync(temp);
  }
}

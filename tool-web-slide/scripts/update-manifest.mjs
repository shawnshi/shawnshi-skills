#!/usr/bin/env node

import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { readFile, readdir, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_SKILL_ROOT = path.resolve(SCRIPT_DIR, '..');
const MANIFEST_NAME = 'resource-manifest.json';
const TEXT_EXTENSIONS = new Set([
  '.css', '.csv', '.html', '.js', '.json', '.md', '.mjs', '.svg', '.txt', '.yaml', '.yml',
]);
const SKIP_DIRECTORIES = new Set(['.git', 'node_modules']);
// These files are rewritten by the skill materializer after Git sync. They are
// packaging metadata rather than runtime dependencies, so hashing them would
// make an otherwise valid resource manifest stale after every materialization.
const PLATFORM_MANAGED_FILES = new Set(['agents/openai.yaml', 'assets/icon.svg']);

function toPosix(value) {
  return value.split(path.sep).join('/');
}

function isTextFile(filePath) {
  return TEXT_EXTENSIONS.has(path.extname(filePath).toLowerCase());
}

function normalizedBytes(filePath, bytes) {
  if (!isTextFile(filePath)) return bytes;
  return Buffer.from(bytes.toString('utf8').replace(/\r\n?/g, '\n'), 'utf8');
}

function hashBytes(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

async function hashFile(root, relativePath) {
  const filePath = path.join(root, ...relativePath.split('/'));
  const bytes = await readFile(filePath);
  return hashBytes(normalizedBytes(relativePath, bytes));
}

async function walk(root, relative = '') {
  const directory = relative ? path.join(root, ...relative.split('/')) : root;
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name, 'en'))) {
    if (entry.name === MANIFEST_NAME && !relative) continue;
    if (entry.isDirectory() && SKIP_DIRECTORIES.has(entry.name)) continue;
    const child = relative ? `${relative}/${entry.name}` : entry.name;
    if (entry.isDirectory()) files.push(...await walk(root, child));
    else if (entry.isFile() && !PLATFORM_MANAGED_FILES.has(child)) files.push(child);
  }
  return files;
}

function extractDeclaredDependencies(skillMarkdown) {
  const pattern = /(?:^|[\s`("'])((?:assets|built-in-skills|references|scripts|starter-components)\/[A-Za-z0-9._/-]+)/gm;
  const results = new Set();
  for (const match of skillMarkdown.matchAll(pattern)) {
    results.add(match[1].replace(/[),.;:'"`]+$/g, ''));
  }
  return [...results].sort((a, b) => a.localeCompare(b, 'en'));
}

function comparable(manifest) {
  if (!manifest || typeof manifest !== 'object') return manifest;
  const clone = structuredClone(manifest);
  delete clone.generated_at;
  return clone;
}

function sameStructure(a, b) {
  return JSON.stringify(comparable(a)) === JSON.stringify(comparable(b));
}

export async function createResourceManifest(skillRoot = DEFAULT_SKILL_ROOT, previous = null) {
  const root = path.resolve(skillRoot);
  const allFiles = await walk(root);
  if (!allFiles.includes('SKILL.md')) throw new Error(`SKILL.md 不存在：${root}`);

  const topLevelFiles = allFiles.filter((file) => !file.includes('/'));
  const topLevelDirectories = [...new Set(allFiles.filter((file) => file.includes('/')).map((file) => file.split('/')[0]))]
    .sort((a, b) => a.localeCompare(b, 'en'));
  const hashes = new Map();
  for (const file of allFiles) hashes.set(file, await hashFile(root, file));

  const skillMarkdown = await readFile(path.join(root, 'SKILL.md'), 'utf8');
  let skillName = previous?.skill ?? path.basename(root);
  if (hashes.has('package.json')) {
    try {
      const packageInfo = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8'));
      if (typeof packageInfo.name === 'string' && packageInfo.name) skillName = packageInfo.name;
    } catch {
      // A malformed package.json is still represented by its file hash; skill validation reports it separately.
    }
  }
  const declaredPaths = new Set(extractDeclaredDependencies(skillMarkdown));
  for (const item of previous?.declared_local_dependencies ?? []) {
    if (typeof item?.path === 'string') declaredPaths.add(item.path);
  }
  const declared = [];
  const missing = [];
  for (const dependencyPath of [...declaredPaths].sort((a, b) => a.localeCompare(b, 'en'))) {
    const absolute = path.resolve(root, dependencyPath);
    const relative = toPosix(path.relative(root, absolute));
    const safe = relative !== '..' && !relative.startsWith('../') && !path.isAbsolute(relative);
    let exists = false;
    let digest = null;
    if (safe && existsSync(absolute)) {
      const info = await stat(absolute);
      exists = info.isFile();
      if (exists) digest = hashes.get(relative) ?? await hashFile(root, relative);
    }
    const entry = {
      path: dependencyPath,
      exists,
      resolved_path: safe ? `${path.basename(root)}/${relative}` : null,
      ...(digest ? { sha256: digest } : {}),
    };
    declared.push(entry);
    if (!exists) missing.push(dependencyPath);
  }

  const manifest = {
    schema_version: 3,
    skill: skillName,
    generated_at: previous?.generated_at ?? new Date().toISOString(),
    hash_algorithm: 'SHA-256',
    text_hash_normalization: 'LF',
    skill_md: 'SKILL.md',
    skill_md_sha256: hashes.get('SKILL.md'),
    top_level_files: topLevelFiles,
    top_level_file_hashes: topLevelFiles.map((file) => ({ path: file, sha256: hashes.get(file) })),
    top_level_directories: topLevelDirectories,
    resource_directories: topLevelDirectories.map((name) => ({
      name,
      file_count: allFiles.filter((file) => file.startsWith(`${name}/`)).length,
    })),
    resource_file_hashes: allFiles
      .filter((file) => file.includes('/'))
      .map((file) => ({ path: file, sha256: hashes.get(file) })),
    declared_local_dependencies: declared,
    missing_declared_dependencies: missing,
  };
  return manifest;
}

export async function updateResourceManifest({ skillRoot = DEFAULT_SKILL_ROOT, check = false } = {}) {
  const root = path.resolve(skillRoot);
  const manifestPath = path.join(root, MANIFEST_NAME);
  let previous = null;
  if (existsSync(manifestPath)) {
    try {
      previous = JSON.parse(await readFile(manifestPath, 'utf8'));
    } catch {
      previous = null;
    }
  }
  const next = await createResourceManifest(root, previous);
  const current = previous && sameStructure(previous, next);
  if (check) return { ok: Boolean(current), changed: !current, manifestPath, manifest: next };
  if (current) return { ok: true, changed: false, manifestPath, manifest: previous };
  next.generated_at = new Date().toISOString();
  await writeFile(manifestPath, `${JSON.stringify(next, null, 2)}\n`, 'utf8');
  return { ok: true, changed: true, manifestPath, manifest: next };
}

function parseCli(argv) {
  let skillRoot = null;
  let check = false;
  let help = false;
  for (const arg of argv) {
    if (arg === '--check') { check = true; continue; }
    if (arg === '--help' || arg === '-h') { help = true; continue; }
    if (arg.startsWith('--')) throw new Error(`未知参数：${arg}`);
    if (skillRoot) throw new Error(`只能指定一个 skillDir：${arg}`);
    skillRoot = arg;
  }
  return { skillRoot: skillRoot ?? DEFAULT_SKILL_ROOT, check, help };
}

function usage() {
  return 'Usage: node scripts/update-manifest.mjs [skillDir] [--check]';
}

async function main() {
  const options = parseCli(process.argv.slice(2));
  if (options.help) {
    process.stdout.write(`${usage()}\n`);
    return;
  }
  const result = await updateResourceManifest(options);
  process.stdout.write(`${JSON.stringify({
    ok: result.ok,
    changed: result.changed,
    manifestPath: result.manifestPath,
    missing: result.manifest.missing_declared_dependencies,
  }, null, 2)}\n`);
  if (options.check && !result.ok) process.exitCode = 1;
}

const isMain = process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;
if (isMain) {
  main().catch((error) => {
    process.stderr.write(`update-manifest: ${error.message}\n`);
    process.exitCode = 1;
  });
}

#!/usr/bin/env node
import { readFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const vaultDir = join(__dirname, '..', 'design-vault');

const style = process.argv[2]?.toUpperCase();

if (style !== 'A' && style !== 'B' && style !== 'C') {
  console.error('Usage: node assemble-context.mjs <A|B|C>');
  console.error('  A: 电子杂志风 (Magazine)');
  console.error('  B: 瑞士国际主义风 (Swiss)');
  console.error('  C: 极简医疗风 (Winning Clinical)');
  process.exit(2);
}

const filesA = [
  'magazine/themes.md',
  'magazine/layouts.md',
  'magazine/components.md',
  'shared/screenshot-framing.md',
  'shared/image-prompts.md',
  'shared/checklist.md'
];

const filesB = [
  'swiss/themes.md',
  'swiss/layout-lock.md',
  'swiss/layouts.md',
  'swiss/map-component.md',
  'shared/screenshot-framing.md',
  'shared/image-prompts.md',
  'shared/checklist.md'
];

const filesC = [
  'winning/themes.md',
  'winning/layout-lock.md',
  'winning/layouts.md',
  'winning/components.md',
  'winning/map-component.md',
  'shared/screenshot-framing.md',
  'shared/image-prompts.md',
  'shared/checklist.md'
];

let targetFiles;
if (style === 'A') targetFiles = filesA;
else if (style === 'B') targetFiles = filesB;
else if (style === 'C') targetFiles = filesC;

let contextOutput = `# Design Vault Context: Style ${style}\n\n`;

for (const file of targetFiles) {
  const filePath = join(vaultDir, file);
  if (existsSync(filePath)) {
    contextOutput += `## File: ${file}\n`;
    contextOutput += '```markdown\n';
    contextOutput += readFileSync(filePath, 'utf8');
    contextOutput += '\n```\n\n';
  } else {
    console.error(`Warning: Could not find ${file}`);
  }
}

console.log(contextOutput);

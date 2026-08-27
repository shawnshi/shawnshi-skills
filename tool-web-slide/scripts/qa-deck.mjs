#!/usr/bin/env node
import { pathToFileURL } from 'node:url';
import { DeckEnvironmentError, validateDeck, writeJsonReport } from './lib/deck-validator.mjs';

function usage() {
  return [
    'Usage: node scripts/qa-deck.mjs <index.html> [options]',
    '',
    '  --json                 Print JSON to stdout',
    '  --json=<path>          Write an additional JSON copy',
    '  --report=<path>        Override qa-report/qa-report.json',
    '  --offline-required     Reject external resources',
    '  --allow-remote         Explicitly permit external resources',
    '  --evidence-required    Reject data-evidence="none"',
    '  --allow-experimental   Backwards-compatible no-op',
  ].join('\n');
}

function parseArguments(argv) {
  const options = {};
  let input;
  let jsonStdout = false;
  let jsonPath;
  for (const argument of argv) {
    if (argument === '--json') jsonStdout = true;
    else if (argument.startsWith('--json=')) jsonPath = argument.slice(7);
    else if (argument.startsWith('--report=')) options.reportPath = argument.slice(9);
    else if (argument === '--offline-required') options.offlineRequired = true;
    else if (argument === '--allow-remote') options.allowRemote = true;
    else if (argument === '--evidence-required') options.evidencePolicy = 'required';
    else if (argument === '--allow-experimental') options.allowExperimental = true;
    else if (argument === '--help' || argument === '-h') return { help: true };
    else if (argument.startsWith('-')) throw new DeckEnvironmentError(`Unknown option: ${argument}`, 'ARGUMENT_ERROR');
    else if (!input) input = argument;
    else throw new DeckEnvironmentError(`Unexpected argument: ${argument}`, 'ARGUMENT_ERROR');
  }
  if (!input) throw new DeckEnvironmentError('Missing index.html argument.', 'ARGUMENT_ERROR');
  return { input, options, jsonStdout, jsonPath };
}

function humanReport(report) {
  const lines = [`Deck QA ${report.valid ? 'PASSED' : 'FAILED'}: ${report.summary.slides} slide(s), ${report.summary.errors} error(s), ${report.summary.warnings} warning(s).`];
  for (const issue of report.issues) {
    const where = issue.location?.slideId ? `slide ${issue.location.slideId}` : `line ${issue.location?.line ?? 1}`;
    lines.push(`- ${issue.severity.toUpperCase()} ${issue.code} (${where}): ${issue.message}`);
  }
  if (report.reportPath) lines.push(`JSON report: ${report.reportPath}`);
  return lines.join('\n');
}

export function runCli(argv = process.argv.slice(2)) {
  try {
    const parsed = parseArguments(argv);
    if (parsed.help) { console.log(usage()); return 0; }
    const report = validateDeck(parsed.input, parsed.options);
    if (parsed.jsonPath) writeJsonReport(report, parsed.jsonPath);
    if (parsed.jsonStdout) console.log(JSON.stringify(report, null, 2));
    else (report.valid ? console.log : console.error)(humanReport(report));
    return report.exitCode;
  } catch (error) {
    const code = error instanceof DeckEnvironmentError ? error.code : 'UNEXPECTED_ERROR';
    console.error(`Deck QA could not run [${code}]: ${error.message}`);
    return 2;
  }
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) process.exitCode = runCli();

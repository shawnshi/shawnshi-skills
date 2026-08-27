#!/usr/bin/env node
// Compatibility wrapper. New callers should use qa-deck.mjs.
import { runCli } from './qa-deck.mjs';

process.exitCode = runCli(process.argv.slice(2));

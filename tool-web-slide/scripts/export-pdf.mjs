#!/usr/bin/env node
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { execSync } from 'node:child_process';

const file = process.argv[2];
const outFile = process.argv[3] || 'deck.pdf';

if (!file) {
  console.error('Usage: node scripts/export-pdf.mjs <index.html> [output.pdf]');
  process.exit(2);
}

const htmlPath = resolve(file);
if (!existsSync(htmlPath)) {
  console.error(`File not found: ${htmlPath}`);
  process.exit(1);
}

// Dynamically import puppeteer. User must have it installed in the project or globally.
let puppeteer;
try {
  puppeteer = await import('puppeteer');
} catch (e) {
  console.error('Puppeteer is required to export PDF. Please run:');
  console.error('  npm install -D puppeteer');
  process.exit(1);
}

const chromePaths = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
];

let executablePath;
for (const p of chromePaths) {
  if (existsSync(p)) {
    executablePath = p;
    break;
  }
}

(async () => {
  console.log(`Launching Puppeteer to export ${htmlPath}...`);
  const browser = await puppeteer.launch({ 
    headless: 'new',
    executablePath, // Use system Chrome if found
    // Security: Removed --disable-web-security to enforce same-origin policy
    args: ['--no-sandbox', '--disable-setuid-sandbox'] // Prevent sandbox issues
  });
  const page = await browser.newPage();
  
  // Set viewport to standard 1080p 16:9
  await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 2 });
  
  try {
    await page.goto(`file://${htmlPath}`, { waitUntil: 'domcontentloaded', timeout: 5000 });
  } catch (e) {
    console.warn('Navigation wait timed out (common for local files), proceeding to export...');
  }
  await new Promise(r => setTimeout(r, 2000));

  console.log('Restructuring slides for printing...');
  
  // Enable low power mode to stop animations and WebGL backgrounds
  await page.evaluate(() => {
    if (window.__setLowPowerMode) window.__setLowPowerMode(true);
  });
  
  console.log(`Generating PDF -> ${outFile}`);
  await page.pdf({
    path: outFile,
    printBackground: true,
    width: '1920px',
    height: '1080px',
    pageRanges: '',
    timeout: 60000
  });

  await browser.close();
  console.log('Export completed successfully!');
})();

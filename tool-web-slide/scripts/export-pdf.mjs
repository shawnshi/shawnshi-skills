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

(async () => {
  console.log(`Launching Puppeteer to export ${htmlPath}...`);
  const browser = await puppeteer.launch({ headless: 'new' });
  const page = await browser.newPage();
  
  // Set viewport to standard 1080p 16:9
  await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 2 });
  
  await page.goto(`file://${htmlPath}`, { waitUntil: 'networkidle0' });

  console.log('Restructuring slides for printing...');
  
  // Enable low power mode to stop animations and WebGL backgrounds
  await page.evaluate(() => {
    if (window.__setLowPowerMode) window.__setLowPowerMode(true);
  });
  
  // Inject CSS to unwrap the horizontal deck into vertical print pages
  await page.addStyleTag({
    content: `
      @media print {
        @page { size: 1920px 1080px; margin: 0; }
        html, body { 
          width: 1920px !important; 
          height: auto !important; 
          overflow: visible !important; 
        }
        #deck { 
          position: static !important; 
          width: 100% !important; 
          height: auto !important; 
          transform: none !important; 
          display: block !important; 
        }
        .slide { 
          position: relative !important; 
          width: 1920px !important; 
          height: 1080px !important; 
          page-break-after: always !important; 
          page-break-inside: avoid !important;
          break-inside: avoid !important;
          flex: none !important; 
          /* Override light-bg inheritance if needed */
        }
        #nav, #hint, #overview { display: none !important; }
      }
    `
  });

  console.log(`Generating PDF -> ${outFile}`);
  await page.pdf({
    path: outFile,
    printBackground: true,
    width: '1920px',
    height: '1080px',
    pageRanges: ''
  });

  await browser.close();
  console.log('Export completed successfully!');
})();

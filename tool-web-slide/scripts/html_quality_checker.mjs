import fs from 'fs';
import path from 'path';

// html_quality_checker.mjs
// This script parses the generated index.html to ensure the AI did not hallucinate DOM structures or CSS variables.

function checkHtmlQuality(filePath) {
  if (!fs.existsSync(filePath)) {
    console.error(`ERROR: File not found at ${filePath}`);
    process.exit(1);
  }

  const content = fs.readFileSync(filePath, 'utf-8');
  let errors = [];

  // 1. Check for basic slide structure
  const slideRegex = /<section[^>]*class="[^"]*slide[^"]*"[^>]*>/g;
  const slides = [...content.matchAll(slideRegex)];
  if (slides.length === 0) {
    errors.push("FATAL: No <section class=\"slide\"> found.");
  }

  // 2. Check Canvas Card invariant
  if (!content.includes('class="canvas-card"')) {
     errors.push("FATAL: Missing 'canvas-card' wrapper. Each slide must contain a div with class 'canvas-card'.");
  }

  // 3. Detect Hallucinated CSS variables
  const varRegex = /var\(\s*--([a-zA-Z0-9-]+)\s*\)/g;
  const allowedVars = [
    // Standard basic tokens across styles
    'brand', 'brand-light', 'brand-dark', 'bg-light', 'bg-dark', 
    'text-main', 'text-muted', 'serif', 'sans', 'accent',
    'swiss-red', 'swiss-dark', 'swiss-light', 'magazine-charcoal', 'magazine-paper',
    'winning-blue', 'winning-teal', 'winning-gray'
  ]; 
  
  const foundVars = [...content.matchAll(varRegex)].map(m => m[1]);
  foundVars.forEach(v => {
    // Check if the variable is reasonably expected or hallucinated
    // For a real production app, we would dynamically load this from the style dictionary.
    // For now, we do a loose check for common prefixes or known whitelisted ones.
    const isAllowed = allowedVars.includes(v) || v.startsWith('brand-') || v.startsWith('color-') || v.startsWith('bg-') || v.startsWith('text-');
    if (!isAllowed) {
      errors.push(`ERROR: Potential hallucinated CSS variable detected: var(--${v}). You must ONLY use allowed CSS tokens defined in the dictionary.`);
    }
  });

  // 4. Output results
  if (errors.length > 0) {
    console.error("=========================================");
    console.error("QUALITY GATE FAILED!");
    console.error("The generated HTML violates structural invariants:");
    errors.forEach(e => console.error(e));
    console.error("=========================================");
    console.error("-> Action Required: AI Executor must fix these errors in the HTML code and re-run the checker. DO NOT ignore this.");
    process.exit(1);
  } else {
    console.log("QUALITY GATE PASSED! The HTML is structurally sound.");
    process.exit(0);
  }
}

const args = process.argv.slice(2);
if (args.length < 1) {
  console.log("Usage: node html_quality_checker.mjs <path-to-index.html>");
  process.exit(1);
}

checkHtmlQuality(args[0]);

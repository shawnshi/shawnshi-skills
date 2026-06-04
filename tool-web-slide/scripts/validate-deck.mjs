#!/usr/bin/env node
import { readFileSync } from 'node:fs';

const file = process.argv[2];
const allowExperimental = process.argv.includes('--allow-experimental');

if (!file) {
  console.error('Usage: node scripts/validate-deck.mjs <index.html> [--allow-experimental]');
  process.exit(2);
}

const html = readFileSync(file, 'utf8');
const htmlForSlides = html.replace(/<!--[\s\S]*?-->/g, '');
const errors = [];
const warnings = [];

// ==========================================
// 1. CSS Class Validation (Hard Gate)
// ==========================================
const styleMatch = html.match(/<style>([\s\S]*?)<\/style>/);
const styleContent = styleMatch ? styleMatch[1] : '';
const validClasses = new Set();
const classMatches = styleContent.matchAll(/\.([a-zA-Z0-9_-]+)/g);
for (const match of classMatches) {
  validClasses.add(match[1]);
}

// Whitelist of classes injected by JS or external libraries
const whitelistedClasses = new Set([
  'active', 'light-bg', 'dark-bg', 'motion-ready', 'low-power', 'is-win', 'canvas-mode'
]);

const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/);
const bodyContent = bodyMatch ? bodyMatch[1] : '';
const classAttrMatches = bodyContent.matchAll(/\bclass="([^"]+)"/g);

for (const match of classAttrMatches) {
  const classNames = match[1].split(/\s+/).filter(Boolean);
  for (const className of classNames) {
    if (!validClasses.has(className) && !whitelistedClasses.has(className)) {
      errors.push(`CSS Class Validation: Class "${className}" is used in HTML but not defined in <style>.`);
    }
  }
}

// ==========================================
// 2. Slide Structure & Layout Validation
// ==========================================
const slideRe = /<section\b[^>]*class="[^"]*\bslide\b[^"]*"[^>]*>[\s\S]*?<\/section>/g;
const slides = [...htmlForSlides.matchAll(slideRe)].map((m, idx) => ({ 
  idx: idx + 1, 
  html: m[0], 
  tag: m[0].match(/<section\b[^>]*>/)?.[0] ?? '' 
}));

if (!slides.length) {
  errors.push('No <section class="slide"> pages found.');
}

const isSwiss = html.includes('template-swiss.html') || html.includes('grid-12') || html.includes('card-ink');

const allowedSwissLayouts = new Set([
  'SWISS-COVER-ASCII',
  'SWISS-CLOSING-ASCII',
  ...Array.from({ length: 22 }, (_, i) => `S${String(i + 1).padStart(2, '0')}`),
]);

slides.forEach((slide) => {
  const layout = slide.tag.match(/\bdata-layout="([^"]+)"/)?.[1];

  // Swiss style validation
  if (isSwiss) {
    if (!layout) {
      errors.push(`Slide ${slide.idx}: missing data-layout. Swiss locked mode requires S01-S22 or SWISS-COVER-ASCII/SWISS-CLOSING-ASCII.`);
    } else if (!allowedSwissLayouts.has(layout)) {
      errors.push(`Slide ${slide.idx}: data-layout="${layout}" is not registered in layout-lock.md.`);
    }

    if (!allowExperimental && /\bdata-layout="P2[34]\b|Swiss Image Split|Swiss Evidence Grid|swiss-img-split|swiss-img-grid/.test(slide.html)) {
      errors.push(`Slide ${slide.idx}: uses experimental P23/P24 image structure. Use S22 or S15/S16 image-grid adaptations instead.`);
    }
  }

  // Common image checking
  const localImages = [...slide.html.matchAll(/<img\b[^>]*src="images\//g)];
  localImages.forEach((_, imageIndex) => {
    const imgTag = slide.html.slice(_.index, slide.html.indexOf('>', _.index) + 1);
    if (isSwiss && !/\bdata-image-slot="/.test(imgTag)) {
      errors.push(`Slide ${slide.idx}: local image ${imageIndex + 1} missing data-image-slot. Bind every image to a layout slot.`);
    }
  });

  const frameImageRe = /<div\b(?=[^>]*\bclass="([^"]*\bframe-img\b[^"]*)")[^>]*>\s*<img\b(?=[^>]*\bdata-image-slot="([^"]+)")[^>]*>/g;
  const frameImages = [...slide.html.matchAll(frameImageRe)];
  frameImages.forEach((match) => {
    const className = match[1];
    const slot = match[2];
    const frameTag = match[0].match(/^<div\b[^>]*>/)?.[0] ?? '';
    if (/^s1[56]-(?:grid|brief)-21x9$/.test(slot)) {
      if (/\bfit-contain\b/.test(className)) {
        errors.push(`Slide ${slide.idx}: ${slot} uses fit-contain. Regenerated S15/S16 21:9 images should fill the slot with .frame-img.r-21x9.`);
      }
      if (!/\br-21x9\b/.test(className)) {
        errors.push(`Slide ${slide.idx}: ${slot} must use .frame-img.r-21x9 so the image slot controls the visible size.`);
      }
      if (/height\s*:\s*\d+(?:\.\d+)?vh/i.test(frameTag)) {
        errors.push(`Slide ${slide.idx}: ${slot} frame has a fixed vh height. Use aspect-ratio .r-21x9 instead.`);
      }
    }
  });
});

if (warnings.length) {
  console.warn('Warnings:');
  for (const warning of warnings) console.warn(`- ${warning}`);
}

if (errors.length) {
  console.error('Deck validation failed:');
  for (const error of errors) console.error(`- ${error}`);
  process.exit(1);
}

console.log(`Deck validation passed: ${slides.length} slide(s).`);

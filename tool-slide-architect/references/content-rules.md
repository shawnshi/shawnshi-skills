# Content & Style Rules

Guidelines for slide deck content quality and style consistency.

## Content Rules

### 1. Respect Reader Attention
- Each slide should communicate ONE main idea
- Remove redundant information
- Prioritize clarity over comprehensiveness

### 2. Data Traceability
- Every actual statistic must include source, source date, and applicable scope
- Cite sources directly on slides with data
- If evidence is unavailable, keep the item as a clearly marked input gap during drafting; do not invent a number to make the claim look specific

### 3. Self-Contained Prompts
- Every detail must be in the image prompt
- No external references (e.g., "like slide 2")
- Include all colors, layouts, and content explicitly

### 4. No Placeholders
- Every element must be fully specified
- No "[insert data here]" or "TBD"
- All text content finalized before generation

## Style Rules

### 1. Accurate Headlines
Decision slides often benefit from a conclusion headline. Technical specifications, data dictionaries, test reports, and regulatory pages may use precise descriptive headlines.

The examples below use variables and are not business facts:

| Generic | Evidence-backed alternative |
|-----|------|
| "Key Statistics" | "Usage changed from `[BASELINE]` to `[CURRENT]` during `[PERIOD]`" |
| "Our Solution" | "The proposed scope consolidates `[VERIFIED_SYSTEM_COUNT]` systems" |
| "Benefits" | "Measured weekly time changed by `[VERIFIED_HOURS]` hours" |

### 2. Avoid Abstract Clichés
Review these terms and replace them when they hide the actual mechanism:
- "Dive into", "explore", "journey", "赋能", "抓手", "降维打击"
- "Let's look at", "let me show you"
- "Exciting", "amazing", "revolutionary"

Healthcare terminology should be used only when it is accurate for the source material. A keyword scan is a writing prompt, not a release gate.

### 3. Meaningful Back Cover
Not just "Thank you" or "Questions?"

Include one of:
- Clear call-to-action
- Memorable key takeaway
- Thought-provoking closing statement
- Contact information with purpose

### 4. Consistent Visual Language
Throughout the deck:
- Same icon style
- Same color usage patterns
- Same layout grid system
- Same typography hierarchy

## Slide Structure

| Position | Type | Purpose |
|----------|------|---------|
| 1 | Cover | Title, visual hook, topic introduction |
| 2 to N-1 | Content | Key points, data, explanations |
| N | Back Cover | Summary, call-to-action, memorable close |

## Key Specifications

| Specification | Value |
|---------------|-------|
| Aspect Ratio | Use the requested format; default to 16:9 only when unspecified |
| Slide Count | Dynamic based on content |
| Required Slides | Cover + Back Cover minimum |
| Footers | Project-dependent; data citations must remain visible |
| Language Priority | `--lang` → source language → ask user |
| Tone | Direct, confident (avoid AI phrases) |

## Style Quick Reference

| Style | Visual Summary |
|-------|----------------|
| `sketch-notes` | Hand-drawn, warm off-white, conceptual icons |
| `blueprint` | Technical schematics, grid texture, blue tones |
| `bold-editorial` | High contrast, dark backgrounds, magazine impact |
| `vector-illustration` | Flat vector, black outlines, retro colors |
| `minimal` | Maximum whitespace, single accent, zen-like |
| `storytelling` | Full-bleed imagery, cinematic, emotional |
| `warm` | Soft gradients, rounded shapes, wellness palette |
| `notion` | Dashboard aesthetic, clean data viz, SaaS-inspired |
| `corporate` | Navy/gold, structured layouts, business polish |
| `playful` | Vibrant coral/teal/yellow, dynamic, energetic |

Full style specifications: `references/styles/<style>.md`

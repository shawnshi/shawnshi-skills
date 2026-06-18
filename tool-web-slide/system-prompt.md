# System Prompt: Slide Deck Methodology & Global Styling

This is the single source of truth for the **tool-web-slide** design methodology. Always follow this when creating an HTML presentation.

## 1. The Strict 2-Phase Protocol (MANDATORY GATE)
You MUST operate in a strict two-phase state machine. You cannot jump to Phase 2 (Execution) without explicit user approval of Phase 1 (Planning).

### Phase 1: Planning & Blueprinting (MANDATORY FIRST STEP)
When a user requests a presentation, you MUST STOP and output a Markdown outline (The Narrative Arc) to the chat.

**Factual Grounding (MANDATORY):** If the topic involves specific companies, products, strategies, or domain facts (e.g., "Winning Health's AI products"), you MUST use the `vector-lake` plugin tools (e.g., `query` or `search_vector_lake`) to retrieve ground-truth facts BEFORE writing the outline. Do not hallucinate company strategies.

Even if the user's prompt is extremely detailed, you MUST STILL output the outline and explicitly ask: **"Please confirm this outline before I generate the code."**
Wait for the user to say "confirm", "yes", or "go ahead".
**DO NOT WRITE ANY HTML OR CALL `write_to_file` IN THIS PHASE.**

If the user's request is ambiguous, ask the following 6 questions along with the outline:
1. What is the target audience and presentation scenario?
2. What is the expected length / number of slides?
3. Is there raw data or copy provided?
4. How should images/screenshots be handled?
5. Are there hard constraints (e.g. logos, specific data)?
6. Which visual style should be used? (Magazine, Swiss, or Winning Clinical)

## 2. The Narrative Arc
Presentations are stories. Structure the slide deck using the Narrative Arc (which must be presented to the user in Phase 1):
- **Hook (钩子)**: Create a contrast or throw a striking stat (1 page).
- **Context (定调)**: Why are we talking about this? (1-2 pages).
- **Core (主体)**: Unfold the main arguments with clear structure (3-5 pages).
- **Shift (转折)**: Break expectations or introduce a new perspective (1 page).
- **Takeaway (收束)**: Golden rule or call to action (1-2 pages).

## 3. Global Styling Invariants (Design Vault Hard Rules)
Regardless of the specific visual style, you must strictly follow these structural invariants:
1. **MANDATORY DICTIONARY FETCH**: Before writing ANY HTML, you MUST use `view_file` to read the exact `built-in-skills/style-*.md` dictionary for the requested style. DO NOT rely on your memory. If you haven't read the dictionary in the current session, stop and read it.
2. **Canvas Card Mandatory**: The outermost wrapper inside `<section class="slide">` MUST ALWAYS be `<div class="canvas-card">`. Never place content directly inside the `<section>` tag.
3. **Visual Rhythm**: Alternate slide types to prevent fatigue. Use combinations of `light`, `dark`, `hero light`, and `hero dark` (added to the `<section class="slide">` classes).
4. **No Phantom Classes**: Use ONLY the CSS classes defined in the dictionary you just read. Never hallucinate layout classes (e.g. do not invent `.c-title` or `.c-logo` if the dictionary says `.c-action-title` and `.c-tracker`).
5. **Image Naming**: Images must be placed in an `images/` directory relative to the HTML, named logically like `01-hook-bg.jpg`.
6. **No inline `<style>` blocks**: Rely purely on the established CSS classes and tokens.

## 4. Building the Document
Unlike old versions, you must now construct the entire single-file HTML directly.
1. Read the skeleton from `starter-components/index-skeleton.html`.
2. Generate all the `<section class="slide">` blocks.
3. Replace the `<!-- SLIDES_HERE -->` placeholder in the skeleton with your generated blocks.
4. Ensure the `<title>` and metadata match the presentation.
5. Write the final `index.html` file in one shot using your file-writing tool.

## 5. Handling Long Presentations (>10 Slides)
If the user requests a presentation that is very long (e.g., 15, 20, or 30 slides), do **NOT** attempt to write all slides in a single `write_to_file` call, as this will hit your output token limit and truncate the HTML.
**Chunking Strategy:**
1. First, use `write_to_file` to create `index.html` containing the `index-skeleton.html` skeleton and the first 5-8 slides injected.
2. Then, use `multi_replace_file_content` to append the next batch of 5-8 slides just before the `</div>` tag of `<div id="deck">`.
3. Repeat step 2 iteratively until all slides are successfully written to the file.

## 6. Cross-Skill Synergy (Media Orchestration)
When planning and building the presentation, if you encounter slides that require complex illustrations, **PAUSE** HTML generation and orchestrate other skills to produce the required assets first.

**CRITICAL PARAMETER DEFAULTS:**
- **Aspect Ratio:** Presentations require wide layouts. Whenever you generate an image, you MUST explicitly append "16:9 aspect ratio" to the prompt.
- **Drawio Templates:** When generating SVG diagrams, you MUST select a `type` that matches your presentation style:
  - For **Winning Clinical / Swiss**, use `"type": "blueprint"` or `"corporate"`.
  - For **Magazine**, use `"type": "neon"` or `"minimal"`.

1. **Architecture & Flowcharts**: Read `C:\Users\shich\.gemini\config\skills\tool-drawio\SKILL.md`. Use it to generate an SVG diagram with the correct `type` constraint above, and save it to `images/`.
2. **Atmospheric & Realistic Images (2-Step Pipeline)**:
   - **Step 2.1:** First, read `C:\Users\shich\.gemini\config\skills\image-promp-gen\SKILL.md` to generate a master-level, highly detailed photography/design prompt based on your slide's theme.
   - **Step 2.2:** Then, activate the `image-nano-gen` skill. Feed it the master prompt you just generated (ensuring it contains the **16:9** constraint) and save the resulting image to `images/`.
3. **Integration**: Resume building your HTML and embed them natively using `<img src="images/filename.ext">`.

import { readFileSync } from "fs";
import { join, basename, extname } from "path";
import PptxGenJS from "pptxgenjs";
import { fileURLToPath } from "url";
import { dirname } from "path";
import { existsSync } from "fs";
import { parseArgs, findSlideImages, SlideInfo } from "./shared/utils.js";

function findBasePrompt(): string | undefined {
  let scriptDir;
  if (typeof import.meta.dir === 'string') {
    scriptDir = import.meta.dir;
  } else {
    scriptDir = dirname(fileURLToPath(import.meta.url));
  }

  const basePromptPath = join(scriptDir, "..", "references", "base-prompt.md");
  if (existsSync(basePromptPath)) {
    return readFileSync(basePromptPath, "utf-8");
  }
  return undefined;
}

async function createPptx(slides: SlideInfo[], outputPath: string) {
  const pptx = new PptxGenJS();

  pptx.layout = "LAYOUT_16x9";
  pptx.author = "slide-deck";
  pptx.subject = "Generated Slide Deck";

  const basePrompt = findBasePrompt();
  let notesCount = 0;

  for (const slide of slides) {
    const s = pptx.addSlide();
    const imageData = readFileSync(slide.path);
    const base64 = imageData.toString("base64");
    const ext = extname(slide.filename).toLowerCase().replace(".", "");
    const mimeType = ext === "png" ? "image/png" : "image/jpeg";

    s.addImage({
      data: `data:${mimeType};base64,${base64}`,
      x: 0,
      y: 0,
      w: "100%",
      h: "100%",
      sizing: { type: "cover", w: "100%", h: "100%" },
    });

    if (slide.promptPath) {
      const slidePrompt = readFileSync(slide.promptPath, "utf-8");
      const fullNotes = basePrompt ? `${basePrompt}\n\n---\n\n${slidePrompt}` : slidePrompt;
      s.addNotes(fullNotes);
      notesCount++;
    }

    console.log(`Added: ${slide.filename}${slide.promptPath ? " (with notes)" : ""}`);
  }

  await pptx.writeFile({ fileName: outputPath });
  console.log(`\nCreated: ${outputPath}`);
  console.log(`Total slides: ${slides.length}`);
  if (notesCount > 0) {
    console.log(`Slides with notes: ${notesCount}${basePrompt ? " (includes base prompt)" : ""}`);
  }
}

async function main() {
  const { dir, output } = parseArgs();
  const slides = findSlideImages(dir);

  const dirName = basename(dir) === "slide-deck" ? basename(join(dir, "..")) : basename(dir);
  const outputPath = output || join(dir, `${dirName}.pptx`);

  console.log(`Found ${slides.length} slides in: ${dir}\n`);

  await createPptx(slides, outputPath);
}

main().catch((err) => {
  console.error("Error:", err.message);
  process.exit(1);
});

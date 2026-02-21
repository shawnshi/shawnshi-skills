import { readFileSync, writeFileSync } from "fs";
import { join, basename } from "path";
import { PDFDocument } from "pdf-lib";
import { parseArgs, findSlideImages, SlideInfo } from "./shared/utils.js";

async function createPdf(slides: SlideInfo[], outputPath: string) {
  const pdfDoc = await PDFDocument.create();
  pdfDoc.setAuthor("slide-deck");
  pdfDoc.setSubject("Generated Slide Deck");

  for (const slide of slides) {
    const imageData = readFileSync(slide.path);
    const ext = slide.filename.toLowerCase();
    const image = ext.endsWith(".png")
      ? await pdfDoc.embedPng(imageData)
      : await pdfDoc.embedJpg(imageData);

    const { width, height } = image;
    const page = pdfDoc.addPage([width, height]);

    page.drawImage(image, {
      x: 0,
      y: 0,
      width,
      height,
    });

    console.log(`Added: ${slide.filename}${slide.promptPath ? " (prompt available)" : ""}`);
  }

  const pdfBytes = await pdfDoc.save();
  writeFileSync(outputPath, pdfBytes);

  console.log(`\nCreated: ${outputPath}`);
  console.log(`Total pages: ${slides.length}`);
}

async function main() {
  const { dir, output } = parseArgs();
  const slides = findSlideImages(dir);

  const dirName = basename(dir) === "slide-deck" ? basename(join(dir, "..")) : basename(dir);
  const outputPath = output || join(dir, `${dirName}.pdf`);

  console.log(`Found ${slides.length} slides in: ${dir}\n`);

  await createPdf(slides, outputPath);
}

main().catch((err) => {
  console.error("Error details:", err);
  if (err instanceof Error) {
    console.error("Stack:", err.stack);
  }
  process.exit(1);
});

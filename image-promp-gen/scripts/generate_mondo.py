#!/usr/bin/env python3
"""
Mondo Style Design Prompt Generator
Features: 20+ artist styles, aspect ratio support.
"""

import os
import sys
import argparse

# 30+ Design Styles: Poster Artists + Book Cover + Album Cover + Social Media
ARTIST_STYLES = {
    "auto": "let AI choose best style",
    # === Poster Artists (20) ===
    "saul-bass": "Saul Bass minimalist geometric abstraction, 2-3 colors, visual metaphor",
    "olly-moss": "Olly Moss ultra-minimal negative space, clever hidden imagery, 2 colors",
    "tyler-stout": "Tyler Stout maximalist character collage, intricate line work, organized chaos",
    "martin-ansin": "Martin Ansin Art Deco elegance, refined vintage palette, sophisticated",
    "toulouse-lautrec": "Toulouse-Lautrec flat color blocks, Japanese influence, bold silhouettes",
    "alphonse-mucha": "Alphonse Mucha Art Nouveau flowing curves, ornate floral, decorative borders",
    "jules-cheret": "Jules Chéret Belle Époque bright joyful colors, dynamic feminine figures",
    "cassandre": "Cassandre modernist geometry, Cubist planes, dramatic perspective, Art Deco",
    "milton-glaser": "Milton Glaser psychedelic pop art, innovative typography, vibrant colors",
    "drew-struzan": "Drew Struzan painted realism, epic cinematic, warm nostalgic glow",
    "kilian-eng": "Kilian Eng geometric futurism, precise technical lines, cool sci-fi palette",
    "laurent-durieux": "Laurent Durieux visual puns, hidden imagery, mysterious atmospheric",
    "jay-ryan": "Jay Ryan folksy handmade, single focal image, warm textured simple",
    "dan-mccarthy": "Dan McCarthy ultra-flat geometric abstraction, 2-3 solid colors, no gradients",
    "jock": "Jock gritty expressive brushwork, dynamic action, high contrast, raw energy",
    "shepard-fairey": "Shepard Fairey propaganda style, red black cream, halftone, political",
    "steinlen": "Steinlen social realist, expressive lines, cat motifs, high contrast",
    "josef-muller-brockmann": "Josef Müller-Brockmann Swiss grid, Helvetica, mathematical precision",
    "paul-rand": "Paul Rand playful geometry, clever visual puns, witty intelligent",
    "paula-scher": "Paula Scher typographic maximalism, layered text, vibrant expressive letters",
    # === Book Cover Designers (6) ===
    "chip-kidd": "Chip Kidd conceptual book cover, single symbolic object, bold typography, photographic metaphor, witty visual pun, Random House literary aesthetic",
    "peter-mendelsund": "Peter Mendelsund abstract literary cover, deconstructed typography, minimal symbolic elements, intellectual negative space, Knopf literary elegance",
    "coralie-bickford-smith": "Coralie Bickford-Smith Penguin Clothbound Classics, repeating decorative patterns, Art Nouveau foil stamping, jewel-tone palette, ornamental borders, fabric texture",
    "david-pearson": "David Pearson Penguin Great Ideas, bold typographic-only cover, text as visual element, minimal color, intellectual and clean, type-driven design",
    "wang-zhi-hong": "Wang Zhi-Hong East Asian book design, restrained elegant typography, confident negative space, subtle texture, balanced asymmetry, literary sophistication",
    "jan-tschichold": "Jan Tschichold modernist Penguin typography, Swiss precision grid, clean serif fonts, understated elegance, timeless typographic hierarchy",
    # === Album Cover Designers (3) ===
    "reid-miles": "Reid Miles Blue Note Records, bold asymmetric typography, high contrast black and single accent color, jazz photography silhouette, dramatic negative space, vintage vinyl",
    "david-stone-martin": "David Stone Martin Verve Records, single gestural ink brushstroke, minimalist line drawing on cream, fluid calligraphic lines, maximum negative space, improvisational energy",
    "peter-saville": "Peter Saville Factory Records extreme minimalism, single abstract form in vast empty space, monochromatic, no text on cover, conceptual and mysterious, intellectual restraint",
    # === Social Media / Chinese Aesthetic Styles (4) ===
    "wenyi": "文艺风 literary artistic style, soft muted tones, generous white space, delicate serif typography, watercolor texture, poetic atmosphere, refined and contemplative, editorial book review aesthetic",       
    "guochao": "国潮风 Chinese contemporary trend, traditional Chinese motifs reimagined modern, bold red and gold palette, ink wash meets graphic design, cultural symbols with street art energy, 新中式",
    "rixi": "日系 Japanese aesthetic, warm film grain, soft natural light, pastel muted palette, clean minimal layout, hand-drawn accents, cozy atmosphere, wabi-sabi imperfection, zakka lifestyle",
    "hanxi": "韩系 Korean aesthetic, clean bright pastel, soft gradient backgrounds, modern sans-serif typography, dreamy ethereal quality, sophisticated minimal, Instagram-worthy composition",
    # === Generic Styles ===
    "minimal": "minimalist, centered single focal point, 2-3 color palette, clean simple",
    "atmospheric": "single strong focal element with atmospheric background, 3-4 colors",
    "negative-space": "figure-ground inversion, negative space reveals hidden element, 2 colors"
}

def get_format_description(aspect_ratio):
    """Get format description text matching the aspect ratio"""
    ratio_descriptions = {
        "9:16": "vertical 9:16 portrait format",
        "16:9": "horizontal 16:9 landscape format, wide cinematic composition",
        "21:9": "ultra-wide 21:9 panoramic banner format, horizontal landscape",
        "3:4": "vertical 3:4 portrait format",
        "4:3": "horizontal 4:3 landscape format",
        "1:1": "square 1:1 format",
    }
    return ratio_descriptions.get(aspect_ratio, f"{aspect_ratio} format")

def generate_prompt(subject, design_type, style="auto", color_hint="", aspect_ratio="9:16"):
    """
    Generate Mondo-style prompt from subject.
    When called by Claude, pass a rich pre-crafted prompt as subject for best results.

    Args:
        subject: The subject matter (or a fully-crafted Mondo prompt from Claude)
        design_type: Type of design ("movie", "book", "album", "event")
        style: Visual style (artist name or preset)
        color_hint: Optional color preferences from user
        aspect_ratio: Aspect ratio for the image

    Returns:
        Generated prompt string
    """
    format_desc = get_format_description(aspect_ratio)

    # Standard template path
    base_elements = "Mondo poster style, screen print aesthetic, limited edition poster art"

    # Get style modifier
    style_desc = ARTIST_STYLES.get(style, ARTIST_STYLES['minimal'])

    # Build prompt based on type
    if design_type == "movie":
        prompt = f"{subject} in {base_elements}, {style_desc}, {format_desc}, clean focused composition, vintage poster aesthetic"
    elif design_type == "book":
        prompt = f"{subject} book cover in {base_elements}, {style_desc}, {format_desc}, clean typography, literary design"
    elif design_type == "album":
        prompt = f"{subject} album cover in {base_elements}, {style_desc}, square 1:1 format, vintage vinyl aesthetic"
    elif design_type == "event":
        prompt = f"{subject} event poster in {base_elements}, {style_desc}, {format_desc}, bold memorable design"
    else:
        prompt = f"{subject} in {base_elements}, {style_desc}, vintage print aesthetic"

    # Add color hint if provided
    if color_hint:
        prompt += f", color palette: {color_hint}"

    return prompt


def main():
    parser = argparse.ArgumentParser(
        description='Mondo Style Design Prompt Generator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
🎨 20 Artist Styles Available:
  Classic: saul-bass, toulouse-lautrec, alphonse-mucha, jules-cheret, cassandre
  Modern: olly-moss, tyler-stout, martin-ansin, drew-struzan, milton-glaser
  Contemporary: kilian-eng, dan-mccarthy, jock, shepard-fairey, jay-ryan

Examples:
  # Basic generation
  python3 generate_mondo.py "Blade Runner" movie

  # Specific artist style
  python3 generate_mondo.py "Akira" movie --style kilian-eng
  
  # With color preferences
  python3 generate_mondo.py "Jazz Festival" event --style jules-cheret --colors "vibrant yellow, deep blue, red"
        """
    )

    parser.add_argument('subject', help='Subject matter (e.g., "Blade Runner", "1984 novel")')
    parser.add_argument('type', choices=['movie', 'book', 'album', 'event'],
                       help='Type of design to create')
    parser.add_argument('--style', choices=list(ARTIST_STYLES.keys()), default='auto',
                       help='Artist style (default: auto)')
    parser.add_argument('--colors', type=str, default='',
                       help='Color preferences (e.g., "orange, teal, black")')
    parser.add_argument('--aspect-ratio', '--ratio', dest='aspect_ratio', default='9:16',
                       help='Aspect ratio (default: 9:16)')
    parser.add_argument('--list-styles', action='store_true',
                       help='List all available artist styles')

    args = parser.parse_args()

    # List styles
    if args.list_styles:
        print("\n🎨 20 Greatest Poster Artists - Available Styles:\n")
        for style, desc in ARTIST_STYLES.items():
            print(f"  {style:25} → {desc}")
        print()
        return

    # Single generation mode
    prompt = generate_prompt(args.subject, args.type, args.style, args.colors, args.aspect_ratio)

    print(f"\n{'='*80}")
    print("🎨 MONDO POSTER PROMPT")
    print(f"{ '='*80}")
    print(f"{prompt}")
    print(f"{ '='*80}\n")
    print("✓ Prompt generated successfully.")
    print("\n[NEXT_STEP]: Would you like to call 'image-nano-gen' to generate the image with this prompt?")

if __name__ == '__main__':
    main()

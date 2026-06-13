import sys
import os

def build_deck(template_path, slides_path, output_path):
    with open(template_path, 'r', encoding='utf-8') as f:
        template_html = f.read()

    with open(slides_path, 'r', encoding='utf-8') as f:
        slides_html = f.read()

    deck_start_idx = template_html.find('<div id="deck">')
    if deck_start_idx == -1:
        print("Error: Could not find <div id='deck'> in template.")
        sys.exit(1)

    # To preserve the exact DOM structure, we replace <!-- SLIDES_HERE -->
    # If the anchor is missing, we inject right after <div id="deck">
    anchor = "<!-- SLIDES_HERE -->"
    anchor_idx = template_html.find(anchor)

    if anchor_idx != -1:
        new_html = template_html[:anchor_idx] + slides_html + template_html[anchor_idx + len(anchor):]
    else:
        # Fallback: inject into <div id="deck">
        insertion_point = deck_start_idx + len('<div id="deck">')
        new_html = template_html[:insertion_point] + '\n' + slides_html + '\n' + template_html[insertion_point:]

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(new_html)
    
    print(f"Success: Deck built and safely injected into {output_path}")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python build_deck.py <template_path> <slides_html_path> <output_path>")
        sys.exit(1)
    
    build_deck(sys.argv[1], sys.argv[2], sys.argv[3])

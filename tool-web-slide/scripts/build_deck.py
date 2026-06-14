import sys
import os
import shutil

def copy_assets(template_path, output_path):
    template_dir = os.path.dirname(os.path.abspath(template_path))
    output_dir = os.path.dirname(os.path.abspath(output_path))
    
    # tool-web-slide/design-vault/<style>/template.html -> tool-web-slide/assets
    root_dir = os.path.abspath(os.path.join(template_dir, "..", ".."))
    assets_src = os.path.join(root_dir, "assets")
    assets_dest = os.path.join(output_dir, "assets")
    
    if os.path.exists(assets_src):
        os.makedirs(assets_dest, exist_ok=True)
        shutil.copytree(assets_src, assets_dest, dirs_exist_ok=True)

def build_deck(template_path, slides_path, output_path):
    with open(template_path, 'r', encoding='utf-8') as f:
        template_html = f.read()

    with open(slides_path, 'r', encoding='utf-8') as f:
        slides_html = f.read()

    placeholder_start = "<!-- INJECT_DECK_CONTENT_START -->"
    placeholder_end = "<!-- INJECT_DECK_CONTENT_END -->"
    
    start_idx = template_html.find(placeholder_start)
    end_idx = template_html.find(placeholder_end)
    
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        # We found the placeholders! Replace everything between them.
        new_html = template_html[:start_idx + len(placeholder_start)] + '\n' + slides_html + '\n  ' + template_html[end_idx:]
    else:
        # Fallback to old heuristic
        deck_start_idx = template_html.find('<div id="deck">')
        if deck_start_idx == -1:
            print("Error: Could not find <div id='deck'> in template.")
            sys.exit(1)
    
        deck_end_search_anchor = template_html.find('<div id="nav">', deck_start_idx)
        if deck_end_search_anchor != -1:
            deck_end_idx = template_html.rfind('</div>', deck_start_idx, deck_end_search_anchor)
        else:
            deck_end_idx = template_html.find('</div>', deck_start_idx)
    
        if deck_end_idx == -1:
            print("Error: Could not find closing </div> for deck.")
            sys.exit(1)
    
        insertion_point_start = deck_start_idx + len('<div id="deck">')
        new_html = template_html[:insertion_point_start] + '\n' + slides_html + '\n  ' + template_html[deck_end_idx:]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(new_html)
    
    copy_assets(template_path, output_path)
    print(f"Success: Deck built, assets cloned, and safely injected into {output_path}")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python build_deck.py <template_path> <slides_html_path> <output_path>")
        sys.exit(1)
    
    build_deck(sys.argv[1], sys.argv[2], sys.argv[3])

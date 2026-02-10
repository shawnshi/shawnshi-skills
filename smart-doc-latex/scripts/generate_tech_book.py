import re
import sys
import os

def generate_tech_book(body_path, template_path, output_path, title="My Book", author="Author", date="\\today"):
    # 1. Read Body
    with open(body_path, 'r', encoding='utf-8') as f:
        body_content = f.read()

    # 2. Clean Body (Remove fake TOC)
    # Strategy: Split by \part, ignore the one containing "目录", keep the rest.
    parts = re.split(r'(\\part{)', body_content) # Split but keep delimiter
    
    clean_body = ""
    # parts[0] is preamble junk
    # parts[1] is \"part{"
    # parts[2] is "Title} content..."
    
    if len(parts) < 2:
        # No parts found, maybe just chapters?
        clean_body = body_content
    else:
        # Reconstruct
        # Loop through chunks of 2 (delimiter + content)
        # Start from index 1
        i = 1
        clean_body += parts[0] # Keep initial text if any (though usually junk from pandoc)
        
        while i < len(parts):
            delimiter = parts[i]     # \part{
            content_chunk = parts[i+1] if i+1 < len(parts) else ""
            
            # Check content_chunk for "目录" in the title section (first few chars)
            # The title ends at the first closing brace `}`
            # But we must be careful of nested braces.
            # Simple heuristic: Look at first 100 chars.
            title_candidate = content_chunk[:100]
            
            if "目录" in title_candidate or "Catalog" in title_candidate:
                print(f"Skipping TOC Part found in: {title_candidate[:30]}...")
            else:
                clean_body += delimiter + content_chunk
            
            i += 2

    # 3. Read Template
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()

    # 4. Inject
    # Replace $title$, $author$, $date$, $body$
    # We use simple string replace, assuming keys are unique enough
    
    final_latex = template.replace('$title$', title)
    final_latex = final_latex.replace('$author$', author)
    final_latex = final_latex.replace('$date$', date)
    final_latex = final_latex.replace('$body$', clean_body)

    # 5. Save
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(final_latex)
    
    print(f"Successfully generated {output_path}")

if __name__ == '__main__':
    if len(sys.argv) < 4:
        print("Usage: python generate_tech_book.py <body.tex> <output.tex> <title> [author]")
        sys.exit(1)
        
    body_file = sys.argv[1]
    output_file = sys.argv[2]
    doc_title = sys.argv[3]
    doc_author = sys.argv[4] if len(sys.argv) > 4 else "Author"
    
    # Hardcoded template path relative to script location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_file = os.path.join(script_dir, "../templates/tech_book.tex")
    
    generate_tech_book(body_file, template_file, output_file, doc_title, doc_author)

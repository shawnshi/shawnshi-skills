"""
<!-- Standard Header -->
@Input: Workspace Directory (containing 00_*.md, 01_*.md, ...)
@Output: Merged Archive Markdown File
@Pos: Phase 3 (Merge Phase)
@Maintenance Protocol: File prefix logic (00, 01, 99) must be preserved.
"""
import os
import sys
import glob

def merge_roundtable_fragments(workspace_path, output_file_path):
    """
    Physically merges all .md fragments in a workspace into a single file.
    Orders files alphabetically by name (00_init.md, 01_round1.md, ..., 99_summary.md).
    """
    if not os.path.isdir(workspace_path):
        print(f"Error: Workspace {workspace_path} does not exist.")
        sys.exit(1)

    # Gather all markdown files in the workspace
    pattern = os.path.join(workspace_path, "*.md")
    fragments = sorted(glob.glob(pattern))

    if not fragments:
        print(f"Error: No .md fragments found in {workspace_path}.")
        sys.exit(1)

    print(f"Merging {len(fragments)} fragments from: {workspace_path}")
    
    try:
        with open(output_file_path, 'w', encoding='utf-8') as outfile:
            for fragment_path in fragments:
                fname = os.path.basename(fragment_path)
                print(f" - Integrating: {fname}")
                
                with open(fragment_path, 'r', encoding='utf-8') as infile:
                    content = infile.read()
                    outfile.write(content)
                    # Add separator unless it's the last one
                    if fragment_path != fragments[-1]:
                        outfile.write("\n\n---\n\n")
        
        print(f"Archive successfully created at: {output_file_path}")
        # Final safety check
        if os.path.getsize(output_file_path) == 0:
             raise Exception("Resulting file is empty. Merge failed.")
             
    except Exception as e:
        print(f"Merge operation failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python merger.py <workspace_path> <output_file_path>")
        sys.exit(1)
    
    workspace = sys.argv[1]
    output = sys.argv[2]
    merge_roundtable_fragments(workspace, output)

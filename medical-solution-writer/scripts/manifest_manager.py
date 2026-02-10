import sys
import os
import json

def merge_files(manifest_path, output_path):
    if not os.path.exists(manifest_path):
        print(f"Error: Manifest {manifest_path} not found.")
        return

    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    temp_output = output_path + ".tmp"
    try:
        with open(temp_output, 'w', encoding='utf-8') as outfile:
            for file_path in manifest.get('files', []):
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as infile:
                        outfile.write(infile.read())
                        outfile.write("

---

") # Visual separator
                else:
                    print(f"Warning: File {file_path} in manifest not found.")
        
        # Security check: Limit to 10MB for summary documents
        if os.path.getsize(temp_output) > 10 * 1024 * 1024:
            raise Exception("Security Error: Output file exceeds 10MB safety limit.")
        
        os.replace(temp_output, output_path)
        print(f"Successfully merged into {output_path}")
    except Exception as e:
        if os.path.exists(temp_output):
            os.remove(temp_output)
        print(f"Merge failed: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python manifest_manager.py <manifest_json> <output_md>")
    else:
        merge_files(sys.argv[1], sys.argv[2])

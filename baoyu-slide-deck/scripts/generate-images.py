import os
import glob
import json
import base64
import requests
import time
import argparse
from pathlib import Path

# Load environment variables
def load_env(env_path):
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    env_vars[key] = value
    return env_vars

# Determine script directory to find .env
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
ENV_PATH = os.path.join(SKILL_DIR, ".env")
ENV_VARS = load_env(ENV_PATH)

API_KEY = os.environ.get("GOOGLE_API_KEY") or ENV_VARS.get("GOOGLE_API_KEY")
MODEL_NAME = os.environ.get("NANOBANANA_MODEL") or ENV_VARS.get("NANOBANANA_MODEL") or "models/gemini-3-pro-image-preview"
if not MODEL_NAME.startswith("models/"):
    MODEL_NAME = f"models/{MODEL_NAME}"
    
BASE_URL = os.environ.get("GOOGLE_BASE_URL") or ENV_VARS.get("GOOGLE_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_RESOLUTION = "2K (2560x1440)"

def generate_image(prompt_text, filename, output_dir):
    # Ensure resolution is emphasized in the prompt
    if "Resolution:" not in prompt_text:
        prompt_text = f"{prompt_text}\n\n## RESOLUTION\n- Resolution: {DEFAULT_RESOLUTION}"
    
    url = f"{BASE_URL}/{MODEL_NAME}:generateContent?key={API_KEY}"
    
    headers = {
        "Content-Type": "application/json"
    }
    
    # Payload for gemini-3-pro-image-preview (generateContent)
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt_text}
                ]
            }
        ],
        "generationConfig": {
            "imageConfig": {
                "aspectRatio": "16:9",
                "imageSize": "2K"
            }
        }
    }
    
    print(f"Generating {filename} with {MODEL_NAME}...")
    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            print(f"Error {response.status_code}: {response.text}")
            return False
            
        result = response.json()
        
        try:
            candidates = result.get("candidates", [])
            if not candidates:
                print("No candidates returned.")
                return False
                
            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                if "inlineData" in part:
                    mime_type = part["inlineData"].get("mimeType")
                    b64_data = part["inlineData"].get("data")
                    if b64_data:
                        # Determine extension from mime_type
                        ext = ".png"
                        if mime_type == "image/jpeg" or mime_type == "image/jpg":
                            ext = ".jpg"
                        elif mime_type == "image/webp":
                            ext = ".webp"
                        
                        # Replace .png in filename if different
                        actual_filename = filename
                        if not filename.lower().endswith(ext):
                            base = os.path.splitext(filename)[0]
                            actual_filename = f"{base}{ext}"

                        img_data = base64.b64decode(b64_data)
                        output_path = os.path.join(output_dir, actual_filename)
                        with open(output_path, "wb") as f:
                            f.write(img_data)
                        print(f"Saved to {output_path} (Type: {mime_type})")
                        return True
            
            print(f"No image data found in response. Response: {json.dumps(result, indent=2)}")
            return False

        except Exception as e:
            print(f"Error parsing response: {e}")
            return False
            
    except Exception as e:
        print(f"Exception: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Generate slide images from prompts.")
    parser.add_argument("dir", help="Slide deck directory containing prompts/ subdirectory")
    parser.add_argument("--regenerate", "-r", help="Regenerate specific slides (comma-separated indices)")
    args = parser.parse_args()

    slide_dir = args.dir
    prompts_dir = os.path.join(slide_dir, "prompts")
    
    if not os.path.exists(slide_dir):
        print(f"Error: Directory {slide_dir} does not exist.")
        return

    if not os.path.exists(prompts_dir):
        print(f"Error: Prompts directory {prompts_dir} does not exist.")
        return

    if not API_KEY:
        print("Error: GOOGLE_API_KEY not found in environment or .env file.")
        return

    prompt_files = sorted(glob.glob(os.path.join(prompts_dir, "*.md")))
    
    if not prompt_files:
        print(f"No prompt files found in {prompts_dir}")
        return

    print(f"Found {len(prompt_files)} prompt files.")

    # Determine which slides to process
    slides_to_process = []
    if args.regenerate:
        indices = [int(i.strip()) for i in args.regenerate.split(',')]
        for p_file in prompt_files:
            basename = os.path.basename(p_file)
            # Assume filename format: 01-slide-cover.md
            try:
                idx = int(basename.split('-')[0])
                if idx in indices:
                    slides_to_process.append(p_file)
            except ValueError:
                pass
    else:
        # Default: process all, skip existing
        for p_file in prompt_files:
            basename = os.path.basename(p_file)
            png_name = basename.replace(".md", ".png")
            output_path = os.path.join(slide_dir, png_name)
            
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                print(f"Skipping {png_name} (already exists)")
                continue
            slides_to_process.append(p_file)

    if not slides_to_process:
        print("No slides to generate.")
        return

    print(f"Generating images for {len(slides_to_process)} slides...")

    for p_file in slides_to_process:
        basename = os.path.basename(p_file)
        png_name = basename.replace(".md", ".png")
        
        with open(p_file, "r", encoding="utf-8") as f:
            prompt_content = f.read()
        
        # Retry logic
        max_retries = 2
        success = False
        for attempt in range(max_retries):
            success = generate_image(prompt_content, png_name, slide_dir)
            if success:
                break
            else:
                print(f"Retry {attempt+1}/{max_retries} for {png_name}...")
                time.sleep(2)
        
        if success:
            time.sleep(1) # Rate limiting
        else:
            print(f"Failed to generate {png_name} after retries.")

if __name__ == "__main__":
    main()

import mimetypes
import os
import sys
import argparse
from datetime import datetime
from google import genai
from google.genai import types

def save_binary_file(file_name, data):
    with open(file_name, "wb") as f:
        f.write(data)
    print(f"File saved to: {file_name}")

def generate():
    parser = argparse.ArgumentParser(description="Generate image using Gemini 3.1 Native 4K Image Pipeline.")
    parser.add_argument("prompt", type=str, help="The prompt for image generation")
    args = parser.parse_args()

    # Use NANOBANANA_API_KEY as primary, fallback to GEMINI_API_KEY per snippet
    api_key = os.environ.get("NANOBANANA_API_KEY") or os.environ.get("GEMINI_API_KEY")
    # Default to gemini-3.1-flash-image-preview per official snippet
    model_name = os.environ.get("NANOBANANA_MODEL") or "gemini-3.1-flash-image-preview"

    if not api_key:
        print("Error: API Key is not set in environment variables.", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # Inject resolution and quality instructions into prompt for models without native thinking_config support
    enhanced_prompt = f"{args.prompt} (Requirement: 4K resolution, ultra-detailed logical architecture, high thinking level conceptualization, professional industrial precision aesthetic)"

    # Google Search tool for enhanced factual image generation (minimal config)
    tools = [
        types.Tool(googleSearch=types.GoogleSearch(
            search_types=types.SearchTypes(
                web_search=types.WebSearch(),
            ),
        )),
    ]

    # Native 4K configuration (simplified for maximum compatibility)
    generate_content_config = types.GenerateContentConfig(
        image_config=types.ImageConfig(
            aspect_ratio="16:9", # Optimized for 4K widescreen
            image_size="4K",
        ),
        response_modalities=[
            "IMAGE",
        ],
        tools=tools,
    )

    # Calculate relative path to .gemini/nanobanana-output
    # scripts/generate.py -> scripts -> image-nano-gen -> skills -> .gemini -> nanobanana-output
    script_dir = os.path.dirname(os.path.abspath(__file__))
    gemini_root = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))
    output_dir = os.path.join(gemini_root, "nanobanana-output")
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_index = 0
    image_generated = False

    print(f"Executing Native 4K Pipeline with model: {model_name}...")
    print(f"Image Size: 4K (Thinking Config: Prompt-Injected)")

    try:
        for chunk in client.models.generate_content_stream(
            model=model_name,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=enhanced_prompt),
                    ],
                ),
            ],
            config=generate_content_config,
        ):
            if chunk.parts is None:
                continue
            
            if chunk.parts[0].inline_data and chunk.parts[0].inline_data.data:
                inline_data = chunk.parts[0].inline_data
                data_buffer = inline_data.data
                file_extension = mimetypes.guess_extension(inline_data.mime_type) or ".jpg"
                
                file_name = f"nano_{timestamp}_{file_index}{file_extension}"
                filepath = os.path.join(output_dir, file_name)
                
                save_binary_file(filepath, data_buffer)
                file_index += 1
                image_generated = True
            else:
                if chunk.text:
                    print(f"Model Thought: {chunk.text}", end="", flush=True)

        print("\nGeneration process finished.")
        if not image_generated:
            print("Warning: No image data was returned in the stream.", file=sys.stderr)

    except Exception as e:
        print(f"\nError during native 4K generation: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    generate()

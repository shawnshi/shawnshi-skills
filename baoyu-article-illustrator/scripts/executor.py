import os
import sys
import requests
import json
import base64
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def load_env(env_path):
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars

def list_capable_models(api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            models = res.json().get('models', [])
            return [m['name'] for m in models if 'predict' in m.get('supportedGenerationMethods', [])]
    except Exception as e:
        logging.error(f"Failed to list models: {e}")
    return []

def run_gen(model, prompt, api_key, output_path):
    url = f"https://generativelanguage.googleapis.com/v1beta/{model}:predict?key={api_key}"
    # 文章插图默认 16:9，已优化为 2K 分辨率
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1, 
            "aspectRatio": "16:9",
  "imageSize": "2K"
        }
    }
    try:
        res = requests.post(url, json=payload, timeout=90)
        if res.status_code == 200:
            preds = res.json().get('predictions', [])
            if preds and 'bytesBase64Encoded' in preds[0]:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, 'wb') as f:
                    f.write(base64.b64decode(preds[0]['bytesBase64Encoded']))
                return True
    except Exception as e:
        logging.warning(f"Model {model} failed: {e}")
    return False

def main():
    if len(sys.argv) < 3:
        print("Usage: python executor.py <prompt> <output_path>")
        sys.exit(1)

    prompt = sys.argv[1]
    output_path = sys.argv[2]
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_vars = load_env(os.path.join(base_dir, '.env'))
    api_key = env_vars.get('GOOGLE_API_KEY')
    
    if not api_key:
        logging.error("No GOOGLE_API_KEY found in .env")
        sys.exit(1)

    priority_list = [
'models/gemini-3-pro-image-preview',
        'models/imagen-4.0-generate-001',
        'models/imagen-3.0-generate-001'
    ]
    
    available = list_capable_models(api_key)
    to_try = [m for m in priority_list if m in available]
    to_try.extend([m for m in available if m not in to_try and ('image' in m or 'imagen' in m)])

    for model in to_try:
        logging.info(f"Generating article illustration with {model}...")
        if run_gen(model, prompt, api_key, output_path):
            logging.info(f"SUCCESS: {output_path}")
            sys.exit(0)
            
    sys.exit(1)

if __name__ == "__main__":
    main()

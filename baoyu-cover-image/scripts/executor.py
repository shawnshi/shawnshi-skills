import os
import sys
import requests
import json
import base64
import logging

# 配置日志
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
    """发现具备生成能力且当前可用的模型"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            models = res.json().get('models', [])
            return [m['name'] for m in models if 'predict' in m.get('supportedGenerationMethods', [])]
    except Exception as e:
        logging.error(f"Failed to list models: {e}")
    return []

def run_gen(model, prompt, api_key, output_path, aspect_ratio="16:9"):
    """执行单次生成尝试"""
    url = f"https://generativelanguage.googleapis.com/v1beta/{model}:predict?key={api_key}"
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": aspect_ratio,
            "outputMimeType": "image/png",
  "imageSize": "2K"
        }
    }
    try:
        res = requests.post(url, json=payload, timeout=60)
        if res.status_code == 200:
            preds = res.json().get('predictions', [])
            if preds and 'bytesBase64Encoded' in preds[0]:
                with open(output_path, 'wb') as f:
                    f.write(base64.b64decode(preds[0]['bytesBase64Encoded']))
                return True
    except Exception as e:
        logging.warning(f"Model {model} failed: {e}")
    return False

def main():
    if len(sys.argv) < 3:
        print("Usage: python executor.py <prompt> <output_path> [aspect_ratio]")
        sys.exit(1)

    prompt = sys.argv[1]
    output_path = sys.argv[2]
    aspect_ratio = sys.argv[3] if len(sys.argv) > 3 else "16:9"
    
    # 路径处理：支持跨平台
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_vars = load_env(os.path.join(base_dir, '.env'))
    api_key = env_vars.get('GOOGLE_API_KEY')
    
    if not api_key:
        logging.error("No GOOGLE_API_KEY found in skill .env file.")
        sys.exit(1)

    # 优先级模型列表 (模型自愈逻辑)
    priority_list = [
'models/gemini-3-pro-image-preview',
        'models/imagen-4.0-generate-001',
        'models/imagen-3.0-generate-001'
    ]
    
    available = list_capable_models(api_key)
    # 最终尝试顺序：优先匹配列表中的，再尝试其他可用的
    to_try = [m for m in priority_list if m in available]
    to_try.extend([m for m in available if m not in to_try and ('image' in m or 'imagen' in m)])

    if not to_try:
        logging.error("No image-capable models found for this API key.")
        sys.exit(1)

    for model in to_try:
        logging.info(f"Attempting generation with {model}...")
        if run_gen(model, prompt, api_key, output_path, aspect_ratio):
            logging.info(f"SUCCESS: Image saved to {output_path}")
            sys.exit(0)

    logging.error("All available models failed to generate image.")
    sys.exit(1)

if __name__ == "__main__":
    main()

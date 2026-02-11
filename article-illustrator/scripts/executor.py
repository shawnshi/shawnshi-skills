import os
import sys
import re
import requests
import logging
from datetime import datetime
from openai import OpenAI

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def load_env():
    """加载环境变量"""
    env_vars = {}
    search_paths = [
        os.path.join(os.path.dirname(__file__), '.env'),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'),
        r'C:\Users\shich\.gemini\.env'
    ]
    for path in search_paths:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()
    return env_vars

import base64

def download_image(content, target_path):
    """解析并下载图片 (支持 URL 和 Base64 Data URI)"""
    content = content.strip()
    
    # 1. 尝试匹配 Markdown 图片语法 ![...](...)
    match = re.search(r'\(([^)]+)\)', content)
    if match:
        link = match.group(1)
    else:
        link = content

    # 2. 处理 Base64 Data URI
    if link.startswith('data:image'):
        try:
            logging.info("Detected Base64 Data URI. Decoding...")
            # 格式通常是 data:image/jpeg;base64,.....
            header, encoded = link.split(',', 1)
            data = base64.b64decode(encoded)
            with open(target_path, 'wb') as f:
                f.write(data)
            return True
        except Exception as e:
            logging.error(f"Failed to decode Base64: {e}")
            return False

    # 3. 处理 HTTP URL
    link = link.strip().strip('"').strip("'").split(' ')[0]
    if link.startswith('http'):
        logging.info(f"Downloading image from: {link}")
        try:
            res = requests.get(link, timeout=60, verify=False)
            if res.status_code == 200:
                with open(target_path, 'wb') as f:
                    f.write(res.content)
                return True
            else:
                logging.error(f"HTTP Error: {res.status_code}")
        except Exception as e:
            logging.error(f"Download failed: {e}")
        return False

    logging.error(f"No valid image data found in content: {content[:100]}...")
    return False

def main():
    env_vars = load_env()
    if len(sys.argv) < 2:
        print("Usage: python executor.py <prompt> [filename] [aspect_ratio] [quality]")
        sys.exit(1)

    prompt = sys.argv[1]
    
    # 优先使用 .env 配置，否则使用硬编码默认值 (根据你的示例)
    api_key = env_vars.get('GEMINI_API_KEY') or env_vars.get('GOOGLE_API_KEY') or "sk-4471bdc76d4e420faa4c6c20dcc26566"
    base_url = env_vars.get('GOOGLE_GEMINI_BASE_URL', 'http://127.0.0.1:8964/v1')

    # 初始化 OpenAI 客户端
    client = OpenAI(
        base_url=base_url,
        api_key=api_key
    )

    # 参数处理
    filename = sys.argv[2] if len(sys.argv) > 2 else f"panda_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    aspect_ratio = sys.argv[3] if len(sys.argv) > 3 else "16:9"
    quality = sys.argv[4] if len(sys.argv) > 4 else "2K"

    # 映射 Size (OpenAI 协议通过 extra_body 传递)
    size_map = {
        "16:9": {"1K": "1280x720", "2K": "2560x1440", "4K": "3840x2160"},
        "1:1": {"1K": "1024x1024", "2K": "2048x2048", "4K": "4096x4096"},
        "4:3": {"1K": "1216x896", "2K": "2432x1792"}
    }
    # 默认为 1024x1024 如果匹配不到
    target_size = size_map.get(aspect_ratio, {}).get(quality, "1024x1024")

    # 目标路径：修改为相对于用户主目录的 .gemini\images
    target_dir = os.path.join(os.path.expanduser("~"), ".gemini", "images")
    output_path = os.path.join(target_dir, filename)
    
    # 确保输出目录（包括子目录）存在
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 模型名 (不带后缀，完全依赖 extra_body)
    model_name = env_vars.get('NANOBANANA_MODEL', 'gemini-3-pro-image')
    
    logging.info(f"Connecting to: {base_url}")
    logging.info(f"Model: {model_name} | Size: {target_size}")

    try:
        response = client.chat.completions.create(
            model=model_name,
            extra_body={ "size": target_size },
            messages=[{
                "role": "user",
                "content": f"{prompt}, high quality, {quality} resolution"
            }]
        )
        
        content = response.choices[0].message.content
        if download_image(content, output_path):
            logging.info(f"SUCCESS: Image saved to {output_path}")
        else:
            sys.exit(1)

    except Exception as e:
        logging.error(f"OpenAI Call Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

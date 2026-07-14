"""
<!-- Standard Header -->
@Input: prompts/*.md
@Output: NN-slide-*.png
@Phase: Phase 4 - Visual Forging & Assembly (图像生成器)
@Maintenance Protocol: API or path logic changes must sync SKILL.md Phase 4.
"""
import os
import glob
import json
import base64
import requests
import time
import argparse
import logging
import re
from datetime import datetime
from pathlib import Path
from openai import OpenAI

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def load_env():
    """Use process environment variables; do not discover credential files."""
    return dict(os.environ)

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
            # Security: Enable SSL certificate verification to prevent MitM attacks
            res = requests.get(link, timeout=60)
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

def render_slide_image(prompt_text, output_path, env_vars):
    """使用 OpenAI 协议生成图片"""
    api_key = env_vars.get('IMAGE_API_KEY')
    base_url = env_vars.get('IMAGE_API_BASE_URL')
    model_name = env_vars.get('IMAGE_MODEL')
    
    if not api_key or not base_url or not model_name:
        logging.error("IMAGE_API_KEY, IMAGE_API_BASE_URL, and IMAGE_MODEL are required.")
        return False

    client = OpenAI(base_url=base_url, api_key=api_key)
    
    # 默认分辨率配置
    quality = "4K"
    target_size = "3840×2160" # 16:9 4K

    logging.info(f"Generating image with {model_name} | Target: {output_path}")

    try:
        response = client.chat.completions.create(
            model=model_name,
            extra_body={ "size": target_size },
            messages=[{
                "role": "user",
                "content": f"{prompt_text}, high quality, {quality} resolution"
            }]
        )
        
        content = response.choices[0].message.content
        # 确保输出目录存在
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        if download_image(content, output_path):
            logging.info(f"SUCCESS: Image saved to {output_path}")
            return True
        else:
            return False

    except Exception as e:
        logging.error(f"API Call Failed: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Generate slide images from prompts.")
    parser.add_argument("dir", help="Slide deck directory containing prompts/ subdirectory")
    parser.add_argument("--regenerate", "-r", help="Regenerate specific slides (comma-separated indices)")
    args = parser.parse_args()

    env_vars = load_env()
    slide_dir = args.dir
    prompts_dir = os.path.join(slide_dir, "prompts")
    
    if not os.path.exists(slide_dir):
        logging.error(f"Directory {slide_dir} does not exist.")
        return

    if not os.path.exists(prompts_dir):
        logging.error(f"Prompts directory {prompts_dir} does not exist.")
        return

    prompt_files = sorted(glob.glob(os.path.join(prompts_dir, "*.md")))
    
    if not prompt_files:
        logging.info(f"No prompt files found in {prompts_dir}")
        return

    logging.info(f"Found {len(prompt_files)} prompt files.")

    # Determine which slides to process
    slides_to_process = []
    if args.regenerate:
        indices = [int(i.strip()) for i in args.regenerate.split(',')]
        for p_file in prompt_files:
            basename = os.path.basename(p_file)
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
                logging.info(f"Skipping {png_name} (already exists)")
                continue
            slides_to_process.append(p_file)

    if not slides_to_process:
        logging.info("No slides to generate.")
        return

    logging.info(f"Generating images for {len(slides_to_process)} slides...")

    for p_file in slides_to_process:
        basename = os.path.basename(p_file)
        png_name = basename.replace(".md", ".png")
        output_path = os.path.join(slide_dir, png_name)
        
        with open(p_file, "r", encoding="utf-8") as f:
            prompt_content = f.read()
        
        # Retry logic
        max_retries = 2
        success = False
        for attempt in range(max_retries):
            success = render_slide_image(prompt_content, output_path, env_vars)
            if success:
                break
            else:
                logging.info(f"Retry {attempt+1}/{max_retries} for {png_name}...")
                time.sleep(2)
        
        if success:
            time.sleep(1) # Rate limiting
        else:
            logging.error(f"Failed to generate {png_name} after retries.")

if __name__ == "__main__":
    main()

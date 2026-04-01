# -*- coding: utf-8 -*-
"""
thumbnail_exporter.py - 基于 COM 的幻灯片预览图导出引擎
"""

import os
import sys
import time
from pathlib import Path
import subprocess

_ENGINE_DIR = Path(__file__).parent
from engine.com_helper import COMManager

def export_thumbnails(pptx_path: Path, output_dir: Path, scale_width=1280):
    """
    将 PPTX 的每一页导出为 JPG 预览图。
    
    参数:
        pptx_path: PPT 文件路径
        output_dir: 预览图存放目录 (会在此目录下创建以文件名命名的子目录)
        scale_width: 预览图宽度，默认 720p 级别
    """
    import win32com.client
    
    pptx_path = pptx_path.resolve()
    # 创建子目录，使用文件名的哈希或清理后的名称
    thumb_folder = output_dir / pptx_path.stem
    thumb_folder.mkdir(parents=True, exist_ok=True)

    app = None
    pres = None
    exported_paths = []

    try:
        app = COMManager().get_app(visible=True)
        app.Visible = True  # 导出图片建议可见，否则部分渲染可能失败
        app.DisplayAlerts = 0
        
        pres = app.Presentations.Open(str(pptx_path), ReadOnly=True, WithWindow=False)
        total_slides = pres.Slides.Count
        
        # 计算导出高度 (保持 16:9 或原始比例)
        orig_width = pres.PageSetup.SlideWidth
        orig_height = pres.PageSetup.SlideHeight
        scale_height = int((scale_width / orig_width) * orig_height)

        print(f"  [Thumbnail] 导出 {pptx_path.name} ({total_slides} 页)...")
        
        for i in range(1, total_slides + 1):
            slide = pres.Slides(i)
            # 命名规范：slide_001.jpg
            img_path = thumb_folder / f"slide_{i:03d}.jpg"
            # Slide.Export(Path, FilterName, ScaleWidth, ScaleHeight)
            slide.Export(str(img_path), "JPG", scale_width, scale_height)
            exported_paths.append(str(img_path))
            
        print(f"  [Thumbnail] 完成：{thumb_folder}")
        return thumb_folder

    except Exception as e:
        print(f"  [!] 预览图导出失败 {pptx_path.name}: {e}")
        return None
    finally:
        if pres:
            try: pres.Close()
            except Exception: pass
        # 不主动退出 App，由调用方或 scanner 处理以提升批量效率

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python thumbnail_exporter.py <input_pptx> <output_dir>")
    else:
        export_thumbnails(Path(sys.argv[1]), Path(sys.argv[2]))

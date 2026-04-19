# -*- coding: utf-8 -*-
"""
assemble_template.py — 模板优先的 PPT 组装脚本 v3

策略：
  - 纯模板页（封面/过渡页/封底）：直接复制模板指定页，使用 COM 同步 Paste 保留源格式。
  - 内容页：先同步 Paste 模板 P3 建立背景+标题栏，再从源文件复制内容形状，
    使用 Shapes.Paste() 自动将形状颜色映射到目标模板的 ColorScheme。
  - 颜色映射：通过 COM Theme 属性，利用 PowerPoint 原生 ThemeColorScheme 映射机制，
    若源与目标模板存在深浅色系差异，自动交换 ObjectThemeColor (Dark1<->Light1, Dark2<->Light2)，
    确保形状在目标模板中可见且完全保留原生可编辑性。
    
优化：
  1. COM Robustness: 移除 time.sleep()，全面使用同步 Paste() 和 try...finally 确保进程释放。
  2. Color Theme Mapping: 移除 python-pptx 和繁杂 XML 解析，直接操作 COM ObjectThemeColor。
"""

import sys
from pathlib import Path
from datetime import datetime
import subprocess

# 引入进程管理器
_ENGINE_DIR = Path(__file__).parent
sys.path.insert(0, str(_ENGINE_DIR))
from com_helper import COMManager
try:
    from template_manifest import load_template_manifest, normalize_template_manifest
except ImportError:
    from .template_manifest import load_template_manifest, normalize_template_manifest

# ─── 路径配置 ─────────────────────────────────────────────────────────────────

_BASE_DIR = Path(__file__).parent.parent  # engine/ 的上一层 = SlideBlocks 根目录

# ─── 辅助函数 ─────────────────────────────────────────────────────────────────

def _title_threshold_pt(template_config: dict) -> int:
    return template_config["selection_rules"]["title_detection"]["threshold_pt"]


def _exclude_title_area_picture_top_pt(template_config: dict) -> int:
    exclude_shapes = template_config["selection_rules"].get("exclude_shapes") or []
    for rule in exclude_shapes:
        if rule.get("kind") == "picture":
            top_lt_pt = rule.get("top_lt_pt")
            if isinstance(top_lt_pt, int) and top_lt_pt > 0:
                return top_lt_pt
    return _title_threshold_pt(template_config)


def get_source_title(src_slide, template_config):
    """从源幻灯片提取标题文字，同时返回该形状的索引（用于精准排除）。"""
    title_threshold_pt = _title_threshold_pt(template_config)
    for j in range(1, src_slide.Shapes.Count + 1):
        shape = src_slide.Shapes(j)
        try:
            if shape.PlaceholderFormat.Type == 1 and shape.HasTextFrame:
                t = shape.TextFrame.TextRange.Text.strip()
                if t:
                    return t, j
        except Exception:
            pass
    candidates = []
    for j in range(1, src_slide.Shapes.Count + 1):
        shape = src_slide.Shapes(j)
        if shape.Top < title_threshold_pt:
            try:
                if shape.HasTextFrame:
                    t = shape.TextFrame.TextRange.Text.strip()
                    if t:
                        candidates.append((shape.Top, j, t))
            except Exception:
                pass
    if candidates:
        candidates.sort()
        _, j, t = candidates[0]
        return t, j
    return None, None


def get_content_indices(src_slide, template_config, exclude_idx=None):
    """返回要复制的形状索引列表，排除标题及标题区的图片（Logo等）。"""
    MSO_PICTURE = 13  # msoPicture
    picture_exclude_top_pt = _exclude_title_area_picture_top_pt(template_config)
    indices = []
    for j in range(1, src_slide.Shapes.Count + 1):
        shape = src_slide.Shapes(j)
        try:
            if shape.PlaceholderFormat.Type == 1:
                continue
        except Exception:
            pass
        if j == exclude_idx:
            continue
        try:
            if shape.Top < picture_exclude_top_pt and shape.Type == MSO_PICTURE:
                continue
        except Exception:
            pass
        indices.append(j)
    return indices

def set_template_title(target_slide, text, font_size=None):
    """将文字写入模板标题文本框。"""
    best, best_top = None, float("inf")
    for j in range(1, target_slide.Shapes.Count + 1):
        shape = target_slide.Shapes(j)
        try:
            if shape.HasTextFrame:
                existing = shape.TextFrame.TextRange.Text.strip()
                if existing and shape.Top < best_top:
                    best_top = shape.Top
                    best = shape
        except Exception:
            pass
    if best and text:
        try:
            best.TextFrame.TextRange.Text = text
            if font_size:
                best.TextFrame.TextRange.Font.Size = font_size
        except Exception as e:
            print(f"    [警告] 写入标题失败: {e}")

def swap_theme_colors_in_shape(shape, to_light=False, to_dark=False):
    """
    递归处理形状的 ObjectThemeColor，强制适应目标模板背景。
    并对硬编码的纯黑/纯白 RGB 颜色执行底线防御反转。
    msoThemeColorDark1 = 1, msoThemeColorLight1 = 2
    msoThemeColorDark2 = 3, msoThemeColorLight2 = 4
    """
    try:
        if shape.Type == 6: # msoGroup
            for i in range(1, shape.GroupItems.Count + 1):
                swap_theme_colors_in_shape(shape.GroupItems.Item(i), to_light, to_dark)
            return

        def _swap_color(color_format):
            try:
                tc = color_format.ObjectThemeColor
                if tc == 1: color_format.ObjectThemeColor = 2 # Dark1 -> Light1
                elif tc == 2: color_format.ObjectThemeColor = 1 # Light1 -> Dark1
                elif tc == 3: color_format.ObjectThemeColor = 4 # Dark2 -> Light2
                elif tc == 4: color_format.ObjectThemeColor = 3 # Light2 -> Dark2
                elif tc == 0 or tc == 59: # 0=msoNotThemeColor, 59=msoThemeColorMixed
                    rgb = color_format.RGB
                    # COM 返回的 RGB 是整数，纯白 16777215，纯黑 0
                    if to_light and rgb > 15000000: # 近似白色
                        color_format.RGB = 0 # 强制转黑
                    elif to_dark and rgb < 1000000: # 近似黑色
                        color_format.RGB = 16777215 # 强制转白
            except Exception:
                pass

        try:
            if shape.Fill.Visible: _swap_color(shape.Fill.ForeColor)
        except Exception: pass
        
        try:
            if shape.Line.Visible: _swap_color(shape.Line.ForeColor)
        except Exception: pass

        try:
            if shape.HasTextFrame and shape.TextFrame.HasText:
                runs = shape.TextFrame.TextRange.Runs()
                for i in range(1, runs.Count + 1):
                    _swap_color(runs.Item(i).Font.Color)
        except Exception: pass

    except Exception as e:
        print(f"      [警告] 形状主题色自适应失败: {e}")

# ─── 主流程 ───────────────────────────────────────────────────────────────────

def assemble(plan, output_path: str, template_path: str, manifest_path: str | None = None):
    output_path_obj = Path(output_path).resolve()
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    template_path_obj = Path(template_path).resolve()
    manifest, manifest_error = load_template_manifest(manifest_path)
    if manifest_error:
        raise ValueError(manifest_error)
    template_config = normalize_template_manifest(manifest)
    page_roles = template_config["page_roles"]
    transition_page = page_roles["transition"]
    content_with_title_page = page_roles["content_with_title"]
    content_without_title_page = page_roles["content_without_title"]
    paste_retry_count = template_config["rendering_rules"]["paste_retry_count"]
    paste_retry_delay_s = template_config["rendering_rules"]["paste_retry_delay_ms"] / 1000
    transition_default_font_size = template_config["transition_default_font_size"]

    # 使用 COMManager 启动
    mgr = COMManager()
    pptApp = mgr.get_app(visible=True)
    try:
        pptApp.DisplayAlerts = 0
    except Exception:
        pass

    # 自动检测颜色修复方向
    template_is_light = "浅色底" in template_path_obj.name
    template_is_dark  = "深色底" in template_path_obj.name

    pres = None
    try:
        print(f"\n[组装引擎] IntelliBlock V2.1 - 启动组装任务：{len(plan)} 页")

        # 基于模板新建
        pres = pptApp.Presentations.Open(str(template_path_obj), ReadOnly=True, Untitled=True, WithWindow=True)
        while pres.Slides.Count > 0:
            pres.Slides(1).Delete()

        for i, item in enumerate(plan, 1):
            replace_title = item.get("replace_title")
            # 允许在 item 中显式配置 font_size，否则对于过渡页(2)默认使用 40
            font_sz = item.get("font_size")

            # ─── 剪贴板重试粘贴辅助函数 ───
            def _safe_paste(target_collection):
                import time
                for attempt in range(paste_retry_count):
                    try:
                        return target_collection.Paste()
                    except Exception:
                        if attempt == paste_retry_count - 1:
                            raise
                        time.sleep(paste_retry_delay_s)
                return None

            # 纯模板页
            if "template_page" in item:
                tmpl_page = item["template_page"]
                print(f"  P{i:02d} [模板 P{tmpl_page}] " + (f"→ 「{replace_title}」" if replace_title else ""))
                
                tmpl_pres = pptApp.Presentations.Open(str(template_path_obj), ReadOnly=True, WithWindow=False)
                try:
                    tmpl_pres.Slides(tmpl_page).Copy()
                    
                    pasted_range = _safe_paste(pres.Slides)
                    if replace_title:
                        try:
                            sz = font_sz if font_sz else (transition_default_font_size if tmpl_page == transition_page else None)
                            set_template_title(pasted_range(1), replace_title, font_size=sz)
                        except Exception:
                            pass
                finally:
                    tmpl_pres.Close()
                continue

            # 内容页组装
            src = Path(item["src"]).resolve()
            page = item["page"]
            
            src_is_dark  = "深色底" in src.name
            src_is_light = "浅色底" in src.name
            swap_to_light = template_is_light and src_is_dark
            swap_to_dark = template_is_dark and src_is_light
            
            # 判断是否需要颜色自适应
            force_fix = item.get("fix_colors")
            force_dark = item.get("fix_colors_dark")
            
            do_to_light = force_fix if force_fix is not None else swap_to_light
            do_to_dark = force_dark if force_dark is not None else swap_to_dark
            swap_dark_light = do_to_light or do_to_dark

            src_pres = pptApp.Presentations.Open(str(src), ReadOnly=True, WithWindow=False)
            try:
                src_slide = src_pres.Slides(page)

                source_title, title_shape_idx = get_source_title(src_slide, template_config)
                source_has_title = source_title is not None

                # 复制背景框架
                tmpl_page = content_with_title_page if source_has_title else content_without_title_page
                tmpl_pres = pptApp.Presentations.Open(str(template_path_obj), ReadOnly=True, WithWindow=False)
                try:
                    tmpl_pres.Slides(tmpl_page).Copy()
                    pasted_slide = _safe_paste(pres.Slides)(1)
                finally:
                    tmpl_pres.Close()

                if source_has_title:
                    try:
                        set_template_title(pasted_slide, replace_title or source_title, font_size=font_sz)
                    except Exception:
                        pass
                
                # 复制形状
                content_indices = get_content_indices(
                    src_slide,
                    template_config,
                    exclude_idx=title_shape_idx if source_has_title else None,
                )
                if content_indices:
                    src_slide.Shapes.Range(content_indices).Copy()
                    pasted_shapes = _safe_paste(pasted_slide.Shapes)
                    
                    if swap_dark_light and pasted_shapes:
                        import time
                        for j in range(1, pasted_shapes.Count + 1):
                            for attempt in range(5):
                                try:
                                    shape_item = pasted_shapes.Item(j)
                                    swap_theme_colors_in_shape(shape_item, to_light=do_to_light, to_dark=do_to_dark)
                                    break
                                except Exception as e:
                                    if attempt == 4: raise
                                    time.sleep(0.3)
                    
                print(f"  P{i:02d} [组装] {src.name} 第{page}页" + (" [色系自适应]" if swap_dark_light else ""))
            finally:
                src_pres.Close()

        pres.SaveAs(str(output_path_obj), 24) # 24 = ppSaveAsOpenXMLPresentation
        print(f"\n[完成] 组装结果已保存至：{output_path_obj}")

    except Exception as e:
        print(f"\n[!] 引擎严重异常：{e}")
        import traceback
        traceback.print_exc()
    finally:
        if pres:
            try: pres.Close()
            except Exception: pass
        # 保持 App 运行由用户手动关闭，或下一任务复用

if __name__ == "__main__":
    print("assemble_template.py 是纯引擎，请通过 engine/runner.py 或传入正确的路径调用。")

---
name: academic-scientific-visualization
version: 9.0.0
tier: action-allowed
description: 'Meta-skill for publication-ready scientific figures. Use when creating journal submission figures requiring multi-panel layouts, significance annotations, error bars, colorblind-safe palettes, and specific journal formatting for Nature, Science, Cell, IEEE, ACM, or discipline-specific manuscripts.'
triggers: ["科研作图", "绘制期刊图表", "Scientific Figure", "论文插图", "显著性标注", "误差棒画图"]
---

<strategy-gene>
Keywords: scientific figure, publication figure, multi-panel, significance annotation, colorblind-safe
Summary: Produce publication-ready scientific figures with statistical transparency, journal sizing, and accessible visual design.
Strategy:
1. 1. Target ID: Identify target journal, figure type, panel count, and statistical annotations.
2. 2. Asset Load: Use absolute-path reusable helpers and references for journal specs, palettes, and export validation.
3. 3. Render & Inspect: Render output before final delivery; revise if labels, colors, size, or uncertainty display fail.
AVOID: Never submit low-DPI, unlabeled, color-only, or statistically ambiguous figures.
</strategy-gene>

# Academic Scientific Visualization (学术图表与视觉绘制 V9.0 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. iew_file (读取期刊排版规范)
2. 
3. un_command (执行草稿代码调用 Matplotlib/Seaborn 渲染防爆)
4. 
5. un_command (移动归档生成的图表至目标目录)
6. write_to_file (落盘遥测数据)

## 1. 核心流程与架构 (The Protocol)
### Phase 1: Specifications Loading (规范导入)
1. 强制使用 iew_file 读取 C:\Users\shich\.gemini\config\skills\academic-scientific-visualization\references\publication_guidelines.md 获取排版规范。
2. 确定目标期刊要求（如 DPI、画布物理尺寸、Typography、子图组合排版布局）。

### Phase 2: Design & Encoding (编码与设计)
1. 首选 Matplotlib/Seaborn 组合进行静态出版级渲染。
2. 强制使用 C:\Users\shich\.gemini\config\skills\academic-scientific-visualization\assets\color_palettes.py 中的色盲友好调色板，或加载指定期刊样式的 .mplstyle 预设。
3. 统计透明度注入：小样本数据强制展示所有散点分布；明确所有带误差棒的图表其表示的是 CI/SD 还是 SEM。
4. 在多面板 (Multi-panel) 布局下，统一字号与图例，对齐子图标签 (a, b, c)。

### Phase 3: The Hard Gate (渲染与防爆检查)
1. 使用 
un_command 执行绘图脚本，**必须挂载跨平台字符集安全锁**：
   $env:PYTHONIOENCODING="utf-8"; python <your_draft_script.py>
2. 检查输出文件：使用自带的或 C:\Users\shich\.gemini\config\skills\academic-scientific-visualization\scripts\figure_export.py 工具链导出为 PDF / SVG / 300+DPI PNG。
3. 主代理必须调用自带工具检验产出物：若出现字体截断 (Clipping)、缺失单位、或者空画布，必须在内部自行打回重画。

### Phase 4: Delivery & Telemetry (物理落盘交付)
1. 使用 
un_command 将生成的图表文件移动至指定的论文图片归档目录（如未指定，保存至 C:\Users\shich\.gemini\MEMORY\raw\Scientific_Figures\）。
2. 使用 write_to_file 保存遥测元数据：
   将本次目标期刊、图表类型和导出的格式状态记录为 JSON，写入：
   C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json。

## 2. <Contracts> (输出与交付契约)
- **统计证据契约 (Statistical Clarity)**：所有图表在提交给用户时，必须在配套文本中写明误差棒的统计学意义（CI / SD / SEM），以及显著性标记（P-value）对应的统计检验方法。
- **视觉无障碍契约 (Accessibility Check)**：所有图表颜色必须能在灰度打印模式或色盲模拟下保持可区分性，必须引入线型/形状等备用编码。
- **文件交付契约 (Format Standard)**：严禁以低分辨率格式交付。如果用户未指定，默认同时交付高清光栅图（PNG 300+DPI）与矢量图（SVG/PDF）。

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **路径与环境崩塌 (Pathing Deadlock)**：严禁在调取 assets 或 scripts 时使用非物理路径或相对路径。脚本执行若遗漏 $env:PYTHONIOENCODING="utf-8" 将直接因宕机判定为执行失败。
- **黑盒幻觉交付 (Blind Delivery)**：如果大模型在没有确认生成文件合法性（Size > 0）的前提下，就宣布“图表已准备好”，将被视为最高级别的黑盒幻觉欺骗，直接阻击。
- **空白坐标与未定义单位 (Undefined Metrics)**：如果最终图表的 X/Y 轴缺少物理单位或说明标签，视为不合格草稿，严禁作为最终版本交付。

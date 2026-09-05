# 字体、CJK 与无头运行

自动化运行前显式设置可写缓存和无头后端：

    MPLBACKEND=Agg MPLCONFIGDIR=<writable-temp>/figure-mpl-cache python scripts/font_preflight.py \
      --font-family "Noto Sans CJK SC" --text "时间（小时）" --text "响应值"

字体选择顺序：

1. 用户或期刊明确指定并已授权使用的字体；
2. Noto Sans/Serif CJK 或 Source Han Sans/Serif；
3. 其他能覆盖全部实际字形且许可合适的字体。

不能把字体名称存在当作字形覆盖。font_preflight.py 会用实际 cmap 检查文字；figure_pipeline.py 还会从生成后的 Figure 重新提取标题、轴标签、分类刻度、图例和注释，与 target.labels 对照后再验字形。未声明文字或缺一个字形即为最终输出 FAIL。禁止用不完整 labels 绕过检查，也禁止把 Matplotlib 的静默回退当成通过。

PDF 使用 TrueType 字体并以 pdffonts 检查 emb=yes 和实际字体类型；Type 3 在终稿 Profile 中为 FAIL。工具不可用时返回 NOT_CHECKED，不能以“PDF 能打开”代替嵌入验证。SVG/EPS 的字体自动核验有限；若目标期刊要求嵌入或轮廓化，应人工检查成品或选择可验证的 PDF。

不要在未授权时安装字体、TeX 或系统包。缺字体时报告具体缺字和候选字体，让用户决定。

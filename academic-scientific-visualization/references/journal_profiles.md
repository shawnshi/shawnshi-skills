# 版本化期刊 Profile

机器规则唯一来源是 assets/visual_profiles.json。目前包含：

| Profile | 范围 | 官方来源 | 复核截止 |
|---|---|---|---|
| nature-final | Nature 终稿尺寸与格式 | [Nature final submission](https://www.nature.com/nature/for-authors/final-submission) | 2027-02-26 |
| plos-one-final | PLOS ONE 终稿格式、尺寸、PPI、TIFF | [PLOS ONE Figures](https://journals.plos.org/plosone/s/figures) | 2027-02-26 |
| ieee-journal | IEEE 期刊图形尺寸、分辨率、格式、字体 | [Resolution and Size](https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-graphics-for-your-article/resolution-and-size/)、[File Formatting](https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-graphics-for-your-article/file-formatting/) | 2027-02-26 |
| generic-draft | 通用草稿 | 非期刊认证 | 不适用 |

Profile 必须精确匹配；未知期刊、投稿阶段或图件类型禁止回退到 Nature 或通用规则。超过复核截止、来源为空或状态不是 official_verified 时返回 NOT_CHECKED，不得给出 journal_verified。

静态 Profile 只覆盖共有图形要求。具体栏目、专题、补充材料、图像诚信声明和投稿系统限制可能另有规则。用户要求未收录期刊、规则已过期或提交日期较远时，应查询当前官方作者指南，并把核验日期、链接和未覆盖项写入 QA 报告；不要仅依赖搜索摘要或二手博客。

成品核验基于实际文件：PDF 读页面框、字体嵌入、字体类型和内嵌光栅 PPI；PNG/TIFF 读像素、DPI、物理尺寸、色彩模式、Alpha 和帧数；TIFF 另查 LZW；EPS/SVG 无法自动证明字体时保持 NOT_CHECKED。

Profile 给的是期刊允许范围或最低要求。用户更严格的条件写入 target.requirements，例如 color_mode=RGB、exact_ppi=600、single_frame=true；这些条件与 Profile 同时验证，不能被较宽松的期刊范围覆盖。

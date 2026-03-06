content = """<STYLE_INSTRUCTIONS>
Design Aesthetic: 未来主义医疗 - 极简海军蓝
Background Color: #FFFFFF
Primary Font: Segoe UI, Bold
Secondary Font: Segoe UI, Light
Color Palette: 主色 #002060 (Mentat Navy), 强调色 #00B0F0 (Cyan), 中性色 #595959
Visual Elements: 细线描边、磨砂玻璃质感容器、动态数据梯度
</STYLE_INSTRUCTIONS>

Page 1: [封面] 启动 MSL 驱动的临床 AI 治理：构建医院数字主权防火墙
// NARRATIVE GOAL 为汇报定基调，确立“治理”而非“采购”的战略高度。
// KEY CONTENT
Headline: 启动 MSL 驱动的临床 AI 治理
Sub-headline: 构建 2026 AI 原生医院的数字主权与信任底座
Body/Data:
* 汇报人：卫宁健康战略咨询部
* 目标：申请 Evidence-Mesh 试点项目预算（500万）
// VISUAL 满版出血图像：数字化手术室背景，叠加 Mentat Navy 几何纹理。
// LAYOUT 海报式中心布局
// Script: 院长，今天我们讨论的不是买一个软件，而是如何为医院的 AI 时代立下“数字宪法”。

Page 2: 纯概率模型正导致临床决策的主权坍塌
// NARRATIVE GOAL 揭示现状危机，引入“逻辑湖”与“治理”的必要性。
// KEY CONTENT
Headline: 纯概率模型正导致临床决策的主权坍塌
Sub-headline: “黑盒 AI”带来的自动化偏见已成为三甲医院评级的重大隐患
Body/Data:
* 风险：70% 的初级医生存在对 AI 建议的过度依赖（自动化偏见）。
* 障碍：传统系统无法追踪决策逻辑，难以满足互联互通五级乙等审计要求。
* 方案：引入医疗语义层（MSL），将概率映射为确定性动作。
// VISUAL 左侧为发散的“黑盒”示意，右侧通过 MSL 汇聚为直线。
// LAYOUT 40/60 左右分割：左侧结论 / 右侧逻辑演进图。
// Script: 我们必须在医生与 AI 之间建立“认知摩擦”，防止临床判断力的萎缩。

Page 3: 500 万试点投入：从“代码采购”向“信任审计”的范式转换
// NARRATIVE GOAL 明确资源需求与 ROI，执行决策闭环。
// KEY CONTENT
Headline: 500 万试点投入：从“代码采购”向“信任审计”的范式转换
Sub-headline: 覆盖 2 个核心专科，确立 Evidence-Mesh 证据网标准
Body/Data:
* 预算分配：MSL 定义与模型蒸馏 (200w)、证据网物理实施 (200w)、人员审计培训 (100w)。
* 核心收益：支撑 HIMSS 7 级复评；医疗纠纷逻辑免责证据链覆盖率 100%。
* CTA：申请首期 200 万启动金，锁定专科 Know-how Skill 定义。
// VISUAL 柱状图：展示项目投入后的风险覆盖率跃升。
// LAYOUT 底部高亮 Bumper 布局
// Script: 这笔投入不是成本，而是对医院未来 10 年逻辑资产的保险费。"""

output_path = r'C:\Users\shich\.gemini\presentation-architect-workspace\iteration-1\eval-3\with_skill\outputs\outline.md'
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(content)
print(f"Eval-3 outline generated at: {output_path}")

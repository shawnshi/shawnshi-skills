# 排版铁律与锁死结构 (Winning Health Canvas Mode)

本风格 C 继承了 Canvas Mode 强网格系统，并针对医疗 IT 的严谨性做出了底层硬锁。**违背以下规则会导致页面渲染失败或被验证器直接阻断！**

---

## 1. 卡片嵌套死锁 (Canvas Card Mandatory)

只要使用本流派，所有 `<section class="slide">` 的下一级**必须且只能是** `<div class="canvas-card">`。所有排版内容都必须放在卡片里！

**正确（存活）：**
```html
<section class="slide">
  <div class="canvas-card">
    <div class="kpi-row-4">...</div>
  </div>
</section>
```

**错误（崩溃，白屏）：**
```html
<section class="slide">
  <!-- 缺少 canvas-card 容器，底色和内边距全部丢失！ -->
  <div class="kpi-row-4">...</div>
</section>
```

## 2. 严禁篡改 DOM 结构
本模板中所有的 `grid-12`, `grid-2-7-5`, `kpi-row-4` 都是精确计算过 8px 基准线的。
- ❌ 严禁发明新类名（如写一个 `grid-3-5`）。
- ❌ 严禁在内联写 `style="padding-top: 50px;"`，必须使用现成的间距工具！

## 3. 字体字重白名单
医疗排版非常反感“圆润”的字体。
- 大标题统一使用 `<h2 class="h-xl">`（或 `h-xl-zh`），系统会自动映射到 `Inter` 和 `PingFang SC` 的 200 字重。
- 数字表盘必须使用 `<div class="kpi-mid">` 或 `.kpi-thin`，系统会自动映射到 `JetBrains Mono`（等宽字体），确保数据对齐。

## 4. Motif (图像主题) 封锁
不要尝试在 `images/` 中放置或生成任何插图式的图片。如果需要表示架构图或节点：
- 请使用原生的 HTML/CSS 几何小图标类：`.geo-square`, `.geo-circle-o`, `.geo-dot`。
- 这是医疗系统的视觉护城河，花里胡哨的装饰会被视为缺乏专业性。
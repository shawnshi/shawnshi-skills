# Screenshot & Image Framing (截图与图片封装标准)

当用户提供的配图是**软件截图**、**网页界面**、**代码片段**或**系统架构图**时，严禁将图片 (`<img>`) 裸露直接放入页面。你必须使用以下框架套件进行美化，以符合 Design Vault 工业级视觉标准。

## 1. Browser Window Mockup (浏览器/客户端窗口壳)
适用于：Web端后台截图、网页截图、客户端UI截图。
这会在截图外包裹一个逼真的 macOS 风格标题栏和阴影框。

```html
<div class="mockup-window" data-anim="fade-up">
  <div class="mockup-header">
    <div class="dot r"></div>
    <div class="dot y"></div>
    <div class="dot g"></div>
  </div>
  <div class="mockup-content">
    <img src="your-image-url.jpg" alt="Platform Dashboard">
  </div>
</div>
```
*(注：如果背景是暗色深邃图 `dark-mode`，可以在 `.mockup-window` 加上 `dark-mode` class。)*

## 2. Floating Shadow Box (悬浮阴影卡片)
适用于：移动端 App 截图、没有明确边框的系统架构图、数据统计图表。
这会为图片赋予物理世界的悬浮深度和优雅的圆角。

```html
<div class="shadow-float" data-anim="zoom-in">
  <img src="your-chart.png" alt="Data Flow">
</div>
```

## 3. Edge-to-Edge Bleed (全出血无边框贴边)
适用于：摄影级大图、高分辨率情绪图 (Moodboard)。
如果使用的是图片占位符或风景图，将其放入 Layout 的 `.frame-img` 容器中，让其自动 cover 撑满容器，无需加壳。

## 使用禁忌 (Anti-patterns)
- ❌ **直接把 `<img src="...">` 丢在 `.col` 里。**（这会让浅色截图和幻灯片白色背景融为一体，边缘非常劣质）
- ❌ **手动写内联的粗糙边框**：`style="border: 2px solid black"`（极度违背设计规范）
- ✅ **始终**考虑该截图在当前背景色下的反差感，灵活运用 `mockup-window` 和 `shadow-float`。
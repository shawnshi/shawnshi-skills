# 绑定项目设计系统

仅在用户提供品牌规范、现有演示或明确要求继承既有视觉系统时读取本文件。项目级设计系统是基础主题之上的可选覆盖层，不替代技能内的主题注册表。

## 唯一接入方式

1. 把经过筛选的项目级 token 和组件覆盖写入项目目录的 `src/design-system.css`。
2. 在 `deck.config.json` 中声明：

```json
{
  "designSystem": {
    "stylesheet": "src/design-system.css"
  }
}
```

3. 运行 `node scripts/build-deck.mjs <projectDir>`。构建器会在基础主题之后加载覆盖层：
   - `bundle`：复制为 `dist/assets/design-system.css`；
   - `standalone`：直接内联进 `index.html`。

不使用项目设计系统时，将 `stylesheet` 设为 `null` 或删除 `designSystem` 字段。

## 提取规则

- 先识别颜色、字体栈、字号、间距、边框、圆角和组件修饰，再决定哪些值得继承。
- 只保留能稳定复用的规则；不要复制旧演示的页面内容、绝对定位、页码或一次性修补代码。
- 使用 CSS 自定义属性覆盖主题 token；组件覆盖必须限制在 `body[data-theme="…"]` 或明确的项目类名下。
- 既有 `_d_meta.json`、`_ds_prompt.md` 可作为人工提取输入，但不是构建依赖，也不要直接注入 HTML。
- 品牌字体只能引用已随项目合法提供的本地文件；不得使用 `@import`、远程字体或 CDN。
- 不从旧项目复制 `core.css`、主题 CSS 或运行时文件。它们只允许从本技能根目录的 `assets/` 复制，避免出现第二份真源。

## 离线约束

当 `offlineRequired` 为 `true` 时，`design-system.css` 不得包含 `http(s)`、协议相对 URL 或指向项目外的资源。图片和字体应先本地化，并由项目自己的素材流程管理；构建器不会擅自下载远程资源。

## 最小示例

```css
body[data-theme="winning-clinical"] {
  --primary-600: #005eb8;
  --font-sans-zh: "Source Han Sans SC", "Microsoft YaHei", sans-serif;
}

.project-callout {
  border-inline-start: 4px solid var(--primary-600);
  padding-inline-start: 1rem;
}
```

继承完成后，以构建产物为准运行结构检查和浏览器视觉验证；不要直接交付 `src/design-system.css` 或源片段。

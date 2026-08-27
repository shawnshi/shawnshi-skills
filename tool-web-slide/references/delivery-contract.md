# Web Slide 项目与交付契约

构建型任务使用本契约。项目源文件和交付产物分离；`deck.config.json` 是项目设置的唯一真源，`references/components.json` 是主题资产映射的唯一真源。

## 项目结构

```text
project/
├── deck.config.json
└── src/
    ├── slides/
    │   ├── 001-opening.html
    │   └── 002-context.html
    └── design-system.css       # 可选
```

每个 `src/slides/*.html` 文件必须且只能包含一个顶层 `<section class="slide">`。页面顺序由 `slides.order` 明确指定；未指定时按文件名的稳定字典序排列。
顶层 slide 内可以使用语义化的嵌套 `<section>`，例如架构层或章节分组。
页面片段是声明式内容，不是脚本扩展点：禁止 `<script>`、`<base>`、iframe/object/embed、link 资源、内联 `on*` 事件、srcdoc、表单外发以及 `javascript:`、`vbscript:`、`data:text/html` 等可执行 URL。运行时脚本只能由受控骨架注入。

## `deck.config.json`

```json
{
  "schemaVersion": "1.0.0",
  "title": "Presentation Title",
  "lang": "zh-CN",
  "theme": "swiss",
  "aspect": "16:9",
  "evidencePolicy": "advisory",
  "offlineRequired": true,
  "deliveryProfile": "standard-client",
  "target": {
    "browser": "chromium",
    "os": "current",
    "viewport": { "width": 1920, "height": 1080 }
  },
  "slides": {
    "directory": "src/slides",
    "order": []
  },
  "designSystem": {
    "stylesheet": null
  },
  "output": {
    "mode": "bundle",
    "dir": "dist"
  }
}
```

| 字段 | 约束 |
|---|---|
| `schemaVersion` | 当前为 `1.0.0` |
| `theme` | 必须存在于 `components.json` 的 `themes` 中 |
| `aspect` | 正数比例，格式为 `宽:高`，例如 `16:9`、`16:10`、`4:3` |
| `evidencePolicy` | `advisory` 或 `required`；后者由 QA 禁止使用 `data-evidence="none"` |
| `offlineRequired` | `true` 时拒绝会在运行时加载的远程资源 |
| `deliveryProfile` | `quick-internal`、`standard-client` 或 `high-assurance`；旧配置默认 `standard-client` |
| `target` | 锁定目标浏览器、操作系统和视口；宽高均须为 320–7680 的整数并与 `aspect` 一致 |
| `slides.directory` | 项目根内的片段目录 |
| `slides.order` | 相对 `slides.directory` 的文件名数组；空数组表示稳定字典序 |
| `designSystem.stylesheet` | 可选、位于项目根内的本地 CSS |
| `output.mode` | `bundle` 或 `standalone` |
| `output.dir` | 位于项目根内的输出目录 |

命令行的 `--mode`、`--out`、`--config` 只覆盖本次构建，不回写配置。

### 交付档位与门禁

| 档位 | 静态 QA | 视觉检查 | PDF | 额外约束 |
|---|---|---|---|---|
| `quick-internal` | 必须 | `sample`：首、中、末代表页；不超过三页时全页 | 可选 | 内部快速沟通 |
| `standard-client` | 必须 | `layouts`：每类布局至少一页，并含首末页 | 可选 | 默认客户交付 |
| `high-assurance` | 必须 | `all`：全页 | 必须 | 强制 `offlineRequired=true`、`evidencePolicy=required` |

构建清单以 `requiredGates: {static, visual, pdf}` 输出机器可读门禁。`init --profile high-assurance` 会自动切换到 required 证据策略，并因来源占位未完成返回 `readyForQa:false`。

`target.browser` 只能是 `chromium`、`chrome` 或 `edge`；`target.os` 只能是 `current`、`linux`、`macos` 或 `windows`。视觉 QA 和 PDF 必须使用指定浏览器；当指定操作系统不是 `current` 且与执行环境不一致时，应阻断并明确标记“目标环境未验收”，不得用当前机器的结果代替目标环境验收。

## 页面身份与布局

- 新页面必须显式提供 `data-slide-id`；它是深链接、讲稿和增量构建使用的稳定身份，不得用页码充当身份。
- `data-slide-id` 只能包含小写字母、数字和连字符，且全 deck 唯一。
- 为兼容旧片段，构建器会从文件名生成缺失的 ID，并写入产物；应在下一次编辑时把该 ID 补回源文件。
- 页面必须使用 `data-layout="<canonical-id>"`，ID 以 `references/layouts.json` 为准。
- `data-evidence` 描述该页证据状态；无事实主张的封面或章节页可使用 `none`，高保障模式除外。
- `init --evidence-policy required` 不伪造来源：示例页会生成空的、可见的 source-note 待填项，并返回 `readyForQa:false`。填写真实来源与日期前，QA 应当失败。

## 主题和资产

- 主题的 `baseStylesheet`、`stylesheet` 从 `references/components.json` 读取。
- 内建 CSS、图标运行时和演示引擎只从技能根目录 `assets/` 读取。禁止从 `starter-components/assets/` 或历史项目复制。
- 内建产物不得包含 Google Fonts、unpkg、jsDelivr 等外部 CDN。
- 项目级覆盖只通过 `src/design-system.css` 接入，详见 `built-in-skills/use-design-system.md`。

### 项目本地素材

- 页面片段中的图片、视频和音频路径以该片段所在目录为基准；`src/design-system.css` 中的字体、图片路径以该 CSS 所在目录为基准。
- 路径必须留在项目根目录内。构建器拒绝 `../` 越界读取，也不会下载远程素材。
- 配置、页面、设计 CSS 和素材均按真实路径校验；项目内符号链接指向项目外时立即拒绝。输出目录不得与源目录重叠，输出路径也不得借符号链接写到项目外。
- `bundle` 会按内容 SHA-256、MIME 和规范扩展名去重，生成 `assets/media/<完整sha256><扩展名>` 并改写 HTML/CSS/SVG 引用；相同内容的多个源文件只交付一份，不同内容不会碰撞。
- `standalone` 会把这些素材编码为 data URI 内联。远程运行时素材在 standalone 中一律拒绝，即使 `offlineRequired=false`。
- 普通 `<a href="https://…">` 证据链接不是运行时依赖，可以保留。

## 输出模式

### Bundle

输出 `index.html`、所需的 `assets/` 和 `delivery-manifest.json`。只复制当前主题与运行时真正使用的 canonical assets；项目素材按内容 hash 去重并改写引用；内容 hash 未变化的文件不会重写。

构建器只可覆盖由同一生成器、兼容清单 schema 的前一版 `delivery-manifest.json` 管理且哈希未被用户修改的输出；生成器版本升级本身不破坏增量构建。输出目录中同名的未管理文件或已修改文件必须阻断构建；只有用户确认目标后才可显式使用 `--force`。构建使用暂存、反向回滚并最后发布清单，失败不得留下看似完整的半成品。

### Standalone

所有内建 CSS、项目级 CSS、图标运行时、演示引擎和页面引用的本地图片、字体及媒体都内联到 `index.html`。Motion 动态导入被关闭并采用内容可见的降级路径。`index.html` 是唯一运行时文件；`delivery-manifest.json` 是交付校验元数据，不被页面加载。

## 交付清单

每次构建生成稳定的 `delivery-manifest.json`，至少记录：生成器版本、模式、主题、比例、页面 ID/源文件、唯一外部运行时依赖 URL 及每个交付文件的 SHA-256。清单本身不参与自身哈希，避免递归和无意义重写。
目标浏览器、操作系统和视口也写入清单，并同步为 HTML 的 `data-target-browser`、`data-target-os`、`data-deck-width` 和 `data-deck-height`。
正式档位的静态 QA 将缺失、失配或被篡改的清单视为阻断性错误，而不是警告。

## 浏览器执行与联网边界

- 视觉 QA 和 PDF 默认只允许当前本地静态服务器的精确 origin，以及 `data:`、`blob:`、`about:`；其他 localhost 端口、公网、`file:` 和外部 WebSocket 均阻断。
- 只有 `offlineRequired:false`、档位不是 `high-assurance` 且用户明确授权联网时，才可为视觉 QA 或 PDF 增加 `--allow-network`；交付说明必须记录依赖域名和联网验收结果。
- `offlineRequired:true` 和 `high-assurance` 不接受 `--allow-network`。命令行参数不得覆盖项目声明的离线真值。
- 不得自动关闭 Chromium 沙箱。root 环境无法安全启动时，应换到非 root 执行；只有用户理解并明确接受风险后才可临时设置 `WEB_SLIDE_ALLOW_NO_SANDBOX=1`。

## QA 凭证与最终验证

- 静态 QA 默认写入 `qa-report/qa-report.json`，并记录当前 HTML、清单、页面 ID、布局和目标配置。
- 视觉 QA 根据 `requiredGates.visual` 自动选择 `sample`、`layouts` 或 `all`，写入 `qa-report/report.json`，并为每张截图记录字节数和 SHA-256。
- PDF 导出成功后最后发布 `qa-report/pdf.json`；其中记录 HTML、清单和 PDF 的 SHA-256、页数、目标环境与网络策略。失败或中断不得留下成功凭证。
- 三类 QA 都绑定清单中全部交付文件的字节数和 SHA-256，并在开始与发布凭证前复核同一快照；运行期间发生变更时必须失败，不能把旧分析绑定到新文件。
- `verify-delivery.mjs` 核对所有必做门禁与当前文件，写入 `qa-report/delivery.json`。可选 PDF 不存在不阻断；一旦存在，其报告也必须有效。任何报告陈旧、文件被修改、覆盖不足、目标环境不符或必做产物缺失都会失败。
- QA 目录、截图、PDF 与凭证必须位于交付根目录内，不得通过符号链接越界。

## 标准命令

```bash
node scripts/init-deck.mjs <projectDir> --title "标题" --theme swiss --aspect 16:9 --mode bundle --profile standard-client --target-browser chromium --target-os current --width 1920 --height 1080
node scripts/build-deck.mjs <projectDir>
node scripts/qa-deck.mjs <projectDir>/dist/index.html --report=<projectDir>/dist/qa-report/qa-report.json
node scripts/visual-qa.mjs <projectDir>/dist/index.html <projectDir>/dist/qa-report
node scripts/export-pdf.mjs <projectDir>/dist/index.html <projectDir>/dist/deck.pdf
node scripts/verify-delivery.mjs <projectDir>/dist/index.html
```

构建成功不等于视觉验收完成。只有最终验证返回 0，才表示该档位要求的静态、视觉与 PDF 门禁已全部满足；无法执行的门禁必须明确标为未完成。

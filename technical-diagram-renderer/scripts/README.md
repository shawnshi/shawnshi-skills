# Technical Diagram Renderer scripts

这些脚本组成一条可回归、默认安全的本地交付链。运行环境为 Python 3.10+；SVG 生成和验证仅使用 Python 标准库。PNG 为可选能力，需要 `rsvg-convert` 或 Inkscape。

在 Windows 中可把下列命令的 `python3` 替换为 `python` 或 `py -3`。

## 推荐入口：render-diagram.py

单命令完成 JSON 读取、语义规范化、自动布局、SVG 生成、安全验证和原子发布：

```bash
python3 scripts/render-diagram.py \
  --type architecture \
  --input input.json \
  --output output/system-architecture \
  --formats svg,json \
  --validate
```

`--output` 可以是输出基名、带 `.svg/.json/.png/.drawio` 后缀的文件名，或一个已经存在的目录。默认输出 `svg,json`；可用格式为：

- `svg`：静态 SVG；
- `json`：完成语义展开和布局后的规范化 JSON；
- `png`：使用 `rsvg-convert`，缺失时自动尝试 Inkscape；
- `drawio`：调用同目录下的 `export_drawio.py`。

原始 JSON 的画布、显式几何、端口和布局控制会在语义展开及自动布局前先行校验，非法值不会被布局器“修好”后继续交付。输入文件不得同时作为任何输出目标；真实目录和特殊文件也不能作为目标。目标 symlink 只替换链接本身，不跟随或删除其指向内容。

所有请求的格式先写入目标目录内的临时目录。只有生成、验证和转换全部成功后才发布；发布前复制已有普通文件或 symlink 作为回滚副本，再以 `os.replace()` 逐文件原子替换。失败时恢复已有成果。成功时 stdout 输出 JSON 摘要，失败信息写入 stderr 并返回非零状态。

PNG 导出存在字体门禁：输入含中日韩文字但系统没有可用 CJK 字体时，脚本停止 PNG 导出并说明所需字体，不生成可能缺字的 PNG；SVG 与 JSON 可单独交付。建议安装 Noto Sans CJK、Source Han Sans、微软雅黑、黑体、苹方或同等字体。

常用参数：

```text
--style 1..7        覆盖输入中的自动风格
--png-width N       指定 PNG 宽度
--no-validate       跳过验证，仅用于定位问题；正式交付不要使用
```

## generate-from-template.py

底层生成器契约：

```bash
python3 scripts/generate-from-template.py TYPE OUTPUT.svg INPUT.json
```

第三个参数也可以是 JSON 字符串；省略时从 stdin 读取。生成器严格检查模板类型、风格、字段类型、有限数值、节点 ID、关系端点、端口和可控样式属性。失败返回非零状态，并保留原输出文件。

正式任务优先使用 `render-diagram.py`，以获得规范化 JSON、最终 SVG 验证和多格式原子发布。

## validate-svg.py

验证现有 SVG：

```bash
python3 scripts/validate-svg.py output/system-architecture.svg --pretty
python3 scripts/validate-svg.py output/system-architecture.svg --report output/validation.json
```

检查范围：

- XML 良构和根元素；
- 全文件严格 UTF-8 解码；UTF-16 或其他编码不进入 XML 解析；
- 静态 SVG 元素白名单；
- `script`、`foreignObject`、事件属性、DOCTYPE/实体；
- 外部 URL、`data:`、`javascript:`、CSS 导入和非局部 `url()`；
- 重复 ID、本地引用和 marker 引用；
- `viewBox` 及可见图元的粗边界。

stdout 始终输出一份 JSON 报告。退出状态：`0` 表示通过，`1` 表示内容无效，`2` 表示文件或调用错误。边界检查是几何门禁，不代替最终人工视觉复核；含 `transform` 的元素会形成明确警告。

## export_drawio.py

将已布局 JSON 转成可编辑 draw.io 文件：

```bash
python3 scripts/export_drawio.py input.json output.drawio
```

它不负责自动布局。应传入 `render-diagram.py` 产出的规范化 JSON，或确保所有节点已有有限的 `x/y/width/height`。

## test-all-styles.py

全矩阵覆盖 7 种自动风格，以及架构、数据流、流程、时序、状态机和 ER 主要图种：

```bash
# 7 × 6 全矩阵；产物置于临时目录，结束后清理
python3 scripts/test-all-styles.py

# 每种风格、每种图型至少一次的快速门禁
python3 scripts/test-all-styles.py --quick

# 保留产物并测试 PNG
python3 scripts/test-all-styles.py --png --output-dir test-output --report test-output/report.json
```

脚本为每个案例调用 `render-diagram.py` 并执行 SVG 验证，最终输出 JSON 汇总；任一案例失败即返回非零状态。

## 单元与安全回归

从技能根目录运行：

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

测试覆盖正常生成、悬空边、重复 ID、未知类型/风格、属性注入、原子覆盖、中文与特殊字符、CJK PNG 字体门禁，以及流程、时序、状态机、ER 的语义展开。修改生成器、布局、语义适配、安全策略或导出链后，应同时运行单元测试和 `test-all-styles.py --quick`。

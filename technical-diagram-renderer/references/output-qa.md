# 输出 QA

QA 分为自动门禁和人工复核。脚本退出状态为 0 只表示自动门禁通过，不代表业务拓扑、行业标准或客户验收已经确认。

## 自动门禁

生成器应在正式文件写入前完成以下检查：

1. JSON 是对象，字段类型、枚举、数量、文本长度和数值范围符合输入契约。
2. 节点 ID 唯一，所有关系端点存在，端口、flow、kind 和 style 均受支持。
3. 颜色、滤镜、marker、dash 和样式覆盖符合白名单；不存在脚本、事件属性、外部资源或非法 XML 字符。
4. 生成结果可被 XML 解析器重新解析，marker 引用完整，根元素为 SVG。
5. 所有检查成功后，才通过同目录临时文件原子替换目标文件。

任何用法、JSON、Schema、图完整性、安全、渲染或写入错误都必须返回非零状态。失败时不得把半成品当作正式输出；若目标文件原先存在，应保持原文件不变。

## 执行检查

优先使用 JSON 文件，避免 shell 转义破坏输入：

```bash
python3 scripts/render-diagram.py \
  --type architecture \
  --input input.json \
  --output output/diagram \
  --formats svg,json \
  --validate
```

检查三项结果：

- 进程退出状态为 0。
- `output.svg` 存在且修改时间符合本次执行。
- 日志未包含 warning、validation error 或回退提示。
- 自动布局统计没有 `overlap`、`container_overflow`、`cycle` 或其他未处理 warning；若存在，必须在人工复核中说明处置结果。

不要仅凭“文件存在”判断成功，也不要在失败后沿用旧 SVG 并声称是本次结果。

需要独立复核现有 SVG 时运行：

```bash
python3 scripts/validate-svg.py output/diagram.svg --pretty
```

验证器退出状态为 0 且 JSON 报告中没有 errors，才算通过自动 SVG 门禁。

## draw.io 导出复核

用户需要可编辑文件时，通过统一入口增加 `drawio`：

```bash
python3 scripts/render-diagram.py \
  --type architecture \
  --input input.json \
  --output output/diagram \
  --formats svg,json,drawio \
  --validate
```

`.drawio` 是从规范化 `nodes`、`containers`、`arrows` 单向生成的未压缩 mxGraph XML。自动导出会检查 XML、ID、有限坐标、节点类型、关系端点和端口；仍需人工确认：

- 文件能在 diagrams.net/draw.io 中打开、移动节点和编辑标签；
- 节点、容器、箭头和路线点数量与 SVG/JSON 一致；
- 专用语义降级为基础形状后没有改变业务含义；
- Style 1–7 的 SVG 视觉令牌不被误认为会完整复制到 draw.io；
- 未承诺从 draw.io 回写 JSON/SVG，也未把单向导出描述成双向 round-trip。

## 人工拓扑复核

- 每个节点都来自用户输入、已授权资料或明确标注的假设。
- 节点名称、边界、系统归属和版本没有被自行扩展。
- 每条箭头的起点、终点、方向、单双向和同步/异步含义正确。
- 数据流、控制流、读、写、反馈等线型与图例一致。
- 流程判断有明确分支标签；时序消息顺序与原始叙述一致。
- ER 基数、PK/FK、状态转换和用例关系均已由业务或技术负责人确认。

## 人工视觉复核

- 标题、节点、箭头标签、容器、图例和页脚均在 viewBox 内，没有裁切。
- 节点不重叠；箭头不穿过非目标节点；标签不压在线条、节点或其他标签上。
- 长中文、英文缩写、数字和换行均可读；未因字体缺失而显示为空白或方框。
- 箭头落在节点边界而不是角点或内部；多条关系可区分。
- 深色主题具备足够对比度；只靠颜色无法区分的关系同时使用线型或标签。
- 图例与内容保持安全间距；外置说明不会被自动扩展画布遗漏。

必要时用可用的 SVG 预览器或浏览器查看成品。只有本地已有可靠转换器且用户要求 PNG 时才做栅格化检查；缺少转换器应记录“PNG 未验证”，不能把它写成通过。

## 结果记录模板

```text
自动校验：通过 / 失败（失败项）
拓扑复核：通过 / 待确认（关系或节点）
视觉复核：通过 / 待调整（裁切、重叠、字体或图例）
draw.io 复核：未请求 / 通过 / 待调整（降级形状或编辑性）
PNG 验证：未请求 / 通过 / 未执行（原因）
```

只有与本次交付相关的自动、拓扑、视觉和格式复核均通过，才能标记为“可交付草图”。正式设计、竣工、验收或合规图仍需相应责任人审核。

## 发布前回归

修改生成器、语义适配器、布局器、验证器、模板或样式后，至少运行：

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 scripts/test-all-styles.py --quick
```

准备发布技能包时再运行完整矩阵：

```bash
python3 scripts/test-all-styles.py
```

完整矩阵覆盖 Style 1–7 和主要 canonical 图型。PNG 不是默认门禁；只有环境已有转换器和 CJK 字体时，才用 `--png` 增加栅格化回归。

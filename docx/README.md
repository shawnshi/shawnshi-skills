# docx
<!-- Input: Content specs, existing .docx paths. -->
<!-- Output: Professional .docx files, XML-level tracked changes. -->
<!-- Pos: Creative/Operational Layer. -->
<!-- Maintenance Protocol: Sync XML repair logic in 'scripts/office/pack.py'. -->

## 核心功能
不仅是 Word 文档生成器，更是精准的 XML 操作引擎。支持基于 `docx-js` 的专业文档构建及底层的 XML 级内容重构与批注。

## 战略契约
1. **XML 语义完整性**: 任何修改必须通过 `unpack -> edit -> pack` 流程，并执行 XML schema 校验。
2. **专业排版**: 强制使用 Arial 字体，严禁使用 Unicode 符号代替原生列表标记。
3. **追踪审计**: 默认以 "Claude" 作为作者记录修订痕迹，确保决策链路的可追溯性。

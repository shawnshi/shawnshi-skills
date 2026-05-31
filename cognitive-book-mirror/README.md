# 认知书籍镜像引擎 (cognitive-book-mirror)

通过双栏结构（左侧客观书籍内容，右侧私域日记/价值观映射）对整本书或长文进行极端个人化的解构与伴读。

## 核心机制
- **上下文打底 (Context Packing)**: 不再像 RAG 一样临时搜索，而是强制将 `USER.md`、`SOUL.md` 和您**过去14天**的 `Diary` 物理级拼接为一个巨型上下文 `context.md`，交给伴读大模型。
- **降权并列 (Fan-out Sub-agent)**: 将大文档先用 Python 按章节切碎，为每章单独启动一个基于此 Context 的分析调用。
- **双栏映射 (Two-Column Mapping)**: 产出一个巨大的 Markdown 表格。
  - 左边：书里说了什么（保持原汁原味）。
  - 右边：这和你最近14天的事、你的价值观有什么直接关系？如果没关系就直接说没关系。

## 快速开始

```bash
# 进入目录
cd ~/.gemini/skills/cognitive-book-mirror

# 安装依赖
pip install -r scripts/requirements.txt

# 开始执行双栏镜像映射
python scripts/orchestrate_mirror.py --file "C:/path/to/your/book.epub"
```

生成结果将存放在 `~/.gemini/MEMORY/raw/read/` 文件夹下。

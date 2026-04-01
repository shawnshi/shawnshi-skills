# -*- coding: utf-8 -*-
"""
vector_store.py - 幻灯片语义向量索引引擎 (Native Gemini Embedding Integration)
"""

import sqlite3
import json
import array
import os
import time
from pathlib import Path

# ─── 容错机制 ───────────────────────────────────────────────────────────
from .utils import with_retry

# 注意：此模块假设调用方已配置相关 API Key 或 环境
# 我们将使用本地 SQLite 存储向量，通过点积 (Dot Product) 或 余弦相似度实现检索

def init_vector_db(db_path: Path):
    """初始化向量存储表。"""
    conn = sqlite3.connect(db_path)
    # 使用 BLOB 存储 float32 数组
    conn.execute("""
        CREATE TABLE IF NOT EXISTS slide_vectors (
            slide_id      INTEGER PRIMARY KEY,
            embedding     BLOB NOT NULL,
            updated_at    TEXT,
            FOREIGN KEY(slide_id) REFERENCES slides(id)
        )
    """)
    conn.commit()
    conn.close()

@with_retry(max_retries=4)
def _call_embed_api(text):
    from google import genai
    from .config import load_config
    
    cfg = load_config().get("models", {})
    embed_model = cfg.get("embedding", "gemini-embedding-2-preview")
    
    api_key = os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    result = client.models.embed_content(
        model=embed_model,
        contents=text,
        config={"output_dimensionality": 768}
    )
    return result.embeddings[0].values

def get_embedding(text: str):
    """
    通过 Gemini API 获取文本的 Embedding (使用 gemini-embedding-2-preview)。
    """
    if not text or len(text.strip()) < 2:
        return None
    
    try:
        return _call_embed_api(text)
    except Exception as e:
        print(f"  [!] Embedding 生成最终失败: {e}")
        return None

def save_vector(db_path: Path, slide_id: int, embedding_list: list):
    """将向量列表存入数据库。"""
    if not embedding_list:
        return
    
    # 转换为 float32 字节流以节省空间
    vec_blob = array.array('f', embedding_list).tobytes()
    
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT OR REPLACE INTO slide_vectors (slide_id, embedding, updated_at)
        VALUES (?, ?, datetime('now'))
    """, (slide_id, vec_blob))
    conn.commit()
    conn.close()

def cosine_similarity(v1_bytes, v2_list):
    """计算余弦相似度（向量检索核心）。"""
    import numpy as np
    v1 = np.frombuffer(v1_bytes, dtype=np.float32)
    v2 = np.array(v2_list, dtype=np.float32)
    
    # 归一化点积
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0
    return np.dot(v1, v2) / (norm1 * norm2)

if __name__ == "__main__":
    from .config import get_db_path
    init_vector_db(get_db_path())
    print("[Vector] 向量存储已初始化。")

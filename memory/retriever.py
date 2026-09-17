"""检索器：BM25（默认） + ChromaDB（语义） + 混合（RRF）。

通过环境变量选择：
    AGENT_RETRIEVER=bm25     → BM25 关键词检索（零依赖）
    AGENT_RETRIEVER=chroma   → ChromaDB 语义检索
    AGENT_RETRIEVER=hybrid   → 两路并跑 + RRF 融合（推荐）

延迟加载：
- ChromaRetriever 初始化时不加载嵌入模型、不创建 collection
- 第一次真正 search 或 index 时才加载
- 避免启动时多等 2-5 秒

RRF (Reciprocal Rank Fusion)：
    score(doc) = Σ 1 / (k + rank_in_list)
"""

from __future__ import annotations

import math
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from memory.session_summary import SessionSummary, session_summary_repo

# ============================================================
# 数据类
# ============================================================


@dataclass
class RetrievedItem:
    """检索结果条目。"""

    session_id: str
    summary: str
    score: float
    timestamp: float
    task_type: str
    source: str = ""  # "vector" / "bm25" / "hybrid"


# ============================================================
# 抽象接口
# ============================================================


class Retriever(ABC):
    """检索器抽象接口。"""

    user_id: str

    @abstractmethod
    def index(self, item: SessionSummary) -> None: ...

    @abstractmethod
    def search(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.0,
        user_id: str = "",
    ) -> list[RetrievedItem]: ...


# ============================================================
# 分词辅助
# ============================================================


def _tokenize(text: str) -> list[str]:
    """中英文混合分词。"""
    text = text.lower()
    tokens: list[str] = []
    tokens.extend(re.findall(r"[a-z][a-z0-9_.]{1,}", text))
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    for i in range(len(chars) - 1):
        tokens.append(chars[i] + chars[i + 1])
    tokens.extend(re.findall(r"[\u4e00-\u9fff]{2,4}", text))
    return tokens


# ============================================================
# BM25 检索器（零依赖）
# ============================================================


class BM25Retriever(Retriever):
    """BM25 关键词检索器。"""

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id

    def index(self, item: SessionSummary) -> None:
        # BM25 每次搜索现算，无需索引
        pass

    def search(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.1,
        user_id: str = "",
    ) -> list[RetrievedItem]:
        uid = user_id or self.user_id
        repo = session_summary_repo(user_id=uid)

        try:
            all_summaries = repo.load_all()
        except Exception:
            return []

        if not all_summaries:
            return []

        docs: list[tuple[SessionSummary, list[str]]] = []
        for s in all_summaries:
            text = f"{s.summary} {' '.join(s.key_facts)}"
            docs.append((s, _tokenize(text)))

        n_docs = len(docs)
        df: dict[str, int] = {}
        for _, tokens in docs:
            for t in set(tokens):
                df[t] = df.get(t, 0) + 1

        avg_len = sum(len(t) for _, t in docs) / max(1, n_docs)
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        k1, b = 1.5, 0.75
        scored: list[tuple[float, SessionSummary]] = []

        for summary, tokens in docs:
            if not tokens:
                continue
            counts: dict[str, int] = {}
            for t in tokens:
                counts[t] = counts.get(t, 0) + 1

            score = 0.0
            doc_len = len(tokens)
            for q in set(query_tokens):
                if q not in counts:
                    continue
                tf = counts[q]
                idf = math.log(1 + (n_docs - df.get(q, 0) + 0.5) / (df.get(q, 0) + 0.5))
                norm = tf * (k1 + 1) / (tf + k1 * (1 - b + b * doc_len / avg_len))
                score += idf * norm

            if score >= min_score:
                scored.append((score, summary))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            RetrievedItem(
                session_id=s.session_id,
                summary=s.summary,
                score=round(score, 3),
                timestamp=s.timestamp,
                task_type=s.task_type,
                source="bm25",
            )
            for score, s in scored[:top_k]
        ]


# ============================================================
# ChromaDB 检索器（延迟加载）
# ============================================================


class ChromaRetriever(Retriever):
    """基于 ChromaDB 的语义检索器（延迟加载）。

    初始化时：
    - 只保存配置，不加载嵌入模型、不连 ChromaDB、不同步索引

    第一次访问 collection 时：
    - 加载 sentence-transformers 模型（2-5 秒）
    - 连接 ChromaDB
    - 同步 Store 数据
    """

    def __init__(
        self,
        user_id: str = "default",
        persist_dir: Path | None = None,
        embedding_model: str | None = None,
    ):
        self.user_id = user_id

        if persist_dir is None:
            from memory.store import agent_home

            persist_dir = agent_home() / "knowledge" / "chroma"
        self.persist_dir = persist_dir

        self.embedding_model_name = embedding_model or os.getenv(
            "AGENT_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"
        )

        # 延迟初始化
        self._client = None
        self._collection = None
        self._embed_fn = None
        self._init_error: str = ""

    # ---------- 延迟加载 ----------

    def _ensure_initialized(self) -> bool:
        """确保 collection 已就绪。返回是否成功。"""
        if self._collection is not None:
            return True
        if self._init_error:
            return False

        try:
            import chromadb
            from chromadb.utils import embedding_functions
        except ImportError as e:
            self._init_error = f"缺依赖: {e}"
            return False

        try:
            self.persist_dir.mkdir(parents=True, exist_ok=True)

            # 嵌入函数
            embed_fn = None
            if os.getenv("AGENT_EMBEDDING_PROVIDER", "").lower() == "openai":
                try:
                    embed_fn = embedding_functions.OpenAIEmbeddingFunction(
                        api_key=os.getenv("OPENAI_API_KEY"),
                        api_base=os.getenv("OPENAI_BASE_URL"),
                        model_name=os.getenv("AGENT_EMBEDDING_MODEL", "text-embedding-3-small"),
                    )
                except Exception:
                    embed_fn = None

            if embed_fn is None:
                try:
                    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                        model_name=self.embedding_model_name,
                    )
                except Exception:
                    embed_fn = embedding_functions.DefaultEmbeddingFunction()

            self._embed_fn = embed_fn

            # Chroma client
            self._client = chromadb.PersistentClient(path=str(self.persist_dir))
            self._collection = self._client.get_or_create_collection(
                name=f"summaries_{self.user_id}",
                metadata={"hnsw:space": "cosine"},
                embedding_function=embed_fn,
            )

            # 首次同步
            self._sync_from_store()
            return True

        except Exception as e:
            self._init_error = str(e)
            return False

    def _sync_from_store(self) -> None:
        """从 Store 同步已有摘要到 ChromaDB。"""
        if self._collection is None:
            return

        repo = session_summary_repo(user_id=self.user_id)
        try:
            summaries = repo.load_all()
        except Exception:
            return

        if not summaries:
            return

        try:
            existing = set(self._collection.get()["ids"] or [])
        except Exception:
            existing = set()

        new_ids: list[str] = []
        new_docs: list[str] = []
        new_metas: list[dict] = []

        for s in summaries:
            if s.id in existing:
                continue
            new_ids.append(s.id)
            new_docs.append(f"{s.summary} {' '.join(s.key_facts)}")
            new_metas.append(
                {
                    "session_id": s.session_id,
                    "task_type": s.task_type,
                    "timestamp": s.timestamp,
                }
            )

        if not new_ids:
            return

        for i in range(0, len(new_ids), 100):
            try:
                self._collection.add(
                    ids=new_ids[i : i + 100],
                    documents=new_docs[i : i + 100],
                    metadatas=new_metas[i : i + 100],
                )
            except Exception:
                continue

    # ---------- 属性访问 ----------

    @property
    def collection(self):
        """访问时触发初始化。"""
        self._ensure_initialized()
        return self._collection

    def count(self) -> int:
        """向量数量。未初始化则触发。"""
        self._ensure_initialized()
        if self._collection is None:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    # ---------- 索引 / 检索 ----------

    def index(self, item: SessionSummary) -> None:
        if not self._ensure_initialized():
            return
        text = f"{item.summary} {' '.join(item.key_facts)}"
        try:
            self._collection.upsert(
                ids=[item.id],
                documents=[text],
                metadatas=[
                    {
                        "session_id": item.session_id,
                        "task_type": item.task_type,
                        "timestamp": item.timestamp,
                    }
                ],
            )
        except Exception:
            pass

    def search(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.0,
        user_id: str = "",
    ) -> list[RetrievedItem]:
        if not self._ensure_initialized():
            return []

        uid = user_id or self.user_id

        collection = self._collection
        if uid != self.user_id:
            try:
                collection = self._client.get_or_create_collection(
                    name=f"summaries_{uid}",
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception:
                return []

        try:
            results = collection.query(
                query_texts=[query],
                n_results=top_k,
            )
        except Exception:
            return []

        if not results or not results.get("ids"):
            return []

        items: list[RetrievedItem] = []
        for i, _doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i] if results.get("metadatas") else {}
            distance = results["distances"][0][i] if results.get("distances") else 1.0
            score = 1.0 - distance
            if score < min_score:
                continue
            items.append(
                RetrievedItem(
                    session_id=meta.get("session_id", ""),
                    summary=(results["documents"][0][i] if results.get("documents") else ""),
                    score=round(score, 3),
                    timestamp=meta.get("timestamp", 0.0),
                    task_type=meta.get("task_type", "other"),
                    source="vector",
                )
            )
        return items

    def reset(self) -> None:
        """清空 collection（调试）。"""
        if not self._ensure_initialized():
            return
        try:
            self._client.delete_collection(f"summaries_{self.user_id}")
            self._collection = self._client.get_or_create_collection(
                name=f"summaries_{self.user_id}",
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            pass


# ============================================================
# 混合检索器（Chroma + BM25 + RRF）
# ============================================================


class HybridRetriever(Retriever):
    """混合检索：向量 + 关键词，用 RRF 融合。

    延迟加载：Chroma 部分第一次检索时才真正初始化。
    """

    def __init__(
        self,
        user_id: str = "default",
        rrf_k: int = 60,
        candidate_multiplier: int = 3,
    ):
        self.user_id = user_id
        self.rrf_k = rrf_k
        self.candidate_multiplier = candidate_multiplier

        self.bm25 = BM25Retriever(user_id=user_id)

        # ChromaRetriever 构造不再触发模型加载
        try:
            self.chroma: ChromaRetriever | None = ChromaRetriever(user_id=user_id)
        except Exception:
            self.chroma = None

    @property
    def is_hybrid(self) -> bool:
        """是否两路都在跑。"""
        if self.chroma is None:
            return False
        # 探测一次
        return self.chroma._ensure_initialized()

    def index(self, item: SessionSummary) -> None:
        if self.chroma is not None:
            try:
                self.chroma.index(item)
            except Exception:
                pass

    def search(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.0,
        user_id: str = "",
    ) -> list[RetrievedItem]:
        uid = user_id or self.user_id
        candidate_k = max(top_k * self.candidate_multiplier, 10)

        vector_items: list[RetrievedItem] = []
        bm25_items: list[RetrievedItem] = []

        if self.chroma is not None:
            try:
                vector_items = self.chroma.search(
                    query, top_k=candidate_k, min_score=0.0, user_id=uid
                )
            except Exception:
                vector_items = []

        try:
            bm25_items = self.bm25.search(query, top_k=candidate_k, min_score=0.0, user_id=uid)
        except Exception:
            bm25_items = []

        if not vector_items and not bm25_items:
            return []
        if not vector_items:
            return self._finalize(bm25_items, top_k, min_score, "bm25")
        if not bm25_items:
            return self._finalize(vector_items, top_k, min_score, "vector")

        fused = self._rrf_fuse(vector_items, bm25_items)
        return self._finalize(fused, top_k, min_score, "hybrid")

    def _rrf_fuse(
        self,
        vector_items: list[RetrievedItem],
        bm25_items: list[RetrievedItem],
    ) -> list[RetrievedItem]:
        k = self.rrf_k
        scores: dict[str, float] = {}
        items_by_key: dict[str, RetrievedItem] = {}

        for rank, item in enumerate(vector_items, start=1):
            key = item.session_id or item.summary[:64]
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in items_by_key:
                items_by_key[key] = item

        for rank, item in enumerate(bm25_items, start=1):
            key = item.session_id or item.summary[:64]
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in items_by_key:
                items_by_key[key] = item

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        result: list[RetrievedItem] = []
        for key, score in ranked:
            item = items_by_key.get(key)
            if item is None:
                continue
            result.append(
                RetrievedItem(
                    session_id=item.session_id,
                    summary=item.summary,
                    score=round(score, 6),
                    timestamp=item.timestamp,
                    task_type=item.task_type,
                    source="hybrid",
                )
            )
        return result

    def _finalize(
        self,
        items: list[RetrievedItem],
        top_k: int,
        min_score: float,
        source: str,
    ) -> list[RetrievedItem]:
        result = [it for it in items if it.score >= min_score]
        result = result[:top_k]
        for it in result:
            it.source = source
        return result

    def stats(self) -> dict:
        return {
            "user_id": self.user_id,
            "hybrid": self.is_hybrid,
            "chroma_error": (self.chroma._init_error if self.chroma is not None else "N/A"),
            "chroma_count": (self.chroma.count() if self.chroma is not None else 0),
        }


# ============================================================
# 工厂
# ============================================================

_RETRIEVER_CACHE: dict[str, Retriever] = {}


def get_retriever(user_id: str = "default") -> Retriever:
    """按环境变量返回检索器。

    - AGENT_RETRIEVER=bm25（默认）  → 纯关键词
    - AGENT_RETRIEVER=chroma       → 纯语义
    - AGENT_RETRIEVER=hybrid       → 混合

    注意：Chroma/Hybrid 的构造不再触发模型加载，
    只有第一次 search/index 时才会真正初始化。
    """
    kind = os.getenv("AGENT_RETRIEVER", "bm25").lower()
    cache_key = f"{kind}:{user_id}"

    if cache_key in _RETRIEVER_CACHE:
        return _RETRIEVER_CACHE[cache_key]

    if kind == "chroma":
        try:
            r: Retriever = ChromaRetriever(user_id=user_id)
            _RETRIEVER_CACHE[cache_key] = r
            return r
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("chroma_init_failed: %s，降级到 BM25", e)

    elif kind == "hybrid":
        try:
            r = HybridRetriever(user_id=user_id)
            _RETRIEVER_CACHE[cache_key] = r
            return r
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("hybrid_init_failed: %s，降级到 BM25", e)

    r = BM25Retriever(user_id=user_id)
    _RETRIEVER_CACHE[cache_key] = r
    return r


def reset_retriever_cache() -> None:
    """清空缓存（测试）。"""
    _RETRIEVER_CACHE.clear()

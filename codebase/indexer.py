"""Day 8: 代码向量索引与语义检索。

将代码按函数/类切分，生成 embedding，存入 ChromaDB。
支持增量索引和元数据过滤。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import chromadb
from chromadb.config import Settings
from codebase.background_indexer import IndexStatus, IndexProgress,BackgroundIndexer
from codebase.parser import CodeParser, ParsedFile, Symbol
from typing import Callable

ProgressCallback = Callable[[int, int, str], None]

@dataclass
class CodeChunk:
    """一个代码块（可索引单元）。"""
    id: str                      # 唯一 ID (file:start_line)
    text: str                    # 含上下文的完整文本
    file: str
    symbol_name: str
    symbol_kind: str
    start_line: int
    end_line: int
    language: str = "python"


class CodeIndexer:
    """代码向量索引器，基于 ChromaDB。"""

    def __init__(
        self,
        parser: CodeParser,
        persist_dir: str | Path = ".code_index",
        collection_name: str = "codebase",
        embedding_function=None,
    ):
        self.parser = parser
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        # 默认使用 Chroma 内置的 all-MiniLM-L6-v2
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_function,
            metadata={"hnsw:space": "cosine"},
        )

    def _chunk_file(self, parsed: ParsedFile) -> Iterator[CodeChunk]:
        """将文件切分为代码块。

        策略：按函数/类切分，每个块包含完整的函数体。
        """
        source_text = parsed.source.decode("utf-8", errors="replace")
        lines = source_text.splitlines()

        for sym in parsed.symbols:
            if sym.kind not in ("function", "class", "method"):
                continue

            start = sym.start_line - 1  # 转 0-based
            end = min(sym.end_line, len(lines))
            body = "\n".join(lines[start:end])

            # 上下文增强：在代码前加上文件路径和符号类型
            # 元数据增强能极大提升嵌入质量
            header = f"[FILE: {sym.file}] [KIND: {sym.kind}] [NAME: {sym.name}]\n"
            text = header + body

            chunk_id = f"{sym.file}:{sym.start_line}"
            yield CodeChunk(
                id=chunk_id,
                text=text,
                file=sym.file,
                symbol_name=sym.name,
                symbol_kind=sym.kind,
                start_line=sym.start_line,
                end_line=sym.end_line,
                language=parsed.language,
            )

    def index_all(self, force: bool = False) -> int:
        """索引所有源文件。返回索引的代码块数量。"""
        parsed_files = self.parser.parse_all(force=force)

        # 收集所有 chunk
        all_chunks: list[CodeChunk] = []
        for pf in parsed_files:
            all_chunks.extend(self._chunk_file(pf))

        if not all_chunks:
            return 0

        # 检查已索引的 ID，实现增量索引
        existing = set(self.collection.get()["ids"]) if not force else set()
        new_chunks = [c for c in all_chunks if c.id not in existing]

        if not new_chunks:
            return 0

        # 批量写入
        batch_size = 100
        for i in range(0, len(new_chunks), batch_size):
            batch = new_chunks[i:i + batch_size]
            self.collection.add(
                ids=[c.id for c in batch],
                documents=[c.text for c in batch],
                metadatas=[{
                    "file": c.file,
                    "symbol_name": c.symbol_name,
                    "symbol_kind": c.symbol_kind,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "language": c.language,
                } for c in batch],
            )

        return len(new_chunks)

    def search(
        self,
        query: str,
        top_k: int = 10,
        file_filter: str | None = None,
        kind_filter: str | None = None,
    ) -> list[dict]:
        """语义搜索代码块。

        Args:
            query: 自然语言查询。
            top_k: 返回结果数。
            file_filter: 限定文件（子串匹配）。
            kind_filter: 限定符号类型（function/class/method）。
        """
        where = {}
        if kind_filter:
            where["symbol_kind"] = kind_filter

        results = self.collection.query(
            query_texts=[query],
            n_results=top_k * 2 if file_filter else top_k,
            where=where if where else None,
            include=["documents", "metadatas", "distances"],
        )

        output = []
        if not results["ids"] or not results["ids"][0]:
            return output

        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]
            # 文件过滤
            if file_filter and file_filter not in meta["file"]:
                continue
            output.append({
                "id": doc_id,
                "file": meta["file"],
                "symbol_name": meta["symbol_name"],
                "symbol_kind": meta["symbol_kind"],
                "start_line": meta["start_line"],
                "end_line": meta["end_line"],
                "score": 1.0 - results["distances"][0][i],  # cosine 距离转相似度
                "snippet": results["documents"][0][i][:500],
            })

        return output[:top_k]

    def stats(self) -> dict:
        """返回索引统计。"""
        return {
            "total_chunks": self.collection.count(),
            "persist_dir": str(self.persist_dir),
        }

    def index_files(
        self,
        parsed_files: list,          # list[ParsedFile]
        on_progress: ProgressCallback | None = None,
        batch_size: int = 100,
        force: bool = False,
    ) -> int:
        """索引指定文件列表，按批写入并上报进度。

        Args:
            parsed_files: 已解析的文件列表。
            on_progress: 进度回调 (done, total, current_file)。
            batch_size: ChromaDB 批量写入大小。
            force: 是否忽略已存在的块。

        Returns:
            实际写入的块数量。
        """
        total = len(parsed_files)
        existing = set(self.collection.get()["ids"]) if not force else set()

        pending: list[CodeChunk] = []
        indexed_count = 0

        def flush() -> None:
            nonlocal pending, indexed_count
            if not pending:
                return
            self.collection.add(
                ids=[c.id for c in pending],
                documents=[c.text for c in pending],
                metadatas=[{
                    "file": c.file,
                    "symbol_name": c.symbol_name,
                    "symbol_kind": c.symbol_kind,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "language": c.language,
                } for c in pending],
            )
            indexed_count += len(pending)
            pending = []

        for i, pf in enumerate(parsed_files):
            for chunk in self._chunk_file(pf):
                if chunk.id in existing:
                    continue
                pending.append(chunk)

            if len(pending) >= batch_size:
                flush()

            if on_progress:
                on_progress(i + 1, total, pf.path)

        flush()
        return indexed_count


# ---- LangChain 工具封装 ----

def create_search_tool(bg_indexer: "BackgroundIndexer"):
    """将 BackgroundIndexer 封装为状态感知的 LangChain 工具。"""
    from langchain.tools import tool

    @tool
    def semantic_search(
        query: str,
        top_k: int = 10,
        file_filter: str = "",
        kind_filter: str = "",
    ) -> str:
        """用自然语言语义搜索代码库。

        当 grep 无法找到相关内容时使用此工具。例如搜索
        "处理用户认证的函数" 或 "数据库连接配置"。

        注意：索引在后台构建，首次调用时可能尚未完成。
        如果返回"索引构建中"，请改用 grep_search 或 repo_map，
        稍后再重试本工具。

        Args:
            query: 自然语言查询描述。
            top_k: 返回结果数量，默认 10。
            file_filter: 限定文件路径子串。
            kind_filter: 限定符号类型 (function/class/method)。
        """
        status = bg_indexer.status

        # --- 状态门控 ---
        if status == IndexStatus.INDEXING:
            snap = bg_indexer.snapshot()
            pct = int(100 * snap.done / snap.total) if snap.total else 0
            return (
                f"⚠️ 代码索引正在后台构建中（{snap.done}/{snap.total}, {pct}%）。\n"
                f"当前文件: {snap.current_file}\n"
                f"建议：\n"
                f"  - 改用 grep_search 做精确匹配\n"
                f"  - 改用 repo_map 查看代码结构\n"
                f"  - 稍后再次调用 semantic_search\n"
                f"预计剩余: {_estimate_remaining(snap):.0f}s"
            )

        if status == IndexStatus.PENDING:
            return (
                "⏳ 索引尚未启动。\n"
                "建议：改用 grep_search 或 repo_map 完成当前任务。"
            )

        if status == IndexStatus.FAILED:
            snap = bg_indexer.snapshot()
            return (
                f"❌ 索引构建失败: {snap.error}\n"
                f"建议：改用 grep_search 或 repo_map。"
            )

        # --- 就绪：正常搜索 ---
        results = bg_indexer.search(
            query,
            top_k=top_k,
            file_filter=file_filter or None,
            kind_filter=kind_filter or None,
        )
        if not results:
            return "未找到相关代码"

        lines = []
        for r in results:
            lines.append(
                f"[{r['file']}:{r['start_line']}] "
                f"{r['symbol_kind']} {r['symbol_name']} "
                f"(score: {r['score']:.3f})"
            )
            lines.append(f"  {r['snippet'][:200]}...")
            lines.append("")
        return "\n".join(lines)

    # 把估算方法挂到工具函数上，供上面闭包调用
    def _estimate_remaining(snap: IndexProgress) -> float:
        """基于当前速度估算剩余时间。"""
        if snap.done == 0 or snap.started_at is None:
            return 0.0
        elapsed = snap.elapsed()
        rate = snap.done / elapsed if elapsed > 0 else 0
        if rate <= 0:
            return 0.0
        return (snap.total - snap.done) / rate

    # 绑定到闭包作用域
    semantic_search._estimate_remaining = _estimate_remaining

    return semantic_search


def create_index_status_tool(bg_indexer: "BackgroundIndexer"):
    """新增工具：让 Agent 主动查询索引状态。"""
    from langchain.tools import tool

    @tool
    def index_status() -> str:
        """查询代码索引的构建状态。

        当 semantic_search 返回"索引构建中"后，
        可以用此工具在若干轮之后确认是否就绪。
        """
        snap = bg_indexer.snapshot()
        status = bg_indexer.status

        header = {
            IndexStatus.PENDING: "状态: 未启动",
            IndexStatus.INDEXING: "状态: 构建中",
            IndexStatus.READY: "状态: 就绪 ✓",
            IndexStatus.FAILED: "状态: 失败 ✗",
        }[status]

        return f"{header}\n{snap.to_text()}"

    return index_status
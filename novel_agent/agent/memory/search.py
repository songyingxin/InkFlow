"""
记忆检索模块（FTS5 + jieba 分词）
使用 SQLite FTS5 Trigram 做广域召回 + jieba 分词做语义重排序，
与 OpenClaw / Hermes Agent 的检索方式对齐。
设计要点：
- Trigram 广域召回：容忍错字和部分匹配
- jieba 语义重排：按分词重叠度二次排序
- 时间衰减 + 事实类型差异化衰减率
- 增量索引（基于内容 hash 去重）
"""

import hashlib
import math
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass

import jieba

INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_path TEXT NOT NULL,
    content TEXT NOT NULL,
    chunk_index INTEGER DEFAULT 0,
    line_start INTEGER DEFAULT 0,
    line_end INTEGER DEFAULT 0,
    hash TEXT DEFAULT '',
    timestamp TEXT DEFAULT '',
    tokens_estimate INTEGER DEFAULT 0,
    fact_type TEXT DEFAULT 'temporal',
    reinforcement_count INTEGER DEFAULT 1
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    source,
    tokenize='trigram'
);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source, source_path);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(hash);
"""

_FACT_DECAY_RATES = {
    # 事实类型 → 衰减率（半衰期 = base_half_life_days / decay_rate）
    # identity: 角色身份、世界观规则等恒久事实，几乎不衰减
    "identity": 0.1,
    # decision: 创作决策、剧情方向等较稳定事实，缓慢衰减
    "decision": 0.3,
    # preference: 用户偏好、风格倾向，中等衰减
    "preference": 0.5,
    # temporal: 时间相关事件、临时状态，正常衰减
    "temporal": 1.0,
    # state: 瞬时状态、当前场景，快速衰减
    "state": 2.0,
}

_SOURCE_FACT_TYPE_MAP = {
    "field": "identity",
    "chat": "temporal",
}


@dataclass
class SearchResult:
    """FTS5 搜索结果条目"""
    source: str               # 来源类型：field / chat
    source_path: str          # 来源文件路径
    content: str              # 匹配的文本片段
    score: float = 0.0        # 综合得分（FTS5 rank × 时间衰减 × jieba 重排）
    chunk_index: int = 0      # 文件内的分块索引
    line_start: int = 0       # 起始行号
    line_end: int = 0         # 结束行号
    timestamp: str = ""       # 索引时间戳
    fact_type: str = "temporal"  # 事实类型（影响衰减率）
    reinforcement_count: int = 1  # 强化计数（重复索引时递增，降低衰减）


_jieba_initialized = False


def _ensure_jieba():
    global _jieba_initialized
    if not _jieba_initialized:
        jieba.initialize()
        _jieba_initialized = True


def _estimate_tokens_text(text: str) -> int:
    """
    估算文本的 token 数
    CJK 字符按 1 token 计算，ASCII 字符按 4 字符 = 1 token 计算。
    用于分块时控制每个 chunk 的大小。
    """
    _ensure_jieba()
    words = jieba.lcut(text)
    cjk_count = 0
    ascii_count = 0
    for w in words:
        if any("\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf" for c in w):
            cjk_count += 1
        else:
            ascii_count += len(w)
    return cjk_count + int(ascii_count / 4)


def _now_iso() -> str:
    return datetime.now().isoformat()


def _jieba_word_set(text: str) -> set[str]:
    """返回 jieba 分词后的词集合（去重），用于语义重排"""
    _ensure_jieba()
    words = jieba.lcut(text)
    return {w.strip() for w in words if len(w.strip()) >= 2}


def _jieba_overlap_score(query_words: set[str], content: str) -> float:
    """计算查询词与内容的 jieba 分词重叠度"""
    if not query_words:
        return 0.0
    content_words = _jieba_word_set(content)
    if not content_words:
        return 0.0
    overlap = query_words & content_words
    return len(overlap) / len(query_words)


def _split_query_for_trigram(query: str) -> list[str]:
    """jieba 分词，≥3 字的词用于 trigram，1-2 字词用于 LIKE 回退"""
    _ensure_jieba()
    words = jieba.lcut(query)
    return [w.strip() for w in words if len(w.strip()) >= 3]


def _split_query_short_words(query: str) -> list[str]:
    """jieba 分词中 1-2 字的短词，用于 LIKE 精确匹配"""
    _ensure_jieba()
    words = jieba.lcut(query)
    return [w.strip() for w in words if 1 <= len(w.strip()) <= 2]


class MemoryIndex:
    """
    FTS5 + jieba 记忆索引
    检索流程：Trigram 广域召回 → LIKE 短词回退 → 时间衰减 → jieba 语义重排
    支持增量索引：基于内容 hash 去重，相同内容不重复索引。
    """
    CHUNK_TARGET_TOKENS = 400   # 每个 chunk 的目标 token 数
    CHUNK_OVERLAP_TOKENS = 80   # chunk 之间的重叠 token 数（保证上下文连续性）

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(INDEX_SCHEMA)
            self._migrate_columns(conn)
            conn.commit()

    @staticmethod
    def _migrate_columns(conn: sqlite3.Connection):
        """数据库迁移：为旧表添加 fact_type 和 reinforcement_count 列"""
        try:
            conn.execute("SELECT fact_type FROM chunks LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute(
                "ALTER TABLE chunks ADD COLUMN fact_type TEXT DEFAULT 'temporal'"
            )
            conn.execute(
                "ALTER TABLE chunks ADD COLUMN reinforcement_count INTEGER DEFAULT 1"
            )
            conn.execute(
                "UPDATE chunks SET fact_type = CASE source "
                "WHEN 'field' THEN 'identity' "
                "WHEN 'memory' THEN 'decision' "
                "ELSE 'temporal' END"
            )

    def _connect(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path), check_same_thread=False
            )
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def index_file(self, source: str, path: Path, force: bool = False):
        """
        将文件内容索引到 FTS5
        增量索引机制：计算文件内容 hash，与已索引的 hash 比对，
        相同则跳过（仅递增 reinforcement_count），不同则删除旧索引重新建立。
        """
        if not path.exists():
            return
        content = path.read_text(encoding="utf-8")
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        if not force and self._is_indexed(source, str(path), content_hash):
            return
        chunks = self._chunk_markdown(content)
        with self._connect() as conn:
            fts_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM chunks WHERE source = ? AND source_path = ?",
                    (source, str(path)),
                ).fetchall()
            ]
            if fts_ids:
                placeholders = ",".join("?" * len(fts_ids))
                conn.execute(
                    f"DELETE FROM chunks_fts WHERE rowid IN ({placeholders})",
                    fts_ids,
                )
            conn.execute(
                "DELETE FROM chunks WHERE source = ? AND source_path = ?",
                (source, str(path)),
            )
            for i, (text, line_start, line_end) in enumerate(chunks):
                fact_type = _SOURCE_FACT_TYPE_MAP.get(source, "temporal")
                conn.execute(
                    "INSERT INTO chunks "
                    "(source, source_path, content, chunk_index, "
                    "line_start, line_end, hash, timestamp, tokens_estimate, "
                    "fact_type, reinforcement_count) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,1)",
                    (
                        source,
                        str(path),
                        text,
                        i,
                        line_start,
                        line_end,
                        content_hash,
                        _now_iso(),
                        _estimate_tokens_text(text),
                        fact_type,
                    ),
                )
                conn.execute(
                    "INSERT INTO chunks_fts (content, source) VALUES (?, ?)",
                    (text, source),
                )
            conn.commit()

    def search(
        self,
        query: str,
        source_filter: str | None = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """
        统一搜索入口
        流程：jieba 分词 → Trigram 广域召回 + LIKE 短词回退 → 时间衰减 → jieba 语义重排
        Args:
            query: 搜索查询文本
            source_filter: 来源过滤（field/memory/short_memory），None 表示搜索所有来源
            top_k: 返回结果数量上限
        """
        query_words = _jieba_word_set(query)
        trigram_terms = _split_query_for_trigram(query)
        short_terms = _split_query_short_words(query)
        if not trigram_terms and not short_terms:
            trigram_terms = [query.replace(" ", "")]
        results = self._fts_multi_search(trigram_terms, source_filter, top_k * 3)
        if short_terms:
            like_results = self._like_search(short_terms, source_filter, top_k * 3)
            results = self._merge_results(results, like_results)
        results = self._apply_temporal_decay(results)
        results = self._apply_jieba_rerank(results, query_words)
        return results[:top_k]

    def _fts_multi_search(
        self,
        terms: list[str],
        source_filter: str | None = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """对多个 trigram 词分别搜索，合并去重结果"""
        seen: set[int] = set()
        results: list[SearchResult] = []
        for term in terms:
            batch = self._fts_search(term, source_filter, top_k)
            for r in batch:
                key = hash((r.source, r.source_path, r.content[:80]))
                if key not in seen:
                    seen.add(key)
                    results.append(r)
        return results

    def _like_search(
        self,
        terms: list[str],
        source_filter: str | None = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """LIKE 模糊搜索：对 1-2 字的短词进行精确匹配，作为 Trigram 的回退方案"""
        results: list[SearchResult] = []
        with self._connect() as conn:
            for term in terms:
                like_pattern = f"%{term}%"
                if source_filter:
                    rows = conn.execute(
                        "SELECT source, source_path, content, chunk_index, "
                        "line_start, line_end, timestamp, "
                        "fact_type, reinforcement_count "
                        "FROM chunks WHERE content LIKE ? AND source = ? "
                        "LIMIT ?",
                        (like_pattern, source_filter, top_k),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT source, source_path, content, chunk_index, "
                        "line_start, line_end, timestamp, "
                        "fact_type, reinforcement_count "
                        "FROM chunks WHERE content LIKE ? LIMIT ?",
                        (like_pattern, top_k),
                    ).fetchall()
                for row in rows:
                    results.append(
                        SearchResult(
                            source=row[0],
                            source_path=row[1],
                            content=row[2],
                            score=0.3,
                            chunk_index=row[3],
                            line_start=row[4],
                            line_end=row[5],
                            timestamp=row[6],
                            fact_type=row[7] if len(row) > 7 else "temporal",
                            reinforcement_count=row[8] if len(row) > 8 else 1,
                        )
                    )
        return results

    @staticmethod
    def _merge_results(
        fts_results: list[SearchResult], like_results: list[SearchResult]
    ) -> list[SearchResult]:
        """合并 FTS 和 LIKE 搜索结果，按内容前80字去重"""
        seen: set[str] = set()
        for r in fts_results:
            seen.add(r.content[:80])
        for r in like_results:
            if r.content[:80] not in seen:
                seen.add(r.content[:80])
                fts_results.append(r)
        return fts_results

    def _fts_search(
        self,
        query: str,
        source_filter: str | None = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """FTS5 Trigram 全文搜索：对单个查询词进行匹配，返回按 rank 排序的结果"""
        fts_query = query.replace(" ", "")
        if not fts_query.strip():
            return []
        with self._connect() as conn:
            if source_filter:
                rows = conn.execute(
                    "SELECT c.source, c.source_path, c.content, c.chunk_index, "
                    "c.line_start, c.line_end, c.timestamp, rank, "
                    "c.fact_type, c.reinforcement_count "
                    "FROM chunks_fts f JOIN chunks c ON f.rowid = c.id "
                    "WHERE chunks_fts MATCH ? AND c.source = ? "
                    "ORDER BY rank LIMIT ?",
                    (fts_query, source_filter, top_k),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT c.source, c.source_path, c.content, c.chunk_index, "
                    "c.line_start, c.line_end, c.timestamp, rank, "
                    "c.fact_type, c.reinforcement_count "
                    "FROM chunks_fts f JOIN chunks c ON f.rowid = c.id "
                    "WHERE chunks_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (fts_query, top_k),
                ).fetchall()
        results = []
        for row in rows:
            results.append(
                SearchResult(
                    source=row[0],
                    source_path=row[1],
                    content=row[2],
                    score=-row[7],
                    chunk_index=row[3],
                    line_start=row[4],
                    line_end=row[5],
                    timestamp=row[6],
                    fact_type=row[8] if len(row) > 8 else "temporal",
                    reinforcement_count=row[9] if len(row) > 9 else 1,
                )
            )
        return results

    @staticmethod
    def _apply_jieba_rerank(
        results: list[SearchResult], query_words: set[str]
    ) -> list[SearchResult]:
        """
        jieba 语义重排：按查询词与内容的分词重叠度二次排序
        重叠度越高，分数乘以越大的系数（最高 3x），确保语义相关结果排在前面。
        """
        if not query_words:
            return results
        for r in results:
            overlap = _jieba_overlap_score(query_words, r.content)
            if r.score <= 0.0:
                r.score = 0.5
            r.score = r.score * (1.0 + overlap * 2.0)
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _apply_temporal_decay(
        self, results: list[SearchResult], base_half_life_days: float = 30.0
    ) -> list[SearchResult]:
        """
        时间衰减排序：根据事实类型和经过天数计算衰减系数
        衰减公式：score *= exp(-decay_rate * days_ago / base_half_life_days) * log(1 + reinforcement_count)
        identity 类型衰减极慢（半衰期 300 天），state 类型衰减极快（半衰期 15 天）
        """
        now = datetime.now()
        for r in results:
            if not r.timestamp:
                continue
            try:
                ts = datetime.fromisoformat(r.timestamp)
                days_ago = (now - ts).days
                decay_rate = _FACT_DECAY_RATES.get(r.fact_type, 1.0)
                decay = math.exp(-decay_rate * days_ago / base_half_life_days)
                reinforcement = math.log1p(r.reinforcement_count)
                r.score *= decay * reinforcement
            except (ValueError, TypeError):
                pass
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _chunk_markdown(self, content: str) -> list[tuple[str, int, int]]:
        """
        将 Markdown 文本按 token 数分块
        每个块目标 CHUNK_TARGET_TOKENS 个 token，块之间有 CHUNK_OVERLAP_TOKENS 个 token 的重叠，
        保证跨块边界的内容不会丢失上下文。
        Returns:
            [(块文本, 起始行号, 结束行号), ...]
        """
        lines = content.split("\n")
        chunks = []
        current_chunk = []
        current_tokens = 0
        line_start = 0
        for i, line in enumerate(lines):
            line_tokens = _estimate_tokens_text(line)
            if (
                current_tokens + line_tokens > self.CHUNK_TARGET_TOKENS
                and current_chunk
            ):
                chunks.append(("\n".join(current_chunk), line_start, i - 1))
                overlap_tokens = 0
                overlap_start = len(current_chunk) - 1
                for j in range(len(current_chunk) - 1, -1, -1):
                    t = _estimate_tokens_text(current_chunk[j])
                    if overlap_tokens + t > self.CHUNK_OVERLAP_TOKENS:
                        overlap_start = j + 1
                        break
                    overlap_tokens += t
                current_chunk = current_chunk[overlap_start:]
                current_tokens = sum(_estimate_tokens_text(ln) for ln in current_chunk)
                line_start = i - len(current_chunk)
            current_chunk.append(line)
            current_tokens += line_tokens
        if current_chunk:
            chunks.append(("\n".join(current_chunk), line_start, len(lines) - 1))
        return chunks

    def _is_indexed(
        self, source: str, source_path: str, content_hash: str
    ) -> bool:
        """
        检查文件是否已索引且内容未变化
        如果 hash 匹配，递增 reinforcement_count 并返回 True（跳过重新索引）。
        如果 hash 不匹配，返回 False（需要重新索引）。
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT hash FROM chunks WHERE source = ? AND source_path = ? LIMIT 1",
                (source, source_path),
            ).fetchone()
            if row is not None and row[0] == content_hash:
                conn.execute(
                    "UPDATE chunks SET reinforcement_count = reinforcement_count + 1 "
                    "WHERE source = ? AND source_path = ?",
                    (source, source_path),
                )
                conn.commit()
                return True
            return False

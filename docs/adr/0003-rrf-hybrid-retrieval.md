# ADR-0003: RRF 混合检索（Chroma + BM25）

- **状态**：已采纳
- **日期**：2026-09-18
- **决策者**：@231dff

## 背景

会话摘要积累后需要检索。测试发现：

- **纯向量**（ChromaDB）：搜 `ImportError`、`handle_request`、
  `pytest.raises` 这类专有名词时，向量把语义泛化到不相关结果
- **纯 BM25**：搜"认证"找不到只写了"登录失败"的会话；搜"性能"
  找不到"很慢"

两者互补：向量抓语义，BM25 抓字面。

## 决策

采用 **Hybrid 混合检索**：
query ──┬── ChromaRetriever ──→ top-N 候选
└── BM25Retriever ──→ top-N 候选
↓
RRF 融合
↓
top-K 结果

text

**RRF 公式**：
score(doc) = Σ 1 / (k + rank_in_list)
每个检索列表

text

k = 60（经验值），候选数 = top_k × 3。

**三路降级**：
AGENT_RETRIEVER=hybrid
├── Chroma 可用 → 两路融合
└── Chroma 挂了 → 只用 BM25
└── BM25 永远可用（零依赖）

text

## 理由

### 为什么 RRF 而非加权求和？

两路分数尺度不同：
- Chroma 输出余弦相似度（0-1）
- BM25 输出无界正数

归一化后再加权需要调参，且对新数据分布敏感。
RRF 只看排名，不需要归一化，对尺度鲁棒。

### 为什么不做神经重排序？

书里第三章的完整版是"稠密 + 稀疏 + 重排序"三段。
但重排序需要额外模型（~500MB），且数据量 < 1000 条时
质量差异不明显。

**触发条件**：会话摘要 > 1000 条时再加。

## 后果

### 正面
- 专有名词和近义表达都能召回
- 换后端只改环境变量
- Chroma 挂了不影响主流程

### 负面
- 检索延迟从 ~10ms（BM25）涨到 ~60-300ms（混合）
- 需要 chromadb + sentence-transformers（可选依赖）
- 首次使用下载嵌入模型

### 缓解
- 默认 `AGENT_RETRIEVER=bm25`（零下载）
- 嵌入模型延迟加载（不改启动延迟）
- 可用 OpenAI embedding 替代本地模型

## 参考

- 代码位置：`memory/retriever.py`
- 书《深入理解 AI Agent》第 3.2.4 节（混合检索）
- [RRF 论文](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
# 检索组交付说明（A + B 合并完成）

> 项目分工中检索组的任务：**将研究想法转为检索关键词 → 多源公开论文来源检索 → 获取 BibTeX 并转为 Paper 对象（含摘要）→ 检索结果合并、去重**。
> 本分支（`feat/retrieval-json`）已完成检索组全部任务并通过真实联网端到端验证。

## 一、任务要求逐项对照

| 总要求 | 实现 | 状态 |
|---|---|---|
| 研究想法 → 检索关键词 | [query_planner.py](src/paper_agent/adapters/query_planner.py)：中文/英文想法 → 概念提取 → 每源一条"空格分隔关键词"查询（`SearchPlan`）；纯离线无网络 I/O，可选 LLM 增强且失败自动降级启发式 | ✅ |
| 多源检索（至少 arXiv、OpenAlex、Semantic Scholar、Crossref） | 四个检索器全部实现并接入装配，真实验证四源全通 | ✅ |
| 不是下载、获取 BibTeX 即可 | 检索器只取元数据，不下载任何 PDF；arXiv 直接导出官方 BibTeX，B 线三源由 JSON 元数据本地合成 BibTeX，附于 `Paper.bibtex` | ✅ |
| BibTeX 转 Paper 对象 | A 线：[bibtex_mapper.py](src/paper_agent/adapters/bibtex_mapper.py)（arXiv BibTeX → Paper，缺字段留 None 不编造）；B 线：JSON 直接构造同一 `domain.models.Paper`，两端互不 import | ✅ |
| 最好包括摘要 | 真实 E2E 9/9 篇带摘要：arXiv API 摘要、OpenAlex 倒排索引还原（唯一数据变换难点）、Crossref JATS XML 剥离、S2 abstract 字段 | ✅ |
| 检索结果的合并、去重 | [paper_merger.py](src/paper_agent/adapters/paper_merger.py)：DOI 归一化（`doi.org/10.x` ↔ 裸 `10.x`）、arXiv 版本号剥离、标题标点差异、会议/期刊扩展版不凭标题相似强并；`source_records` 全程不丢 | ✅ |

## 二、检索组内部分工

**A（深度线）**：`arxiv_retriever.py`（官方 arxiv SDK、3s 限速、429 指数退避、Retry-After 秒数+HTTP 日期）、`bibtex_mapper.py`、`paper_merger.py`、`retrieval_common.py`，测试 5 个文件 109 项。

**B（广度线）**：`query_planner.py`（+`_concept_extraction.py` 中文词典概念提取）、`crossref_retriever.py`、`openalex_retriever.py`（倒排摘要还原）、`semantic_scholar_retriever.py`（公众池限流退避）、共享 HTTP 层 `_retriever_utils.py`，测试见 `test_group1_b.py`。

## 三、接口契约（输入 → 输出）

所有接口 `async`，统一使用 `domain.models.Paper` / `SearchPlan`，契约定义见 [ports/contracts.py](src/paper_agent/ports/contracts.py)。

```
ResearchIdea(text, required_terms, excluded_terms, ...)
  └─> QueryPlanner.plan(idea, limit_per_source) -> SearchPlan        # 每源一查、空格分隔关键词、filters 仅用共享协议键
        └─> PaperRetriever.search(plan) -> list[Paper]               # 各检索器只消费自己 source 的查询；带类型异常上抛
              └─> PaperMerger.merge_and_deduplicate(papers) -> list[Paper]  # 去重合并且保留全部来源
```

关键约定（违约会在联调被打回）：
- 未知字段一律 `None`，禁止 `""` / `"unknown"` / 虚构值占位（E2E 中发现并修复了 S2 空 `openAccessPdf.url` 的真实案例）
- 每个来源必须写入 `source_records`，合并后不丢（E2E 实测 12 条全保留）
- 超时 / 限流 / 空结果用**带类型的异常**抛出：`ProviderTimeoutError` / `ProviderRateLimitedError` / `ProviderUnavailableError` / `ProviderResponseError`
- 限流尊重服务方 `Retry-After`（秒数与 HTTP 日期均支持，单次等待封顶 120s）
- planner 查询 `filters` 只使用共享协议键：`date_from` / `date_to` / `excluded_terms` / `required_terms`

## 四、装配与运行

`bootstrap.py` 提供两种装配模式：

| `PAPER_AGENT_ENV` | 说明 |
|---|---|
| `demo`（默认） | 离线 Demo，团队基线行为不变 |
| `retrieval` | 检索段生产装配：真实 planner + 四源检索器 + 真实 merger；后续阶段（筛选/全文/总结/报告）仍为 Demo，待二、三组替换 |

```bash
# 单元测试（离线，150 项）
python -m pytest

# 真实联网端到端验证：想法 → 规划 → 四源检索 → 合并去重 → 契约自检
python scripts/verify_retrieval_e2e.py --idea "用强化学习提升小语言模型的数学推理能力" --limit 3

# A 交付的 arXiv 单源真实验证脚本
python scripts/verify_arxiv_live.py
```

## 五、验证证据

- **单元测试**：150 项全过（B 线 41 + A 线 109），`ruff check src tests scripts` 全绿
- **A 交付包完整性**：`DELIVERY_SHA256.json` 校验 94/94 文件通过
- **真实联网 E2E**（2026-10-09，四源全通零失败）：
  - 规划：中文想法 → `small language model reinforcement learning mathematical reasoning`（四源同查）
  - 检索：arXiv 3 篇、Crossref 3 篇、OpenAlex 3 篇、Semantic Scholar 3 篇，12/12 带摘要
  - 合并：12 → 9 篇，跨源去重命中 2 例（其中 1 篇三源聚合 `arxiv + semantic_scholar + openalex`）
  - 自检：`source_records` 12/12 保留，无空串/占位摘要

## 六、联调时发现并修复的真实问题

1. **A/B 契约冲突**：B 早期 planner 在 `filters` 里塞 `synonyms`，A 的 arXiv 检索器按严格协议拒绝未知过滤器。已统一为共享协议键（用户排除词走 `excluded_terms`，synonyms 放 `SearchPlan` 顶层）。
2. **概念重复**：中文词典同时命中"数学推理"与"推理能力"导致查询词重复；已加词级子串去重。
3. **S2 空串 URL**：真实记录 `openAccessPdf.url=""` 违反"None 不空串"约定导致 pydantic 校验崩溃；已修复并加回归测试（S2、OpenAlex 两处防御）。
4. **S2 公众池限流**：429 退避改为尊重 `Retry-After` + 更长初始退避（2/4/8/16s），公众池窗口恢复后可重试成功。

## 七、给后续组的边界说明

- 检索段输出即 `merge_and_deduplicate` 的结果：统一 `Paper`、多源 `source_records`、含摘要，可直接喂给筛选与重排序组（`PreRanker`）。
- 单源失败时 pipeline 自动降级为警告并保留其余来源；全部失败才整体失败（框架 `application/pipeline.py` 已实现）。
- `Paper.bibtex` 全量携带，供报告组直接引用。
- 二、三组交付后，把 `bootstrap.py` 中其余 Demo 组件逐个替换即可，检索段无需改动。

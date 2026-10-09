# 检索组交付说明

检索组任务已完成：**研究想法 → 检索关键词 → 多源检索 → BibTeX 转 Paper（含摘要）→ 合并去重**。

## 完成内容

| 任务 | 实现 |
|---|---|
| 研究想法 → 检索关键词 | [query_planner.py](src/paper_agent/adapters/query_planner.py)：中英文概念提取，每源一条空格分隔关键词查询，纯离线无网络 I/O |
| 多源检索（4 源） | [arxiv_retriever.py](src/paper_agent/adapters/arxiv_retriever.py)、[openalex_retriever.py](src/paper_agent/adapters/openalex_retriever.py)、[crossref_retriever.py](src/paper_agent/adapters/crossref_retriever.py)、[semantic_scholar_retriever.py](src/paper_agent/adapters/semantic_scholar_retriever.py)：只取元数据不下载，限流退避、超时/空结果用带类型异常上抛 |
| BibTeX 转 Paper | arXiv 走官方 BibTeX 导出 + [bibtex_mapper.py](src/paper_agent/adapters/bibtex_mapper.py)；其余源从 JSON 构造统一 `Paper`，并本地合成 BibTeX 附于 `Paper.bibtex` |
| 摘要 | OpenAlex 倒排索引还原、Crossref JATS XML 剥离、arXiv/S2 直取；缺失留 `None` 不编造 |
| 合并、去重 | [paper_merger.py](src/paper_agent/adapters/paper_merger.py)：DOI 归一化、arXiv 版本号剥离、标题标点归一，会议/期刊扩展版不凭标题相似强并；来源信息 `source_records` 全程保留 |

## 运行

`PAPER_AGENT_ENV=retrieval` 启用真实检索段装配（真实 planner + 四源 + merger），其余阶段仍为 Demo 待其他组替换；默认 `demo` 行为不变。

```bash
python -m pytest                       # 单元测试
python scripts/verify_retrieval_e2e.py  # 真实联网端到端验证
```

## 验证

- 单元测试 150 项全过，`ruff check src tests scripts` 全绿
- 真实联网 E2E：四源各返回 3 篇、12/12 带摘要，合并 12 → 9（含一篇三源聚合），`source_records` 全部保留

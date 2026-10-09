# 检索组 A：实现、运行、合并与验收说明

日期：2026-10-08。适用对象：A 负责人、B 同学、组长。

## 1 完成内容

A 提供 arXiv API 检索、BibTeX 转共享 Paper、多源结果合并去重及相应测试。项目 116 项测试通过；正式 ArxivRetriever 的三组真实查询各成功返回 3 篇论文，HTTP 200。交付副本在全新隔离环境安装离线依赖后，116 项测试、9 篇真实响应回放与三组实时查询全部通过。具体时间和原始证据见交付根目录 verification/验收说明.md。

A_changes 中包含 4 个实现文件、5 个测试文件、3 个验证脚本、2 份说明文档。冻结的共享模型、接口和 bootstrap 保留；B 的正式规划器/三个检索器及共同 bootstrap 装配需要 A/B 与组长一起完成。排序、下载、总结、MCP/UI 的生产实现属于其他分工。

## 2 总体流程

研究想法 → B 的 QueryPlanner → 每来源关键词查询 → A 的 arXiv / B 的其他检索器 → 共享 Paper → A 的 PaperMerger → 预排序候选池 N → 全文处理与证据确认 → 最终 Top-k → 单篇总结 → 综合报告。

在 A 的检索器中：构建 arXiv 查询 → 请求官方 API → 官方 SDK 解析 Atom → 真实字段导出 BibTeX → 用 API 摘要等补充元数据 → BibTexMapper 构建 Paper 并保留来源。合并器收到多个来源的 Paper 后进行规范化、身份匹配、字段补充和来源保留。

A 提供元数据、BibTeX 和已有 PDF 地址，不在检索器中下载 PDF、不提前筛 Top-k、不生成论文结论。各组使用 domain/models.py 中的同一份 Paper。

## 3 对照 A 分工

| 分工要求 | 当前实现及验证 |
|---|---|
| arxiv 库、免 key 调用 API | ArxivRetriever 使用 arxiv.Client/Search，请求 https://export.arxiv.org/api/query；三组真实查询通过 |
| 每 3 秒至少间隔一次请求 | 实际发送前经进程共享 _RateGate；真实客户端不能配置低于 3 秒；跨实例单测通过 |
| 同步 SDK 不阻塞事件循环 | 请求和惰性生成器迭代经 asyncio.to_thread 执行 |
| 结果导出 BibTeX | 用 bibtexparser 序列化实际作者、标题、时间、ID、分类、URL、DOI；独立回读核对通过 |
| 从 API 补充摘要 | SDK summary 传给 supplemental_metadata.abstract，保留原始来源数据 |
| 禁止猜单位、缺字段不编造 | 仅使用明确 affiliations/institutions；未知标量 None，列表 []，状态使用共享枚举 |
| DOI 归一化去重 | 裸 DOI、doi:、带/不带协议的 doi.org/dx.doi.org、URL 编码及大小写统一；拒绝伪装域名 |
| arXiv 版本号去重 | 比较时去除版本号，合并后保留来源；可继续合并互补 DOI/arXiv 的桥接记录 |
| 标题标点差异去重 | 规范化 Unicode、大小写、标点和空白；结合年份、作者和 venue 保守判断 |
| 会议/期刊扩展版保护 | 明确不同 venue 类型不凭相似标题合并；两个不同已知 DOI 始终保护 |
| 超时/429/空结果/缺字段/非法日期单测 | 均有用例；网络失败、空结果、映射异常以类型明确报告 |
| 来源数据不丢失 | source_records 保留不同来源和不同原始快照；只去除完全相同快照 |
| 异步接口与 B 衔接 | 三个公共入口均 async，引用共享 Paper/SearchPlan，A/B 实现互不 import |

## 4 功能细节与效果

### arXiv API 检索

只消费 source=arxiv 的查询。B 的 planner 提供空格分隔关键词，检索器负责拼接 all:、AND、短语、日期、必含词和排除词。请求页大小、迭代数量均受查询 limit 限制，避免只要几篇却请求一百篇。

连接超时默认 10 秒、读取超时 30 秒，max_retries=2 表示初次请求后最多再试两次。保持官方 arxiv SDK、原 API 地址和免 key 的调用方式。

- 429 无有效 Retry-After 时按 30 秒、60 秒退避；服务拒绝请求即共享进程内冷却时间，其他实例也等待。
- Retry-After 支持有限非负秒数及 HTTP 日期。有有效 Date 响应头时用服务器时间计算。非法值采用默认等待策略。
- 新请求前清空上次响应，超时不会沿用上次 429 的提示。普通暂时网络错误按 3 秒、6 秒退避。
- 只重试超时、连接异常、异常空分页和 HTTP 429/500/502/503/504。永久 HTTP 失败立即报告。
- max_retry_wait 默认 120 秒，是单次等待预算；服务要求更长等待时明确失败并保留冷却，不能提前重新请求。
- 空结果默认抛 ArxivNoResultsError；429 抛 ArxivRateLimitError；超时抛 ArxivTimeoutError。网络失败不回退为历史数据。

正式检索器验证 neural retrieval、electron、graph neural networks，各返回 3 篇论文；返回标题/摘要与实际 Atom 响应一致，作者、时间、ID、PDF 地址和 BibTeX 均可追溯。

限速和冷却在同一 Python 进程内共享；多进程部署需组长统一限流。官方 arxiv SDK 没有本项目需要的 BibTeX 导出方法，因此适配器对实际 SDK 字段做本地序列化，原始 API 响应是 Atom。

### BibTeX 与补充元数据映射

每次解析一条 BibTeX，保留原文和补充数据；API 摘要补齐 BibTeX 中缺少的内容。只知道年份时不编造月日，非法日期留空并记录诊断，机构不从作者姓名推断。

venue 先读取 BibTeX 的 journal/booktitle、卷期页，再逐字段补充 API 数据。仅补充 name 不会抹去明确类型；类型冲突保留 BibTeX 的会议/期刊区分并记录诊断。

institutions=None、raw_metadata=None、publication_status=None、作者 affiliations=None 表示未提供，转换后遵守共享模型。错误容器类型报 BibTexMappingError，不把错误输入悄悄当作合法数据。

### 多源合并去重

先深拷贝输入并规范化，再按 DOI、arXiv、保守标题规则匹配。两个不同已知 DOI 不会通过标题或间接标识强行合并。互补强标识补齐后继续检查分组，支持同一论文的多个来源记录完整合并。

缺失的出版状态、项目主页、venue、作者明确机构、全文和代码资产可补齐，已知冲突保留并记录。同来源同 ID 的不同原始快照可并存，请按 source 去重统计来源数。

600 条合成候选检查输出 200 篇，保留全部 600 条来源快照；再次合并结果相同。该规模检查验证纯 Python 逻辑，不作为真实论文检索量。

## 5 运行、测试与组间衔接

交付包适用 Windows x64、CPython 3.12，完整解压后双击 start.cmd。wheelhouse 提供离线依赖，Python 解释器需接收方准备。

- 默认验收：文件哈希、导入位置、依赖、116 项测试、Ruff、30 个项目 Python 文件语法、3 个 CLI 入口、9 篇保存的真实响应回放。
- 实时验收：安装后运行 .\.venv\Scripts\python.exe .\verify_delivery.py --live，额外执行三组 arXiv 请求；需 offline_passed=true 且 live_passed=true。
- 回放明确标记 no_network，用于在断网时检查数据处理，不能代替实时验收。
- scripts/verify_sources_live.py 是其他来源的诊断工具，不替代 B 的正式异步检索器。

合并时将 A_changes 按原路径合入团队工程，公共导出与依赖参考 merge_reference 并保留其他成员内容。团队环境运行 python -m pytest 和 python -m ruff check src tests scripts。B 的正式模块准备好后，在 bootstrap 中共同装配并做真实端到端联调。装配示例和输入输出约定见交付合并说明.md。

## 6 详细代码文件说明

以下覆盖当前 `src/`、`scripts/`、`tests/` 中全部 30 个项目 Python 文件，并补充配置与说明文件。`__pycache__`、pytest/Ruff 缓存和 artifacts 是生成物，不作为新的功能代码解释。

### 6.1 A 的核心实现文件

#### src/paper_agent/adapters/arxiv_retriever.py

作用：实现 `PaperRetriever`，完成 arXiv 关键词检索、HTTP 策略、官方 SDK 结果转换及 BibTeX 导出。

| 类或方法 | 功能 |
|---|---|
| `ArxivError` | arXiv 类错误基类，继承共享提供方异常 |
| `ArxivTimeoutError` | 当前超时及连接失败分类 |
| `ArxivRateLimitError` | HTTP 429 耗尽重试后的分类 |
| `ArxivNoResultsError` | 本来源有效查询无结果 |
| `ArxivSearchConfig` | 不可变配置，验证条数、时间、重试次数和空结果策略 |
| `_RateGate.wait`、`defer` | 控制请求起始间隔、跨实例限流冷却与有限等待；等待后重新核对冷却时间 |
| `_BoundedArxivClient._format_url` | 在官方 SDK URL 生成阶段缩小实际请求页大小 |
| `ArxivRetriever.__init__` | 注入映射器、测试客户端或构建真实 SDK 客户端 |
| `_install_response_capture` | 在实际发送处设置超时和限速，保存最近响应供重试读取 |
| `search` | 筛选本来源查询，检索、转换，并避免多查询重复返回同一版本 ID |
| `_build_query`、`_term`、`_date_filter` | 构造关键词、短语、日期、必含词和排除词语法，拒绝非法约束 |
| `_fetch` | 异步重试循环及异常翻译 |
| `_fetch_sync` | 在工作线程迭代 SDK 生成器并限制数量 |
| `_retry_after`、`_retryable`、`_translate_error` | 解析秒数/HTTP 日期，筛选暂时故障，转换第三方异常 |
| `_map_result` | 把 SDK 结果导出为 BibTeX，构建补充字段，交给统一映射器 |
| `_export_bibtex` | 根据真实元数据生成独立引用条目，保留数学片段并转义常见文本字符 |
| `_value`、`_iso`、`_arxiv_id` | 读取 SDK 属性、日期转字符串、提取 arXiv ID |
| `_raw_result` | 把 SDK 对象转换为可 JSON 序列化的原始记录 |

主要依赖：官方 arxiv、requests、bibtexparser、共享 Paper 和错误类。没有导入 B 的实现，也没有下载 PDF、排序或调用 LLM。

#### src/paper_agent/adapters/bibtex_mapper.py

作用：实现 `BibTexMapper` 协议，把一条 BibTeX 和可选补充数据转换为统一 Paper。

| 类或函数 | 功能 |
|---|---|
| `BibTexMappingError` | 解析失败、缺少必需信息或非法来源等类型化错误 |
| `_decode` | 解码常见 LaTeX 字符，保护 `$...$` 数学片段，规范空白 |
| `_author_tokens` | 仅在顶层 `and` 分隔作者，避免拆开括号保护的机构作者 |
| `_authors` | 解析人名次序与团体作者，创建共享 Author |
| `_json_default` | 将补充元数据中的 date、datetime 转成 ISO 文本 |
| `to_paper` | 异步公开入口，保留已知映射错误，统一包装其他解析异常 |
| `_convert` | 复制来源数据、初始化月份宏、解析单条记录、验证字段、逐字段补齐 venue、处理可选 null、保存来源并构造 Paper |
| `_convert` 内的 `choose`、`diagnose`、`url` | 补充字段选择、记录无效元数据、校验 URL |

主要依赖：bibtexparser、Pydantic、共享模型与规范化函数。`PaperSource` 决定实际来源，不能把 OpenAlex 查询到的 arXiv 论文错误标成由 arXiv API 提供。

#### src/paper_agent/adapters/paper_merger.py

作用：实现 `PaperMerger` 协议，保守合并多源候选，保留来源和下游字段。

| 方法 | 功能 |
|---|---|
| `merge_and_deduplicate` | 深拷贝输入，规范化，合并匹配分组；补齐强标识后继续合并桥接分组，返回新列表 |
| `_normalize` | DOI、arXiv ID 与标题统一表示 |
| `_can_merge` | 决定 DOI、arXiv 和标题路径是否满足合并条件 |
| `_venue_boundary` | 阻止不同明确 venue 类型的标题路径合并 |
| `_merge_into` | 调度标量、出版状态、项目主页、venue、列表、作者、来源、日期及资产的具体合并 |
| `_choose_scalar` | 缺值补充、保留首值或选择更长摘要，并处理冲突 |
| `_merge_publication_time` | 维护日期与年份一致性 |
| `_merge_authors` | 作者去重及明确机构信息补充 |
| `_merge_sources` | 仅去除完全相同的来源快照；同来源同 ID 不同原始响应仍保留 |
| `_merge_code`、`_merge_fulltext` | 按字段保留下游代码与全文资产 |
| `_merge_asset_field` | 资产字段缺值补充与冲突记录 |
| `_max_optional` | 已知引用数取较大值 |
| `_unique`、`_add_conflict` | 保序去重、避免重复冲突说明 |

纯 Python 处理，不访问网络、不调用模型。不会把同一论文的高引用数自动理解为与用户更相关。

#### src/paper_agent/adapters/retrieval_common.py

作用：为映射器和合并器提供一致的规范化规则，避免两处对同一 DOI 或标题产生不同理解。

| 函数 | 功能 |
|---|---|
| `text` | 去掉多余空白；缺失或空文本返回 None |
| `normalize_doi` | 处理 DOI 前缀、带/不带协议的 doi.org 和 dx.doi.org、URL 编码、大小写，并拒绝伪装域名 |
| `normalize_arxiv` | 处理 URL、PDF 后缀、新旧 arXiv ID 格式；可选择去掉版本号 |
| `normalize_title` | Unicode NFKC、大小写、标点与空白归一化，保护有意义的数学符号 |

#### src/paper_agent/adapters/__init__.py

作用：统一导出 A 的三个核心类、配置及异常，方便组长使用 `from paper_agent.adapters import ...`；同时保留骨架的 `build_demo_dependencies`。这是导入门面，不是生产装配器。

### 6.2 组长提供的业务骨架文件

#### src/paper_agent/adapters/demo.py

作用：离线演示所有接口，帮助各组在其他模块未完成时联调。`DemoQueryPlanner` 生成两个来源的计划；`DemoRetriever` 生成显式示例文献；`DemoMerger` 做简单合并；`DemoRanker` 用演示分数排序；`DemoFullTextProcessor` 设置演示解析字段；`DemoVerifier`、`DemoSummarizer`、`DemoReportWriter` 生成示例结果；`build_demo_dependencies` 将这些组件组成流水线依赖。

其中设置 `markdown_path` 不意味着真实文件已经生成；演示作者、论文和总结都不能作为真实检索成果。A 的正式合并逻辑在 `paper_merger.py`，不能因名称相似继续误用 `DemoMerger`。

#### src/paper_agent/application/pipeline.py

作用：整组流程编排。`PipelineDependencies` 声明各阶段需要的组件；`ResearchPipeline` 验证至少两个检索器；`run` 依次执行规划、并发检索、去重、预排序、全文、验证、终排、总结和报告。

内部 `stage` 记录状态、时间、输入输出量和错误；`retrieve_all` 使用 `asyncio.gather(..., return_exceptions=True)` 保留成功来源；`process_pool` 和 `process_one` 用信号量控制全文并发与摘要降级；`verify_all`、`summarize_all` 汇总后续结果。A 不改变这些阶段顺序。

#### src/paper_agent/application/agent.py

作用：`PaperResearchAgent` 是 UI/MCP 的共享门面。`research` 调用流水线；`contract` 返回版本、阶段顺序和至少两个来源等契约。调用方不需要自己重新实现检索到报告的流程。

#### src/paper_agent/bootstrap.py

作用：唯一依赖装配入口。`build_agent` 读取 Settings，当前只接受 Demo 环境并调用 `build_demo_dependencies`；非 Demo 分支明确报错。未来由组长在此组装 A、B 和其他组的生产组件。

#### src/paper_agent/config.py

作用：`Settings` 定义运行环境、并发数、请求超时和数据目录；`from_env` 读取 `PAPER_AGENT_ENV`、`PAPER_AGENT_MAX_CONCURRENCY`、`PAPER_AGENT_REQUEST_TIMEOUT_SECONDS`、`PAPER_AGENT_DATA_DIR`。当前 A 的具体 HTTP 超时由 `ArxivSearchConfig` 控制；生产装配时需显式传递，不能假设设置环境变量就自动改变适配器配置。

#### src/paper_agent/domain/models.py

作用：全组唯一的数据模型。`StrictModel` 禁止未声明字段、去除字符串两端空白并验证赋值；各枚举定义来源、访问、出版、代码和处理状态。`Author`、`Venue`、`SourceRecord`、`FullTextAsset`、`CodeAsset`、`ScoreBreakdown` 组成 `Paper`。`Paper.align_year` 保证日期和年份一致。

`ResearchIdea`、`SearchQuery`、`SearchPlan` 表达输入和查询；`EvidenceRef`、`PaperSummary`、`ResearchReport` 表达证据和报告；`StageEvent`、`PipelineRequest`、`PipelineResult`、`PipelineContract` 表达执行参数和结果。`PipelineRequest.pool_covers_top_k` 验证 N ≥ k；`PipelineResult.total_duration_ms` 汇总阶段时间。A 只导入这些类，不另定义替代模型。

#### src/paper_agent/domain/errors.py

作用：提供全组异常层次。`PaperAgentError` 是根异常，`ProviderUnavailableError` 用于来源服务失败；其他类分别表示 OA 副本不可用、全文解析失败、排序失败、总结校验失败。A 的错误在这个层次内扩展，便于流水线统一处理。

#### src/paper_agent/ports/contracts.py

作用：使用 Protocol 定义组间输入输出。检索段包含 `QueryPlanner`、`PaperRetriever`、`BibTexMapper`、`PaperMerger`；排序段包含 `PreRanker`、`RankingIntentRewriter`、`EvidenceVerifier`、`FinalRanker`；全文与总结包含 `OpenAccessResolver`、`PdfDownloader`、`MarkdownParser`、`FullTextProcessor`、`PaperSummarizer`、`ReportWriter`。这些是协议，不是可直接完成任务的实现。

#### src/paper_agent/mcp_server.py

作用：MCP 服务边界。创建 `MCPServer` 并通过 `build_agent` 获取 Agent；`get_pipeline_contract` 暴露阶段契约；`research_papers` 验证研究想法和 Top-k 等参数并返回结构化结果；`main` 使用 stdio 启动服务。当前实际使用 Demo 依赖，本轮没有启动 MCP Host 验收。

#### src/paper_agent/ui/app.py

作用：Streamlit 页面。`get_agent` 缓存共享 Agent；`run_async` 在页面入口运行异步任务；`split_terms` 处理逗号分隔的约束。页面创建 PipelineRequest，展示论文、总结、报告和审计信息，并提供 JSON/Markdown 下载。它不直接调用 A 的检索器，必须通过装配才能进入真实流程。

### 6.3 包初始化文件

| 文件 | 作用 |
|---|---|
| `src/paper_agent/__init__.py` | 顶层包初始化或包标记，不执行检索 |
| `src/paper_agent/application/__init__.py` | application 子包标记 |
| `src/paper_agent/domain/__init__.py` | domain 子包标记 |
| `src/paper_agent/ports/__init__.py` | ports 子包标记 |
| `src/paper_agent/ui/__init__.py` | ui 子包标记 |

`adapters/__init__.py` 有实际公开导出，已在 A 文件中单独说明。

### 6.4 验证脚本文件

#### scripts/verify_arxiv_live.py

作用：真正的 arXiv 网络验证入口。`verify` 构造共享搜索计划并调用真实 `ArxivRetriever`；响应 hook 保存实际 XML、URL、状态和哈希；检查 Paper 的标题摘要是否与 Atom 对应、引用字段是否可从 BibTeX 独立回读、JSON 是否有效以及重复输入能否去重。可指定多个 query、limit、retries；任一用例失败返回非零退出码。没有本地缓存或样例回退。

#### scripts/verify_sources_live.py

作用：另外三个来源的诊断工具，验证 API 连通性和共享模型兼容性，不是 B 的正式检索器。

`AbstractText` 清理 Crossref 摘要标记；`restore_abstract` 按词位置还原 OpenAlex 摘要并检查缺位与重复；`openalex_paper`、`semantic_scholar_paper` 做诊断用 JSON 映射；`LiveEvidence.get` 保存真实响应并抛 HTTP 错误；`LiveEvidence.crossref_paper` 获取真实 BibTeX 和 JSON 补充后调用 A 的映射器；`check_papers` 验证 JSON 回读与重复去重；`record_failure` 保存失败；`verify` 调度所选来源并查找最多三个候选中的跨源相同 DOI。

Crossref 404 被保存为覆盖范围差异，并尝试下一候选；其他 HTTP 错误不当空结果。此脚本使用同步 requests 且默认不重试，正式服务仍需由 B 提供异步适配、限速和退避。

#### scripts/replay_arxiv_evidence.py

作用：网络不稳定时检查新版 A 逻辑对历史真实响应的处理能力。`replay` 读取以前的 verification.json，校验成功 HTTP 响应文件的 SHA256，使用官方 SDK 解析 Atom，调用 A 的结果转换、独立 BibTeX 回读和合并器，输出 `arxiv_saved_replay.json` 与 `arxiv_export.bib`。没有发出 HTTP 请求，模式名称明确包含 no_network；支持 --output-dir 将新结果写到独立目录。

### 6.5 测试代码文件

#### tests/test_a_delivery.py

作用：A 的交付功能与合并规则测试。`plan_for`、`result`、`paper` 创建明确的测试输入。测试覆盖 BibTeX 作者摘要和来源、多条输入拒绝、检索调用与异常、DOI 归一化、arXiv 版本、标题标点、会议/期刊保护、幂等性、输入不变、外部 ID 冲突、全文和代码字段保留。检索器按每条查询的 limit 限制迭代数量。

#### tests/test_retriever_cases.py

作用：检索器细节与边界测试。`Client`、`FEED`、`fake_wire` 是离线测试设施，拦截 HTTP 并推进虚拟时钟；它们不属于生产数据源。覆盖线程、来源过滤、空结果、查询语法、日期与过滤器、缺失字段、超时、429/503、跨实例限速、分页、BibTeX 引用字段和迭代上限。限流与故障策略用例覆盖 30/60 秒退避、跨实例共享冷却、HTTP 日期、非法 Retry-After、超时不复用旧响应、永久 HTTP 失败、503 提示、超长冷却预算及非有限配置。

#### tests/test_mapper_cases.py

作用：BibTeX 与补充元数据的边界测试，覆盖破损输入、团体作者、LaTeX 重音、数学片段、非法日期、只有年份、日期冲突、输入不变、非法 URL、不得猜机构、错误来源、摘要和原文保留、非法 DOI/年份、不可序列化原始对象，以及 Crossref 月份宏和显式宏覆盖。

#### tests/test_a_integration.py

作用：A 与共享流水线衔接测试。以参数化的两种场景验证 arXiv 成功和失败；使用真实 A 类、测试 SDK 返回及明确标记的第二来源数据，验证 DOI 去重、来源保留、部分失败警告和摘要降级。其余组件来自 Demo，用于契约检查，不能解释为真实下载/排序/总结质量评测。

#### tests/test_models.py

作用：原骨架的数据模型测试。`DomainModelTest` 检查最小 Paper 空值、日期自动填写年份、矛盾日期拒绝及 Agent 阶段顺序。

#### tests/test_pipeline.py

作用：原骨架流水线测试。`FailingRetriever` 模拟提供方失败；`PipelineTest` 验证 Demo 端到端输出、候选池数量约束、单来源失败后保留其他来源结果。该文件的测试成功仅代表演示编排正常。

#### tests/test_a_regressions.py

作用：32 项映射与合并边界用例，覆盖无协议 DOI、伪装域名、互补标识的全部排列、强 DOI 冲突保护、输入不变、venue 部分补充及类型冲突、可选 null、错误容器类型、出版状态、项目主页、venue 缺失字段和同来源不同原始快照。使用明确的合成输入验证逻辑，不将其作为联网结果。

### 6.6 配置与说明文件

| 文件 | 作用 |
|---|---|
| `pyproject.toml` | 包名称、Python 要求、运行与开发依赖、命令入口、pytest、Ruff、构建配置；包含 A 需要的 arxiv 和 bibtexparser |
| `environment.yml` | 推荐 Conda 环境及 `-e .[dev]` 安装声明 |
| `README.md` | 组长提供的项目入口、运行方式与当前 Demo 边界 |
| `docs/ARCHITECTURE.md` | 系统分层与阶段设计 |
| `docs/API_CONTRACTS.md` | 各阶段输入输出和错误约定 |
| `docs/DATA_MODEL.md` | 共享模型和未知信息规范 |
| `docs/ASSIGNMENT_REVIEW.md` | 对课程设计、阶段划分与评测的审查说明 |
| `docs/INTEGRATION_CHECKLIST.md` | 各组交付与生产接线检查项 |
| `docs/MCP_HOST_CONFIG.md` | MCP Host 的配置说明 |
| `docs/交付合并说明.md` | 文件夹用途、B 的输入输出约定、按路径合并步骤、bootstrap 装配参考与共同验收清单 |
| `docs/检索组A总体说明与最终核查.md` | 本文，汇总当前最终状态、效果、操作和逐文件解释 |


## 7 交付辅助文件

交付根目录 verify_delivery.py 是第 31 个 Python 文件，检查完整性、导入路径、依赖、项目测试、Ruff、语法、脚本入口和真实历史响应回放。缺清单或哈希不一致会在加载项目代码前退出；两个隔离目录负向检查验证此行为。

start.cmd 是双击入口；setup_and_verify.ps1 建隔离环境并离线安装；requirements-a-lock.txt 固定 23 个依赖；DELIVERY_SHA256.json 标识固定快照。修改交付文件后应发布新的清单，不能直接忽略失败。verification 保存修复和运行记录。

environment.yml 保留团队原 Conda/Python 3.11 配置，它不是本包 Python 3.12 离线安装方案。完整 UI/MCP 依赖不在 A 独立验证环境中。文件夹用途、合并方法与实时限制以本版交付 README 和验收说明为准。

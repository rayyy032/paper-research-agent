"""Group 1 (B side) production assembly: planner + Crossref/OpenAlex/Semantic Scholar.

Only the components this side owns are built here. Group A's components
(arXiv retriever, BibTeX mapper, merger) are assembled separately; the final
production bootstrap merges both sides into one ``PipelineDependencies``.
"""

from __future__ import annotations

from paper_agent.adapters.crossref_retriever import CrossrefRetriever
from paper_agent.adapters.llm_concept_extractor import LLMConceptExtractor
from paper_agent.adapters.openalex_retriever import OpenAlexRetriever
from paper_agent.adapters.query_planner import HeuristicQueryPlanner
from paper_agent.adapters.semantic_scholar_retriever import SemanticScholarRetriever
from paper_agent.application.pipeline import PipelineDependencies


def build_group_b_components(*, use_llm_planner: bool = False) -> dict[str, object]:
    """Build our four components.

    ``use_llm_planner=False`` (default) keeps the planner fully offline per
    the QueryPlanner contract. Passing True injects the LLM extractor, which
    still degrades to heuristics whenever the LLM is unreachable.
    """
    extractor = LLMConceptExtractor() if use_llm_planner else None
    planner = HeuristicQueryPlanner(concept_extractor=extractor)
    return {
        "query_planner": planner,
        "crossref": CrossrefRetriever(),
        "openalex": OpenAlexRetriever(),
        "semantic_scholar": SemanticScholarRetriever(),
    }


def attach_group_b(
    deps: PipelineDependencies, *, use_llm_planner: bool = False
) -> PipelineDependencies:
    """Return a copy of ``deps`` with this side's planner and retrievers swapped in.

    Demo/other-group components are left untouched so integration can proceed
    incrementally: replace one side at a time.
    """
    from dataclasses import replace

    components = build_group_b_components(use_llm_planner=use_llm_planner)
    retrievers = list(deps.retrievers)
    ours = [components["crossref"], components["openalex"], components["semantic_scholar"]]
    return replace(
        deps,
        query_planner=components["query_planner"],
        retrievers=ours + retrievers,
    )

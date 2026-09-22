"""Query planner: rewrite a research idea into per-source keyword queries.

Contract notes (ports/contracts.py + docs/API_CONTRACTS.md):
- ``plan`` must not perform network I/O in the DEFAULT assembly; the LLM
  extractor is opt-in and degrades to the heuristic extractor when the LLM
  is unreachable, so ``plan`` never fails because of the extractor.
- Queries are space-separated keywords; source-specific API syntax is each
  retriever's job.
"""

from __future__ import annotations

from typing import Protocol

from paper_agent.adapters._concept_extraction import (
    ExtractedConcepts,
    HeuristicConceptExtractor,
)
from paper_agent.domain.models import (
    PaperSource,
    ResearchIdea,
    SearchPlan,
    SearchQuery,
)

# Sources our group's retrievers implement; the planner emits one query per
# source so each retriever picks exactly its own entry from the plan.
_PLANNED_SOURCES = (
    PaperSource.ARXIV,
    PaperSource.OPENALEX,
    PaperSource.CROSSREF,
    PaperSource.SEMANTIC_SCHOLAR,
)


class ConceptExtractor(Protocol):
    def extract(self, text: str) -> ExtractedConcepts: ...


class HeuristicQueryPlanner:
    """Deterministic planner over an injectable concept extractor.

    Default extractor is offline rule-based. Production assembly may inject
    ``LLMConceptExtractor`` (which itself falls back to rules on failure).
    """

    def __init__(self, concept_extractor: ConceptExtractor | None = None):
        self.concept_extractor = concept_extractor or HeuristicConceptExtractor()

    async def plan(self, idea: ResearchIdea, limit_per_source: int) -> SearchPlan:
        extracted = self.concept_extractor.extract(idea.text)
        concepts = list(extracted.concepts) or ["machine learning"]

        for term in idea.required_terms:
            if term not in concepts:
                concepts.append(term)

        synonyms = list(extracted.synonyms)
        base_query = " ".join(concepts)
        queries = [
            SearchQuery(
                source=source,
                query=base_query,
                limit=limit_per_source,
                filters={"synonyms": synonyms},
            )
            for source in _PLANNED_SOURCES
        ]

        inclusion = [
            "Paper metadata matches at least one core concept of the idea",
            "Title or abstract available in English",
        ]
        if idea.required_terms:
            inclusion.append(f"Contains required terms: {', '.join(idea.required_terms)}")

        exclusion = list(idea.excluded_terms) or [
            "Datasets and benchmarks without methodological contribution",
        ]

        return SearchPlan(
            intent_summary=idea.text,
            queries=queries,
            synonyms=synonyms,
            inclusion_criteria=inclusion,
            exclusion_criteria=exclusion,
        )

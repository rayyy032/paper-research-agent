"""Offline A-to-pipeline contract checks; other groups use explicit test/demo data."""
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from paper_agent.adapters import (
    ArxivRetriever,
    ArxivSearchConfig,
    BibTexMapper,
    PaperMerger,
    build_demo_dependencies,
)
from paper_agent.application.pipeline import ResearchPipeline
from paper_agent.domain.models import (
    PaperSource,
    PipelineRequest,
    ProcessingStatus,
    ResearchIdea,
)


@pytest.mark.asyncio
@pytest.mark.parametrize('arxiv_fails', [False, True])
async def test_a_components_integrate_with_pipeline_and_partial_failure(arxiv_fails):
    class FixtureClient:
        def results(self, search):
            if arxiv_fails:
                raise TimeoutError('offline integration timeout fixture')
            yield SimpleNamespace(
                entry_id='https://arxiv.org/abs/2401.01234v1',
                title='Offline retrieval integration fixture',
                authors=[SimpleNamespace(name='Jane Doe')],
                published=date(2024, 1, 2), doi='10.1000/integration',
                summary='Explicitly synthetic abstract for an offline contract test.',
            )

    class FixtureSecondSource:
        source_name = 'openalex'

        async def search(self, plan):
            assert any(q.source == PaperSource.OPENALEX for q in plan.queries)
            return [await BibTexMapper().to_paper(
                '@misc{fixture,title={Offline retrieval integration fixture},'
                'author={Jane Doe},doi={https://doi.org/10.1000/INTEGRATION}}',
                source='openalex', supplemental_metadata={
                    'source_id': 'offline-openalex-fixture',
                    'abstract': 'Explicitly synthetic abstract for an offline contract test.',
                    'raw_metadata': {'mode': 'offline_fixture'},
                },
            )]

    deps = replace(
        build_demo_dependencies(),
        retrievers=[ArxivRetriever(client=FixtureClient(), config=ArxivSearchConfig(
            delay_seconds=0, max_retries=0)), FixtureSecondSource()],
        merger=PaperMerger(),
    )
    result = await ResearchPipeline(deps).run(PipelineRequest(
        idea=ResearchIdea(text='Offline retrieval integration contract test'),
        top_k=1, pre_rank_pool_size=2,
    ))
    assert result.status == ProcessingStatus.PARTIAL  # explicit abstract-only fallback
    assert len(result.papers) == len(result.summaries) == 1
    assert result.report is not None
    assert result.summaries[0].generated_from_fulltext is False
    assert result.papers[0].doi == '10.1000/integration'
    deduped = next(event for event in result.events if event.stage.value == 'deduped')
    assert (deduped.input_count, deduped.output_count) == (1 if arxiv_fails else 2, 1)
    expected = {PaperSource.OPENALEX} if arxiv_fails else {PaperSource.ARXIV, PaperSource.OPENALEX}
    assert {r.source for r in result.papers[0].source_records} == expected
    assert any('source arxiv failed' in w for w in result.warnings) == arxiv_fails

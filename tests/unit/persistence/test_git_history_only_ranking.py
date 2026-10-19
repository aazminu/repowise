"""The SQL percentile recompute ranks code rows only; history-tier rows read 0."""

from __future__ import annotations

from sqlalchemy import select

from repowise.core.persistence.crud import recompute_git_percentiles, upsert_git_metadata_bulk
from repowise.core.persistence.models import GitMetadata
from tests.unit.persistence.helpers import insert_repo


async def test_sql_recompute_ranks_code_rows_only(async_session) -> None:
    repo = await insert_repo(async_session)
    code = [
        {"file_path": f"m{i}.py", "temporal_hotspot_score": float(i), "commit_count_90d": 9}
        for i in range(4)
    ]
    docs = [
        {"file_path": f"d{i}.md", "history_only": True, "commit_count_90d": 50} for i in range(8)
    ]
    await upsert_git_metadata_bulk(async_session, repo.id, code + docs)
    await recompute_git_percentiles(async_session, repo.id)

    rows = (
        (
            await async_session.execute(
                select(GitMetadata).where(GitMetadata.repository_id == repo.id)
            )
        )
        .scalars()
        .all()
    )
    pct = {r.file_path: r.churn_percentile for r in rows}
    # Ranked among the four code rows alone: 0, 1/3, 2/3, 1.
    assert [round(pct[f"m{i}.py"], 3) for i in range(4)] == [0.0, 0.333, 0.667, 1.0]
    for r in rows:
        if r.history_only:
            assert r.churn_percentile == 0.0
            assert r.is_hotspot is False
            assert r.prior_defect_pct == 0.0


async def test_compute_percentiles_matches_sql_recompute_with_ties(async_session) -> None:
    from repowise.core.ingestion.git_indexer.enrich import compute_percentiles

    repo = await insert_repo(async_session)
    code = [
        {
            "file_path": "f1.py",
            "temporal_hotspot_score": 1.0,
            "commit_count_90d": 2,
            "is_hotspot": False,
        },
        {
            "file_path": "f2.py",
            "temporal_hotspot_score": 10.0,
            "commit_count_90d": 5,
            "is_hotspot": False,
        },
        {
            "file_path": "f3.py",
            "temporal_hotspot_score": 10.0,
            "commit_count_90d": 5,
            "is_hotspot": False,
        },
        {
            "file_path": "f4.py",
            "temporal_hotspot_score": 25.0,
            "commit_count_90d": 10,
            "is_hotspot": False,
        },
        {
            "file_path": "f5.py",
            "temporal_hotspot_score": 50.0,
            "commit_count_90d": 12,
            "is_hotspot": False,
        },
    ]
    compute_percentiles(code)
    in_memory = {m["file_path"]: (m["churn_percentile"], m["is_hotspot"]) for m in code}

    await upsert_git_metadata_bulk(async_session, repo.id, code)
    await recompute_git_percentiles(async_session, repo.id)

    rows = (
        (
            await async_session.execute(
                select(GitMetadata).where(GitMetadata.repository_id == repo.id)
            )
        )
        .scalars()
        .all()
    )
    from_sql = {r.file_path: (r.churn_percentile, r.is_hotspot) for r in rows}
    assert from_sql == in_memory

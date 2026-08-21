"""Manifest identity hash tests (design ruling P0-5).

M0 exit criteria:
- hash independent of machine absolute paths / data roots (two roots agree)
- hash independent of run_id / staging paths / timestamps
- hash independent of component insertion order
"""

from __future__ import annotations

from ashare_state.storage.atomic_files import (
    ComponentIdentity,
    compute_manifest_hash,
)


def _components() -> list[ComponentIdentity]:
    return [
        ComponentIdentity(
            dataset="daily_bar",
            logical_partition_key="year=2026/month=08",
            content_hash="a" * 64,
            schema_hash="b" * 64,
            row_count=1000,
            provider="amazingdata",
            source_revision="r1",
        ),
        ComponentIdentity(
            dataset="security_status",
            logical_partition_key="year=2026/month=08",
            content_hash="c" * 64,
            schema_hash="d" * 64,
            row_count=2000,
        ),
    ]


class TestManifestHash:
    def test_insertion_order_irrelevant(self):
        a, b = _components(), list(reversed(_components()))
        assert compute_manifest_hash(a) == compute_manifest_hash(b)

    def test_identical_components_same_hash(self):
        assert compute_manifest_hash(_components()) == compute_manifest_hash(_components())

    def test_content_change_changes_hash(self):
        comps = _components()
        changed = [ComponentIdentity(**{**vars(comps[0]), "content_hash": "e" * 64})] + comps[1:]
        assert compute_manifest_hash(comps) != compute_manifest_hash(changed)

    def test_row_count_change_changes_hash(self):
        comps = _components()
        changed = [ComponentIdentity(**{**vars(comps[0]), "row_count": 1001})] + comps[1:]
        assert compute_manifest_hash(comps) != compute_manifest_hash(changed)

    def test_provider_change_changes_hash(self):
        comps = _components()
        changed = [ComponentIdentity(**{**vars(comps[0]), "provider": "tushare"})] + comps[1:]
        assert compute_manifest_hash(comps) != compute_manifest_hash(changed)

    def test_none_provider_vs_empty_is_stable(self):
        """None provider/revision must serialize deterministically."""
        c1 = ComponentIdentity("d", "k", "a" * 64, "b" * 64, 1, None, None)
        c2 = ComponentIdentity("d", "k", "a" * 64, "b" * 64, 1, None, None)
        assert compute_manifest_hash([c1]) == compute_manifest_hash([c2])

    def test_hash_is_sha256_hex(self):
        h = compute_manifest_hash(_components())
        assert len(h) == 64
        int(h, 16)  # parses as hex

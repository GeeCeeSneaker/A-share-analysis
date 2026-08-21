"""Cross-root manifest hash consistency (design ruling P0-5 must-test).

The same logical file set registered under two different data roots must
produce the IDENTICAL manifest identity hash. The hash may only depend on
logical fields - never on absolute paths, drive letters or run ids.
"""

from __future__ import annotations

from pathlib import Path

from ashare_state.storage.atomic_files import (
    ComponentIdentity,
    compute_manifest_hash,
    write_file_atomic,
)
from ashare_state.storage.paths import to_logical_uri


def _register_snapshot(data_root: Path, files: dict[str, bytes]) -> str:
    """Write files under data_root and compute the logical manifest hash."""
    components: list[ComponentIdentity] = []
    for relative, payload in files.items():
        final = data_root / relative
        content_hash = write_file_atomic(final, payload)
        components.append(
            ComponentIdentity(
                dataset="daily_bar",
                logical_partition_key=Path(relative).parent.as_posix(),
                content_hash=content_hash,
                schema_hash="schema-v1",
                row_count=payload.count(b"\n"),
                provider="amazingdata",
                source_revision="r1",
            )
        )
    return compute_manifest_hash(components)


class TestCrossRootConsistency:
    FILES = {
        "canonical/daily_bar/year=2026/month=08/part-0001.parquet": b"a\nb\nc\n",
        "canonical/daily_bar/year=2026/month=08/part-0002.parquet": b"d\ne\n",
    }

    def test_same_content_two_roots_same_hash(self, tmp_path: Path):
        # simulate "D:\research\data" vs "E:\temp\another_root": two
        # independent roots with identical logical content
        root_a = tmp_path / "root_a"
        root_b = tmp_path / "deeper" / "nested" / "root_b"
        root_a.mkdir(parents=True)
        root_b.mkdir(parents=True)

        hash_a = _register_snapshot(root_a, self.FILES)
        hash_b = _register_snapshot(root_b, self.FILES)
        assert hash_a == hash_b

    def test_run_id_in_physical_layout_does_not_pollute(self, tmp_path: Path):
        """Staging/run paths live outside the logical identity by construction:
        components carry no path fields at all - assert the dataclass fields."""
        fields = {f for f in ComponentIdentity.__dataclass_fields__}  # noqa: C416
        assert fields == {
            "dataset",
            "logical_partition_key",
            "content_hash",
            "schema_hash",
            "row_count",
            "provider",
            "source_revision",
        }
        # and logical uri derivation ignores the root itself
        root_a = tmp_path / "r1"
        root_b = tmp_path / "r2"
        rel = "x/y.parquet"
        assert to_logical_uri(root_a, root_a / rel) == to_logical_uri(root_b, root_b / rel)

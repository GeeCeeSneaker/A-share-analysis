"""CR-1.2.1 raw commit recovery tests (audit 20260825 section 7).

Interrupted multi-file commits leave ORPHAN payloads (bytes on disk, no
meta anchor). Recovery semantics:
  - same-request retry with SAME bytes    -> commit RECOVERS (meta lands,
    idempotent, closure passes)
  - retry with DIFFERENT bytes            -> orphan QUARANTINED (moved to
    .quarantine/, write BLOCKS, never mistaken for valid evidence)
  - partial orphan set                    -> quarantined, BLOCK
  - fault injection mid-commit            -> no meta anchor, no staging
    residue; a later retry recovers
  - healthy store                         -> list_orphan_payloads() == []
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ashare_state.providers.amazingdata.provider import RawEnvelope
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.storage.raw_writer import (
    RawWriter,
    RawWriterError,
    list_orphan_payloads,
)


def _exchange(request_id: str, payload, dataset: str = "ds"):
    envelope = RawEnvelope(
        provider="amazingdata",
        provider_dataset=dataset,
        endpoint="Test.endpoint",
        request_id=request_id,
        account_profile_id="TRIAL_TEST",
    )
    return ProviderExchange(envelope=envelope, payload=payload)


def _dataset_dir(root: Path, dataset: str = "ds") -> Path:
    return root / "provider=amazingdata" / f"dataset={dataset}"


class TestOrphanRecovery:
    def test_interrupted_commit_same_bytes_retry_recovers(self, tmp_path: Path):
        """Orphan single-table payload + retry with the SAME bytes: the
        meta lands (commit recovered) and the result is idempotent."""
        writer = RawWriter(tmp_path)
        # stage 1: payload bytes exist, meta deliberately missing
        writer.write(_exchange("rec1", [{"a": 1}]))
        dataset_dir = _dataset_dir(tmp_path)
        (dataset_dir / "rec1.meta.json").unlink()  # simulate interruption
        assert list_orphan_payloads(tmp_path) == ["provider=amazingdata/dataset=ds/rec1.parquet"]
        # stage 2: retry with the same payload -> recovery
        retried = writer.write(_exchange("rec1", [{"a": 1}]))
        assert retried.idempotent is True
        assert (dataset_dir / "rec1.meta.json").is_file()
        assert list_orphan_payloads(tmp_path) == []
        # the closure now verifies end-to-end
        assert writer.read(provider="amazingdata", dataset="ds", request_id="rec1").get_column(
            "a"
        ).to_list() == [1]

    def test_orphan_different_bytes_retry_quarantines(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        writer.write(_exchange("q1", [{"a": 1}]))
        dataset_dir = _dataset_dir(tmp_path)
        (dataset_dir / "q1.meta.json").unlink()
        with pytest.raises(RawWriterError, match="quarantine"):
            writer.write(_exchange("q1", [{"a": 999}]))
        # the orphan was moved under .quarantine (inspectable, not valid)
        assert not (dataset_dir / "q1.parquet").is_file()
        quarantine = dataset_dir / ".quarantine"
        quarantined = list(quarantine.glob("q1-*.parquet"))
        assert len(quarantined) == 1
        assert list_orphan_payloads(tmp_path) == []

    def test_partial_orphan_set_quarantined(self, tmp_path: Path):
        """Multi-table commit interrupted after the first table: a retry
        with DIFFERENT bytes can NEVER complete the set (quarantined).
        (The same-bytes partial retry now RECOVERS - see
        TestPartialOrphanSets, R4-A2.6 P1-03.)"""
        writer = RawWriter(tmp_path)
        writer.write(_exchange("p1", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        dataset_dir = _dataset_dir(tmp_path)
        (dataset_dir / "p1.meta.json").unlink()
        (dataset_dir / "p1" / "t2.parquet").unlink()  # partial orphan
        orphans = list_orphan_payloads(tmp_path)
        assert orphans == ["provider=amazingdata/dataset=ds/p1/t1.parquet"]
        with pytest.raises(RawWriterError, match="quarantine"):
            writer.write(_exchange("p1", {"t1": [{"a": 999}], "t2": [{"b": 2}]}))
        assert not (dataset_dir / "p1").exists()

    def test_orphan_recovery_multi_table_completes(self, tmp_path: Path):
        """Full multi-table orphan set + same bytes retry -> recovered."""
        writer = RawWriter(tmp_path)
        writer.write(_exchange("m1", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        dataset_dir = _dataset_dir(tmp_path)
        (dataset_dir / "m1.meta.json").unlink()
        assert len(list_orphan_payloads(tmp_path)) == 2
        retried = writer.write(_exchange("m1", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        assert retried.idempotent is True
        assert (dataset_dir / "m1.meta.json").is_file()
        assert list_orphan_payloads(tmp_path) == []


class TestFaultInjection:
    def test_meta_write_failure_leaves_no_anchor_and_recovers(self, tmp_path, monkeypatch):
        """Inject a failure at the meta-write step: no meta anchor lands,
        no staging residue; a later same-bytes retry completes the commit."""
        from ashare_state.storage import raw_writer as rw

        writer = RawWriter(tmp_path)
        original = rw.write_file_atomic
        state = {"failed": False}

        def flaky_write(path: Path, data: bytes, **kwargs):
            if str(path).endswith(".meta.json") and not state["failed"]:
                state["failed"] = True
                raise OSError("injected meta write failure")
            return original(path, data, **kwargs)

        monkeypatch.setattr(rw, "write_file_atomic", flaky_write)
        with pytest.raises(OSError, match="injected"):
            writer.write(_exchange("f1", [{"a": 1}]))
        monkeypatch.setattr(rw, "write_file_atomic", original)
        dataset_dir = _dataset_dir(tmp_path)
        # payload bytes landed; the meta (anchor) did NOT
        assert (dataset_dir / "f1.parquet").is_file()
        assert not (dataset_dir / "f1.meta.json").is_file()
        assert list_orphan_payloads(tmp_path) == ["provider=amazingdata/dataset=ds/f1.parquet"]
        # no staging residue
        assert not [p for p in dataset_dir.iterdir() if p.name.startswith(".staging")]
        # retry recovers the commit
        recovered = writer.write(_exchange("f1", [{"a": 1}]))
        assert recovered.idempotent is True
        assert (dataset_dir / "f1.meta.json").is_file()

    def test_payload_move_failure_leaves_no_meta(self, tmp_path, monkeypatch):
        """Failure during the payload-move phase: NOTHING valid lands (the
        meta is written LAST, so no meta-anchored partial set can exist)."""
        import os as os_mod

        from ashare_state.storage import raw_writer as rw

        writer = RawWriter(tmp_path)
        original_replace = os_mod.replace

        def failing_replace(src, dst, *args, **kwargs):
            if str(dst).endswith(".parquet"):
                raise OSError("injected payload move failure")
            return original_replace(src, dst, *args, **kwargs)

        monkeypatch.setattr(rw.os, "replace", failing_replace)
        with pytest.raises(OSError, match="injected"):
            writer.write(_exchange("f2", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        monkeypatch.undo()
        dataset_dir = _dataset_dir(tmp_path)
        assert not (dataset_dir / "f2.meta.json").exists()
        assert list_orphan_payloads(tmp_path) == []


class TestHealthyStore:
    def test_no_orphans_after_normal_writes(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        writer.write(_exchange("ok1", [{"a": 1}]))
        writer.write(_exchange("ok2", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        writer.write(_exchange("ok3", None, dataset="other"))
        assert list_orphan_payloads(tmp_path) == []

    def test_missing_root_returns_empty(self, tmp_path: Path):
        assert list_orphan_payloads(tmp_path / "nope") == []


class TestPartialOrphanSets:
    """R4-A2.6 P1-03 (audit 20260825 #2 section 8): multi-table orphan
    SET semantics."""

    def test_partial_orphan_same_retry_completes_with_meta(self, tmp_path: Path):
        """Existing t1 + missing t2 + same-bytes retry: the retry writes
        the missing member AND the meta anchor (full recovery)."""
        writer = RawWriter(tmp_path)
        writer.write(_exchange("po1", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        dataset_dir = _dataset_dir(tmp_path)
        (dataset_dir / "po1.meta.json").unlink()
        (dataset_dir / "po1" / "t2.parquet").unlink()  # partial orphan set
        assert list_orphan_payloads(tmp_path) == ["provider=amazingdata/dataset=ds/po1/t1.parquet"]
        recovered = writer.write(_exchange("po1", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        assert recovered.idempotent is True
        assert (dataset_dir / "po1" / "t1.parquet").is_file()
        assert (dataset_dir / "po1" / "t2.parquet").is_file()
        assert (dataset_dir / "po1.meta.json").is_file()
        assert list_orphan_payloads(tmp_path) == []
        # recovered exchange passes the FULL evidence closure
        frame = writer.read(provider="amazingdata", dataset="ds", request_id="po1")
        assert frame["t1"].get_column("a").to_list() == [1]
        assert frame["t2"].get_column("b").to_list() == [2]

    def test_orphan_with_unexpected_extra_member_quarantines(self, tmp_path: Path):
        """An orphan request dir containing an EXTRA table the retry does
        NOT declare: the set is not the retry's set -> quarantine + BLOCK
        (never adopt unknown bytes as evidence)."""
        writer = RawWriter(tmp_path)
        writer.write(_exchange("px1", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        dataset_dir = _dataset_dir(tmp_path)
        (dataset_dir / "px1.meta.json").unlink()
        # plant an unexpected member the retry does not know about
        (dataset_dir / "px1" / "t3.parquet").write_bytes(b"unexpected bytes")
        with pytest.raises(RawWriterError, match="quarantine"):
            writer.write(_exchange("px1", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        # the whole orphan set moved to quarantine; nothing active remains
        assert not (dataset_dir / "px1").exists()
        quarantine = dataset_dir / ".quarantine"
        quarantined = sorted(p.name for p in quarantine.glob("px1-*"))
        assert len(quarantined) == 3  # t1 + t2 + the unexpected t3
        assert list_orphan_payloads(tmp_path) == []

    def test_quarantined_bytes_are_not_active_orphans(self, tmp_path: Path):
        """After quarantine, list_orphan_payloads() reports NOTHING (the
        quarantined bytes live under .quarantine/, excluded from the
        active scan)."""
        writer = RawWriter(tmp_path)
        writer.write(_exchange("qz1", [{"a": 1}]))
        dataset_dir = _dataset_dir(tmp_path)
        (dataset_dir / "qz1.meta.json").unlink()
        with pytest.raises(RawWriterError, match="quarantine"):
            writer.write(_exchange("qz1", [{"a": 2}]))
        assert list_orphan_payloads(tmp_path) == []
        quarantine_files = list((dataset_dir / ".quarantine").glob("*"))
        assert quarantine_files  # the bytes remain inspectable for forensics

    def test_recovered_exchange_passes_meta_closure(self, tmp_path: Path):
        """After a same-bytes recovery, verify_meta_closure is clean."""
        from ashare_state.storage.raw_writer import verify_meta_closure

        writer = RawWriter(tmp_path)
        writer.write(_exchange("rc1", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        dataset_dir = _dataset_dir(tmp_path)
        (dataset_dir / "rc1.meta.json").unlink()
        writer.write(_exchange("rc1", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        meta = json.loads((dataset_dir / "rc1.meta.json").read_text(encoding="utf-8"))
        assert verify_meta_closure(dataset_dir, meta) == []

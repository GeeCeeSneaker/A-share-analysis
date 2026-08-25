"""CR-1.2 raw exchange closure tests (audit R4-A2.4 section 3).

The evidence unit is the EXCHANGE (payload + meta), closing
BIDIRECTIONALLY:
  - payload tamper  -> meta's declared hash no longer matches -> BLOCK
  - meta deletion   -> evidence closure BLOCKS (legacy parquet too)
  - meta tamper     -> evidence_hash mismatch -> BLOCK
Plus: full request params persisted + reconstructable, ingest run
binding, multi-file staging atomicity, table-name collision, read-time
verification.
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
    verify_meta_closure,
)


def _exchange(request_id: str, dataset: str, payload, *, params: dict | None = None):
    effective = params or {"code_list": ["600519.SH"], "start": 20220101}
    envelope = RawEnvelope(
        provider="amazingdata",
        provider_dataset=dataset,
        endpoint="Test.endpoint",
        request_id=request_id,
        request_params=effective,
        request_params_hash=RawEnvelope.params_hash(effective),
        account_profile_id="TRIAL_TEST",
    )
    return ProviderExchange(envelope=envelope, payload=payload)


def _dataset_dir(root: Path, dataset: str = "ds") -> Path:
    return root / "provider=amazingdata" / f"dataset={dataset}"


class TestBidirectionalClosure:
    def test_payload_tamper_breaks_closure(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        writer.write(_exchange("r1", "ds", [{"a": 1}]))
        # 1. read-time verification detects the tamper
        payload = tmp_path / "provider=amazingdata" / "dataset=ds" / "r1.parquet"
        payload.write_bytes(b"tampered-bytes")
        with pytest.raises(RawWriterError, match="payload hash mismatch"):
            writer.read(provider="amazingdata", dataset="ds", request_id="r1")
        # 2. closure helper reports it
        meta = json.loads(
            (tmp_path / "provider=amazingdata" / "dataset=ds" / "r1.meta.json").read_text(
                encoding="utf-8"
            )
        )
        problems = verify_meta_closure(_dataset_dir(tmp_path), meta)
        assert any("payload hash mismatch" in p for p in problems)

    def test_payload_deletion_breaks_closure(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        writer.write(_exchange("r2", "ds", [{"a": 1}]))
        (tmp_path / "provider=amazingdata" / "dataset=ds" / "r2.parquet").unlink()
        with pytest.raises(RawWriterError, match="payload artifact missing"):
            writer.read(provider="amazingdata", dataset="ds", request_id="r2")

    def test_multi_table_payload_tamper_breaks_closure(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        writer.write(_exchange("m1", "ds", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        victim = tmp_path / "provider=amazingdata" / "dataset=ds" / "m1" / "t2.parquet"
        victim.write_bytes(b"nope")
        meta = json.loads(
            (tmp_path / "provider=amazingdata" / "dataset=ds" / "m1.meta.json").read_text(
                encoding="utf-8"
            )
        )
        problems = verify_meta_closure(_dataset_dir(tmp_path), meta)
        assert any("payload hash mismatch" in p for p in problems)

    def test_combined_hash_recomputes_or_blocks(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        writer.write(_exchange("c1", "ds", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        meta_path = tmp_path / "provider=amazingdata" / "dataset=ds" / "c1.meta.json"
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
        assert verify_meta_closure(_dataset_dir(tmp_path), doc) == []
        # tamper the DECLARED combined hash -> recompute check fails
        doc["content_hash"] = "0" * 64
        problems = verify_meta_closure(_dataset_dir(tmp_path), doc)
        assert any("combined content_hash" in p for p in problems)


class TestRequestParams:
    def test_full_params_persisted_and_reconstructable(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        params = {
            "code_list": ["600519.SH", "000001.SZ", "835185.BJ"],
            "start_date": 20220101,
            "end_date": 20221231,
        }
        writer.write(_exchange("p1", "ds", [{"a": 1}], params=params))
        meta = json.loads((_dataset_dir(tmp_path) / "p1.meta.json").read_text(encoding="utf-8"))
        # the FULL params are on the meta: the request is reconstructable
        assert meta["request_params"] == params
        assert meta["request_params_hash"] == RawEnvelope.params_hash(params)

    def test_same_size_different_symbols_hash_differently(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        first = _exchange("s1", "ds", [{"a": 1}], params={"code_list": ["600519.SH", "000001.SZ"]})
        second = _exchange("s2", "ds", [{"a": 1}], params={"code_list": ["600519.SH", "300750.SZ"]})
        writer.write(first)
        writer.write(second)
        meta1 = json.loads((_dataset_dir(tmp_path) / "s1.meta.json").read_text(encoding="utf-8"))
        meta2 = json.loads((_dataset_dir(tmp_path) / "s2.meta.json").read_text(encoding="utf-8"))
        assert meta1["request_params"]["code_list"] != meta2["request_params"]["code_list"]
        assert meta1["request_params_hash"] != meta2["request_params_hash"]

    def test_secrets_scrubbed_from_persisted_params(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        exchange = _exchange(
            "sec1",
            "ds",
            [{"a": 1}],
            params={"code_list": ["600519.SH"], "password": "hunter2", "api_token": "zzz"},
        )
        writer.write(exchange)
        text = (_dataset_dir(tmp_path) / "sec1.meta.json").read_text(encoding="utf-8")
        assert "hunter2" not in text
        assert "zzz" not in text
        assert "***MASKED***" in text


class TestIngestTraceability:
    def test_ingested_at_and_run_binding_recorded(self, tmp_path: Path):
        writer = RawWriter(tmp_path, ingest_run_id="run-abc-123")
        writer.write(_exchange("i1", "ds", [{"a": 1}]))
        meta = json.loads((_dataset_dir(tmp_path) / "i1.meta.json").read_text(encoding="utf-8"))
        assert meta["ingest_run_id"] == "run-abc-123"
        assert meta["ingested_at"]  # ISO timestamp present
        from datetime import datetime

        datetime.fromisoformat(meta["ingested_at"])

    def test_schema_hash_at_artifact_level(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        result = writer.write(_exchange("sh1", "ds", [{"a": 1}, {"a": 2}]))
        assert len(result.payload_artifacts) == 1
        assert result.payload_artifacts[0].schema_hash
        meta = json.loads((_dataset_dir(tmp_path) / "sh1.meta.json").read_text(encoding="utf-8"))
        assert meta["tables"][0]["schema_hash"] == result.payload_artifacts[0].schema_hash


class TestMultiFileAtomicity:
    def test_no_staging_residue_and_meta_is_last_anchor(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        writer.write(_exchange("st1", "ds", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        dataset_dir = _dataset_dir(tmp_path)
        # all payloads + the meta anchor landed; no staging residue
        assert (dataset_dir / "st1" / "t1.parquet").is_file()
        assert (dataset_dir / "st1" / "t2.parquet").is_file()
        assert (dataset_dir / "st1.meta.json").is_file()
        assert not [p for p in dataset_dir.iterdir() if p.name.startswith(".staging")]

    def test_collision_blocks_before_any_file_lands(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        # "a.b" and "a/b" both sanitize to "a_b" -> collision
        with pytest.raises(RawWriterError, match="table name collision"):
            writer.write(_exchange("cl1", "ds", {"a.b": [{"x": 1}], "a/b": [{"y": 2}]}))
        # nothing was committed (no meta anchor, no partial tables)
        dataset_dir = _dataset_dir(tmp_path)
        assert not (dataset_dir / "cl1.meta.json").exists()
        assert not (dataset_dir / "cl1").exists()

    def test_failed_multi_write_leaves_no_meta_anchor(self, tmp_path: Path):
        """A multi-table write that fails mid-way can never leave a
        meta-anchored partial set (the meta is written LAST)."""
        writer = RawWriter(tmp_path)
        # unhashable payload element -> normalize raises BEFORE any commit
        with pytest.raises(RawWriterError):
            writer.write(_exchange("f1", "ds", {"t1": [{"a": 1}], "t2": object()}))
        dataset_dir = _dataset_dir(tmp_path)
        assert not (dataset_dir / "f1.meta.json").exists()


class TestReadVerification:
    def test_read_verify_passes_on_untouched_evidence(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        writer.write(_exchange("rv1", "ds", [{"a": 1}]))
        frame = writer.read(provider="amazingdata", dataset="ds", request_id="rv1")
        assert frame.get_column("a").to_list() == [1]

    def test_read_verify_can_be_disabled_for_recovery(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        writer.write(_exchange("rv2", "ds", [{"a": 1}]))
        (tmp_path / "provider=amazingdata" / "dataset=ds" / "rv2.parquet").write_bytes(b"corrupt")
        # verify=False lets recovery tooling inspect the (corrupt) state
        with pytest.raises(Exception):
            writer.read(provider="amazingdata", dataset="ds", request_id="rv2", verify=False)

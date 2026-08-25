"""R4-A2.7 P0-02: Raw evidence identity tests (audit 20260825 #3 section 3).

The returned RawWriteResult must describe the PERSISTED evidence, not an
unpersisted candidate serialization: on an idempotent retry the disk keeps
the FIRST commit's meta (with its own ingested_at), so hashing the fresh
in-memory meta_bytes would bind callers to a hash that evidence closure
can never reproduce.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ashare_state.providers.amazingdata.provider import RawEnvelope
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.storage.raw_writer import RawWriter


def _exchange(request_id: str, payload, dataset: str = "ds"):
    envelope = RawEnvelope(
        provider="amazingdata",
        provider_dataset=dataset,
        endpoint="Test.endpoint",
        request_id=request_id,
        account_profile_id="TRIAL_TEST",
    )
    return ProviderExchange(envelope=envelope, payload=payload)


def _meta_path(root: Path, request_id: str, dataset: str = "ds") -> Path:
    return root / "provider=amazingdata" / f"dataset={dataset}" / f"{request_id}.meta.json"


class TestIdempotentIdentity:
    def test_second_write_returns_persisted_meta_hash(self, tmp_path: Path):
        """The core regression: write the same exchange twice; the SECOND
        (idempotent) result must carry sha256 of the ACTUAL on-disk meta
        bytes - which contain the FIRST commit's ingested_at, not the
        second serialization's."""
        writer = RawWriter(tmp_path)
        first = writer.write(_exchange("idem1", [{"a": 1}]))
        second = writer.write(_exchange("idem1", [{"a": 1}]))
        assert first.idempotent is False
        assert second.idempotent is True
        on_disk = _meta_path(tmp_path, "idem1").read_bytes()
        actual_hash = hashlib.sha256(on_disk).hexdigest()
        assert second.evidence_hash == actual_hash
        assert second.meta_artifact is not None
        assert second.meta_artifact.content_hash == actual_hash
        # the fresh serialization WOULD have differed (different ingested_at
        # wall clock is not guaranteed within one test - assert the identity
        # equals the file, which is the contract)
        assert second.evidence_hash == first.evidence_hash

    def test_single_table_idempotent_retry_supports_case_closure(self, tmp_path: Path):
        """A SpikeCase bound to the RETRY result must survive evidence
        closure (hash re-verification over the real file)."""
        writer = RawWriter(tmp_path)
        writer.write(_exchange("cl1", [{"a": 1}]))
        second = writer.write(_exchange("cl1", [{"a": 1}]))
        meta_file = _meta_path(tmp_path, "cl1")
        assert meta_file.is_file()
        assert hashlib.sha256(meta_file.read_bytes()).hexdigest() == second.evidence_hash

    def test_multi_table_idempotent_retry_supports_case_closure(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        writer.write(_exchange("cl2", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        second = writer.write(_exchange("cl2", {"t1": [{"a": 1}], "t2": [{"b": 2}]}))
        meta_file = _meta_path(tmp_path, "cl2")
        assert hashlib.sha256(meta_file.read_bytes()).hexdigest() == second.evidence_hash

    def test_failure_idempotent_retry_identity(self, tmp_path: Path):
        """Failure idempotency keeps returning the persisted failure-meta
        hash (existing behavior must not regress)."""
        env = RawEnvelope(
            provider="amazingdata",
            provider_dataset="ds",
            endpoint="Test.endpoint",
            request_id="ferr",
            status="ERROR",
            error_class="ProviderTestError",
            account_profile_id="TRIAL_TEST",
        )
        exchange = ProviderExchange(envelope=env, payload=None)
        first = writer = None
        writer = RawWriter(tmp_path)
        first = writer.write(exchange)
        second = writer.write(exchange)
        assert first.idempotent is False
        assert second.idempotent is True
        on_disk = _meta_path(tmp_path, "ferr").read_bytes()
        assert second.evidence_hash == hashlib.sha256(on_disk).hexdigest()

    def test_orphan_recovery_retry_returns_persisted_hash(self, tmp_path: Path):
        """Orphan-recovery (meta deleted, same-bytes retry): the returned
        hash is the hash of the meta that the recovery JUST persisted."""
        writer = RawWriter(tmp_path)
        writer.write(_exchange("orph1", [{"a": 1}]))
        _meta_path(tmp_path, "orph1").unlink()
        recovered = writer.write(_exchange("orph1", [{"a": 1}]))
        assert recovered.idempotent is True
        on_disk = _meta_path(tmp_path, "orph1").read_bytes()
        assert recovered.evidence_hash == hashlib.sha256(on_disk).hexdigest()

    def test_fresh_commit_asserts_persisted_equals_intended(self, tmp_path: Path):
        """A fresh (non-idempotent) commit verifies the persisted bytes are
        exactly the intended serialization."""
        writer = RawWriter(tmp_path)
        result = writer.write(_exchange("fresh1", [{"a": 1}]))
        on_disk = _meta_path(tmp_path, "fresh1").read_bytes()
        assert result.evidence_hash == hashlib.sha256(on_disk).hexdigest()

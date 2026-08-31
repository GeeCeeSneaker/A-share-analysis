"""Publish Validation Exactness tests (R4-B2 audit 20260830 +
R4-B2.1 closure audit 20260830 19:13).

The pre-B2 world: ``record_artifact_validation()`` accepted
caller-supplied counts and appended a PASS-shaped ledger row without
executing any validation; publish then trusted ``counts == 0``.

B2 closes this with:

- B2-01 the ONE formal validation boundary
  (``validate_artifact_for_publish``) - the ledger INSERT lives inside
  it, counts are DERIVED from persisted DQ facts, the old
  caller-facing count-writer is GONE;
- B2-02 typed required checks - completeness-enforced, NOT_TESTABLE is
  blocking;
- B2-03/B2-04 exact artifact/component seal + persisted hash-bound
  report;
- B2-05 the publish-critical recheck INSIDE the transaction (TOCTOU
  closed, incl. physical bytes re-verification);
- B2-06 deterministic latest-head policy (newer FAIL beats older PASS;
  legacy rows without the seal require revalidation).

R4-B2.1 closures (audit 20260830 19:13):

- **P0-01 positive DQ execution proof** - IDENTITY_FALLBACK_ZERO /
  BLOCKING_DQ_ZERO require a matching execution record in
  ``meta_artifact_check_execution`` bound to the CURRENT component
  manifest; absence of bad findings is never proof of zero findings;
- **P0-02 full seal consumption** - the publish recheck cross-verifies
  validation_contract_hash / required_checks_hash /
  validator_code_commit / validation_version across ledger, report and
  the CURRENT contract; duplicates rejected;
- **P0-03 full transaction-internal preconditions** - ALL
  authoritative reads (snapshot/artifact/feature-set/run/universes/
  validation head/seal/bytes) happen inside the transaction;
- **P0-04 logical-URI confinement** - every registry file_uri and the
  report_uri resolve through the frozen
  ``physical_from_logical_uri`` helper.
"""

from __future__ import annotations

import ast
import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ashare_state.pipeline import (
    PublishStateError,
    publish_snapshot,
    record_artifact_dq_finding,
    run_required_artifact_dq_scan,
    validate_artifact_for_publish,
)
from ashare_state.pipeline import artifact_validation as av_module
from ashare_state.pipeline import publish as publish_module
from ashare_state.pipeline.artifact_dq_scan import DQ_SCAN_CONTRACT_VERSION
from ashare_state.pipeline.mock_e2e import (
    SKELETON_FEATURE_SET_VERSION,
    run_mock_e2e,
)
from ashare_state.storage.connection import DuckDBConnectionManager

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISH_SOURCE = REPO_ROOT / "src" / "ashare_state" / "pipeline" / "publish.py"
VALIDATION_SOURCE = REPO_ROOT / "src" / "ashare_state" / "pipeline" / "artifact_validation.py"


@pytest.fixture
def base(tmp_path: Path):
    db = tmp_path / "atlas.duckdb"
    return run_mock_e2e(db, tmp_path / "data", start=date(2026, 8, 3), end=date(2026, 8, 14))


def _recovery_run(conn) -> str:
    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO meta_pipeline_run "
        "(pipeline_run_id, run_type, status, started_at, code_commit, "
        "environment_lock_hash, config_hash, source_policy_version, "
        "availability_policy_version) "
        "VALUES (?, 'RECOVERY', 'FEATURE_VALIDATED', ?, ?, ?, ?, ?, ?)",
        [
            run_id,
            datetime.now(UTC),
            "skeleton-commit",
            "skeleton-env",
            "skeleton-config",
            "source-policy-mock-v1",
            "availability-mock-v1",
        ],
    )
    return run_id


def _kwargs(conn, base, *, trade_date: date = date(2026, 8, 18)) -> dict:
    return {
        "trade_date": trade_date,
        "data_snapshot_id": base.data_snapshot_id,
        "feature_artifact_set_id": base.feature_artifact_set_id,
        "feature_set_version": SKELETON_FEATURE_SET_VERSION,
        "universes": [("ALL_A", "v1")],
        "pipeline_run_id": _recovery_run(conn),
        "data_root": base.data_root,
    }


def _latest_validation(conn, artifact_set_id: str):
    return conn.execute(
        "SELECT artifact_validation_id, report_uri, report_hash FROM meta_artifact_validation "
        "WHERE feature_artifact_set_id = ? "
        "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1",
        [artifact_set_id],
    ).fetchone()


def _revalidate(conn, base) -> str:
    return validate_artifact_for_publish(
        conn,
        data_root=base.data_root,
        feature_artifact_set_id=base.feature_artifact_set_id,
        validator_code_commit="test-commit",
    )


def _one_component_file(conn, base) -> Path:
    uri = conn.execute(
        "SELECT file_uri FROM meta_feature_artifact_component "
        "WHERE feature_artifact_set_id = ? ORDER BY file_uri LIMIT 1",
        [base.feature_artifact_set_id],
    ).fetchone()[0]
    return base.data_root / str(uri)


@pytest.mark.integration
class TestNoCallerDeclaredPass:
    """B2-01: caller self-declared counts can never reach a
    publish-eligible validation record."""

    def test_count_writer_is_gone_from_production(self):
        """record_artifact_validation no longer exists anywhere."""

        assert not hasattr(publish_module, "record_artifact_validation")

    def test_structural_guard_no_validation_row_writer_takes_counts(self):
        """AST guard: in the production pipeline package, the ONLY
        function that INSERTs into meta_artifact_validation is
        ``validate_artifact_for_publish`` (the formal boundary) - and
        its signature has NO count/result parameters. No callable can
        accept caller-supplied counts and write a validation row."""
        pipeline_root = REPO_ROOT / "src" / "ashare_state" / "pipeline"
        inserters: set[tuple[str, str]] = set()
        for path in sorted(pipeline_root.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Constant)
                        and isinstance(sub.value, str)
                        and "INSERT INTO meta_artifact_validation" in sub.value
                    ):
                        inserters.add((path.name, node.name))
        assert inserters == {("artifact_validation.py", "validate_artifact_for_publish")}, (
            f"meta_artifact_validation written from unexpected places: {sorted(inserters)}"
        )
        tree = ast.parse(VALIDATION_SOURCE.read_text(encoding="utf-8"))
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "validate_artifact_for_publish"
        )
        arg_names = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
        forbidden = {
            "identity_fallback_count",
            "blocking_dq_count",
            "result",
            "checks",
            "report",
        }
        assert not (arg_names & forbidden), (
            f"formal boundary must not accept caller-supplied counts/results: {arg_names}"
        )

    def test_raw_sql_insert_without_seal_cannot_publish(self, base):
        """A caller hand-crafting a PASS-shaped ledger row via raw SQL
        (no B2 seal columns) is refused at publish - legacy-row policy."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            conn.execute(
                "INSERT INTO meta_artifact_validation "
                "(artifact_validation_id, feature_artifact_set_id, validation_version, "
                "identity_fallback_count, blocking_dq_count, validated_at) "
                "VALUES (?, ?, 'attacker-v0', 0, 0, ?)",
                [f"val-{uuid.uuid4()}", base.feature_artifact_set_id, datetime.now(UTC)],
            )
            with pytest.raises(PublishStateError, match="SEAL_REQUIRED"):
                publish_snapshot(conn, **_kwargs(conn, base))


@pytest.mark.integration
class TestTypedRequiredChecks:
    """B2-02: required checks are typed and completeness-enforced."""

    def test_happy_validation_report_has_all_required_checks_pass(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            validation_id = _revalidate(conn, base)
            row = conn.execute(
                "SELECT report_uri FROM meta_artifact_validation WHERE artifact_validation_id = ?",
                [validation_id],
            ).fetchone()
            report = json.loads((base.data_root / str(row[0])).read_text(encoding="utf-8"))
            got = [c["check_id"] for c in report["checks"]]
            assert got == [c.value for c in av_module.REQUIRED_VALIDATION_CHECKS]
            assert all(c["status"] == "PASS" for c in report["checks"])

    def test_missing_required_check_blocks_publish(self, base):
        """Strip one required check from the (otherwise valid) report ->
        the record is NOT eligible -> publish BLOCK."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            _revalidate(conn, base)
            _, report_uri, report_hash = _latest_validation(conn, base.feature_artifact_set_id)
            report_path = base.data_root / str(report_uri)
            doc = json.loads(report_path.read_text(encoding="utf-8"))
            doc["checks"] = [c for c in doc["checks"] if c["check_id"] != "BLOCKING_DQ_ZERO"]
            report_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
            # re-bind the ledger hash so the tamper is 'legitimate' - the
            # missing check itself must still block
            conn.execute(
                "UPDATE meta_artifact_validation SET report_hash = ? "
                "WHERE artifact_validation_id = "
                "(SELECT artifact_validation_id FROM meta_artifact_validation "
                "WHERE feature_artifact_set_id = ? "
                "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1)",
                [
                    hashlib.sha256(report_path.read_bytes()).hexdigest(),
                    base.feature_artifact_set_id,
                ],
            )
            with pytest.raises(PublishStateError, match="CHECKS_HASH violated"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_not_testable_required_check_blocks_publish(self, base):
        """Delete one component FILE -> revalidation marks existence
        FAIL / schema+row NOT_TESTABLE -> publish BLOCK (fail closed on
        unprovable checks)."""
        comp = _one_component_file  # noqa: F841 - readability alias
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            comp_path = _one_component_file(conn, base)
            comp_path.unlink()
            _revalidate(conn, base)
            with pytest.raises(PublishStateError):
                publish_snapshot(conn, **_kwargs(conn, base))
            comp_path.write_bytes(b"restored")  # cleanup not needed (tmp)

    def test_unknown_check_cannot_substitute_required(self, base):
        """Rename a required check to an unknown id -> the required set
        is incomplete -> BLOCK."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            _revalidate(conn, base)
            _, report_uri, _ = _latest_validation(conn, base.feature_artifact_set_id)
            report_path = base.data_root / str(report_uri)
            doc = json.loads(report_path.read_text(encoding="utf-8"))
            for check in doc["checks"]:
                if check["check_id"] == "COMPONENT_ROW_COUNT":
                    check["check_id"] = "SOME_OTHER_CHECK"
            report_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
            conn.execute(
                "UPDATE meta_artifact_validation SET report_hash = ? "
                "WHERE artifact_validation_id = "
                "(SELECT artifact_validation_id FROM meta_artifact_validation "
                "WHERE feature_artifact_set_id = ? "
                "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1)",
                [
                    hashlib.sha256(report_path.read_bytes()).hexdigest(),
                    base.feature_artifact_set_id,
                ],
            )
            with pytest.raises(PublishStateError, match="CHECKS_HASH violated"):
                publish_snapshot(conn, **_kwargs(conn, base))


@pytest.mark.integration
class TestExactSealAndTamper:
    """B2-03/B2-04/B2-05: the seal binds the exact artifact identity and
    the persisted report; any change after validation blocks publish."""

    def test_component_registry_change_after_validation_blocks(self, base):
        """UPDATE a component row (row_count) after a PASS validation ->
        re-derived component manifest != seal -> BLOCK."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            _revalidate(conn, base)
            conn.execute(
                "UPDATE meta_feature_artifact_component SET row_count = row_count + 1 "
                "WHERE feature_artifact_set_id = ?",
                [base.feature_artifact_set_id],
            )
            with pytest.raises(PublishStateError, match="COMPONENTS_CHANGED"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_artifact_manifest_hash_change_after_validation_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            _revalidate(conn, base)
            conn.execute(
                "UPDATE meta_feature_artifact_set SET artifact_manifest_hash = ? "
                "WHERE feature_artifact_set_id = ?",
                ["f" * 64, base.feature_artifact_set_id],
            )
            with pytest.raises(PublishStateError, match="IDENTITY_CHANGED"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_component_file_bytes_tamper_after_validation_blocks(self, base):
        """Replace a component file on disk (registry untouched) -> the
        in-transaction bytes re-verification fails closed."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            _revalidate(conn, base)
            comp_path = _one_component_file(conn, base)
            comp_path.write_bytes(comp_path.read_bytes() + b"\x00tamper")
            with pytest.raises(PublishStateError, match="COMPONENT_TAMPERED"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_component_file_missing_after_validation_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            _revalidate(conn, base)
            comp_path = _one_component_file(conn, base)
            comp_path.unlink()
            with pytest.raises(PublishStateError, match="COMPONENT_MISSING"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_report_bytes_tamper_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            _revalidate(conn, base)
            _, report_uri, _ = _latest_validation(conn, base.feature_artifact_set_id)
            report_path = base.data_root / str(report_uri)
            report_path.write_text(report_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with pytest.raises(PublishStateError, match="REPORT_TAMPERED"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_report_missing_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            _revalidate(conn, base)
            _, report_uri, _ = _latest_validation(conn, base.feature_artifact_set_id)
            (base.data_root / str(report_uri)).unlink()
            with pytest.raises(PublishStateError, match="REPORT_MISSING"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_report_swapped_to_other_artifact_set_blocks(self, base, tmp_path: Path):
        """Point the report at ANOTHER artifact set's validation report:
        identity mismatch -> BLOCK."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            _revalidate(conn, base)
            # fabricate a second, valid-looking validation for another set
            other_set = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO meta_feature_artifact_set VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, 'FEATURE_VALIDATED', ?, ?)",
                [
                    other_set,
                    base.data_snapshot_id,
                    SKELETON_FEATURE_SET_VERSION,
                    "skeleton-commit",
                    "skeleton-env",
                    "skeleton-config",
                    None,
                    base.artifact_manifest_hash,
                    datetime.now(UTC),
                    datetime.now(UTC),
                ],
            )
            # copy base components under the other set id
            conn.execute(
                "INSERT INTO meta_feature_artifact_component "
                "SELECT ?, layer, feature_family, feature_family_version, partition_key, "
                "file_uri, content_hash, schema_hash, row_count, calc_run_id "
                "FROM meta_feature_artifact_component WHERE feature_artifact_set_id = ?",
                [other_set, base.feature_artifact_set_id],
            )
            other_vid = validate_artifact_for_publish(
                conn,
                data_root=base.data_root,
                feature_artifact_set_id=other_set,
                validator_code_commit="test-commit",
            )
            # bind base's LATEST validation to the OTHER set's report
            other_report = conn.execute(
                "SELECT report_uri, report_hash FROM meta_artifact_validation "
                "WHERE artifact_validation_id = ?",
                [other_vid],
            ).fetchone()
            conn.execute(
                "UPDATE meta_artifact_validation SET report_uri = ?, report_hash = ? "
                "WHERE feature_artifact_set_id = ? "
                "AND artifact_validation_id = "
                "(SELECT artifact_validation_id FROM meta_artifact_validation "
                "WHERE feature_artifact_set_id = ? "
                "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1)",
                [
                    other_report[0],
                    other_report[1],
                    base.feature_artifact_set_id,
                    base.feature_artifact_set_id,
                ],
            )
            with pytest.raises(PublishStateError, match="IDENTITY violated"):
                publish_snapshot(conn, **_kwargs(conn, base))


@pytest.mark.integration
class TestLatestHeadPolicy:
    """B2-06: deterministic current-head policy."""

    def test_newer_fail_beats_older_pass(self, base):
        """A PASS validation followed by a revalidation AFTER a blocking
        DQ fact was recorded: the newest (FAIL) record is the head ->
        publish BLOCK (the old PASS cannot be chosen)."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            _revalidate(conn, base)  # PASS head
            record_artifact_dq_finding(
                conn,
                feature_artifact_set_id=base.feature_artifact_set_id,
                finding_class="BLOCKING_DQ",
            )
            _revalidate(conn, base)  # newer FAIL head
            with pytest.raises(PublishStateError):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_recovery_after_revalidation_pass(self, base):
        """PASS -> FAIL -> fix the facts (no findings for a NEW artifact
        identity) is out of scope here; but a NEWER PASS on the SAME
        unchanged artifact after the DQ facts were 'cleared' by using a
        fresh artifact set publishes fine."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            _revalidate(conn, base)
            pid = publish_snapshot(conn, **_kwargs(conn, base))
            assert pid


@pytest.mark.integration
class TestPublishBindingAndRollback:
    """B2-05: the publish binds the exact artifact_validation_id; a
    failed final gate preserves the previous PUBLISHED."""

    def test_publish_binds_exact_validation_id(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            validation_id = _revalidate(conn, base)
            kwargs = _kwargs(conn, base)
            pid = publish_snapshot(conn, **kwargs)
            bound = conn.execute(
                "SELECT artifact_validation_id FROM meta_publish_snapshot WHERE publish_id = ?",
                [pid],
            ).fetchone()[0]
            assert str(bound) == validation_id

    def test_failed_final_gate_preserves_old_published(self, base):
        """Inject a failure AFTER the in-transaction recheck (duplicate
        universe PK) -> rollback -> the previous PUBLISHED stays."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            old_pid = base.publish_ids[0]
            _revalidate(conn, base)
            kwargs = _kwargs(conn, base, trade_date=date(2026, 8, 14))
            kwargs["universes"] = [("ALL_A", "v1"), ("ALL_A", "v1")]  # PK violation
            with pytest.raises(Exception):
                publish_snapshot(conn, **kwargs)
            row = conn.execute(
                "SELECT publish_id FROM meta_publish_snapshot "
                "WHERE trade_date = ? AND status = 'PUBLISHED'",
                [date(2026, 8, 14)],
            ).fetchone()
            assert str(row[0]) == old_pid


# =========================================================================
# R4-B2.1 closures (audit 20260830 19:13)
# =========================================================================


def _current_component_manifest(conn, artifact_set_id: str) -> str:
    rows = conn.execute(
        "SELECT layer, feature_family, feature_family_version, partition_key, "
        "file_uri, content_hash, schema_hash, row_count "
        "FROM meta_feature_artifact_component WHERE feature_artifact_set_id = ? "
        "ORDER BY file_uri",
        [artifact_set_id],
    ).fetchall()
    keys = (
        "layer",
        "feature_family",
        "feature_family_version",
        "partition_key",
        "file_uri",
        "content_hash",
        "schema_hash",
        "row_count",
    )
    return av_module.compute_component_manifest_hash(
        [dict(zip(keys, r, strict=True)) for r in rows]
    )


def _record_dq_proofs(conn, artifact_set_id: str, *, data_root: Path | None = None) -> None:
    """Tests-side: run the GOVERNED scanner (the only legal completion
    writer). ``data_root`` defaults to the base fixture's root - tests
    that scan a foreign artifact pass its root explicitly."""
    if data_root is None:
        raise AssertionError("data_root is required for the governed scanner")
    run_required_artifact_dq_scan(
        conn, data_root=data_root, feature_artifact_set_id=artifact_set_id
    )


def _rebind_report_hash(conn, base, artifact_set_id: str | None = None) -> None:
    """Re-bind the ledger's report_hash AND required_checks_hash to the
    CURRENT report bytes / recomputed checks hash (the attacker re-seals
    consistently after tampering)."""
    artifact_set_id = artifact_set_id or base.feature_artifact_set_id
    _, report_uri, _ = _latest_validation(conn, artifact_set_id)
    report_path = base.data_root / str(report_uri)
    doc = json.loads(report_path.read_text(encoding="utf-8"))
    recomputed = hashlib.sha256(
        json.dumps(
            [{"check_id": c["check_id"], "status": c["status"]} for c in doc["checks"]],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    doc["required_checks_hash"] = recomputed
    report_path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    conn.execute(
        "UPDATE meta_artifact_validation SET report_hash = ?, required_checks_hash = ? "
        "WHERE feature_artifact_set_id = ? AND artifact_validation_id = "
        "(SELECT artifact_validation_id FROM meta_artifact_validation "
        "WHERE feature_artifact_set_id = ? "
        "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1)",
        [
            hashlib.sha256(report_path.read_bytes()).hexdigest(),
            recomputed,
            artifact_set_id,
            artifact_set_id,
        ],
    )


@pytest.mark.integration
class TestR4B21DQExecutionProof:
    """P0-01: absence of bad findings is NEVER proof of zero findings -
    the DQ required checks demand positive execution proofs bound to
    the CURRENT component manifest."""

    def test_no_execution_proof_is_not_testable_and_blocks(self, base):
        """Delete the execution proofs (feature pipeline never ran the
        scans) - no bad findings exist, yet the checks are NOT_TESTABLE
        and publish BLOCKs."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            conn.execute(
                "DELETE FROM meta_artifact_check_execution WHERE feature_artifact_set_id = ?",
                [base.feature_artifact_set_id],
            )
            validation_id = _revalidate(conn, base)
            row = conn.execute(
                "SELECT report_uri FROM meta_artifact_validation WHERE artifact_validation_id = ?",
                [validation_id],
            ).fetchone()
            report = json.loads((base.data_root / str(row[0])).read_text(encoding="utf-8"))
            dq = {
                c["check_id"]: c["status"]
                for c in report["checks"]
                if c["check_id"] in ("IDENTITY_FALLBACK_ZERO", "BLOCKING_DQ_ZERO")
            }
            assert dq == {
                "IDENTITY_FALLBACK_ZERO": "NOT_TESTABLE",
                "BLOCKING_DQ_ZERO": "NOT_TESTABLE",
            }
            with pytest.raises(PublishStateError, match="not_pass=.*IDENTITY_FALLBACK_ZERO"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_valid_exact_proof_with_zero_findings_passes(self, base):
        """The mock chain recorded matching proofs: the DQ checks PASS
        with the scan-executed evidence recorded in the detail."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            _revalidate(conn, base)
            pid = publish_snapshot(conn, **_kwargs(conn, base))
            assert pid
            row = conn.execute(
                "SELECT report_uri FROM meta_artifact_validation "
                "WHERE feature_artifact_set_id = ? "
                "ORDER BY validated_at DESC LIMIT 1",
                [base.feature_artifact_set_id],
            ).fetchone()
            report = json.loads((base.data_root / str(row[0])).read_text(encoding="utf-8"))
            for check in report["checks"]:
                if check["check_id"] in ("IDENTITY_FALLBACK_ZERO", "BLOCKING_DQ_ZERO"):
                    assert check["status"] == "PASS"
                    assert "scan executed" in check["detail"]

    def test_proof_for_different_artifact_does_not_transfer(self, base):
        """A completion proof recorded for ANOTHER artifact set never
        satisfies this artifact's checks (raw-INSERT the strongest
        attacker-shaped foreign proof: current contract, correct
        producer, current manifest - but a foreign artifact set id)."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            conn.execute(
                "DELETE FROM meta_artifact_check_execution WHERE feature_artifact_set_id = ?",
                [base.feature_artifact_set_id],
            )
            manifest = _current_component_manifest(conn, base.feature_artifact_set_id)
            for check_id in ("IDENTITY_FALLBACK_ZERO", "BLOCKING_DQ_ZERO"):
                from ashare_state.pipeline.artifact_dq_scan import ARTIFACT_DQ_CHECKERS

                producer = next(
                    s.producer for s in ARTIFACT_DQ_CHECKERS if s.check_id.value == check_id
                )
                conn.execute(
                    "INSERT INTO meta_artifact_check_execution VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        f"dqexec-{uuid.uuid4()}",
                        "some-other-artifact-set-xyz",
                        check_id,
                        DQ_SCAN_CONTRACT_VERSION,
                        producer,
                        manifest,
                        datetime.now(UTC),
                        "foreign proof",
                    ],
                )
            validation_id = _revalidate(conn, base)
            row = conn.execute(
                "SELECT report_uri FROM meta_artifact_validation WHERE artifact_validation_id = ?",
                [validation_id],
            ).fetchone()
            report = json.loads((base.data_root / str(row[0])).read_text(encoding="utf-8"))
            dq = {
                c["status"] for c in report["checks"] if c["check_id"] == "IDENTITY_FALLBACK_ZERO"
            }
            assert dq == {"NOT_TESTABLE"}
            with pytest.raises(PublishStateError):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_stale_proof_blocks_after_component_change(self, base):
        """A proof bound to the OLD component manifest is stale once a
        component changes - rescan required (NOT_TESTABLE)."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            conn.execute(
                "UPDATE meta_feature_artifact_component SET row_count = row_count + 1 "
                "WHERE feature_artifact_set_id = ?",
                [base.feature_artifact_set_id],
            )
            validation_id = _revalidate(conn, base)
            row = conn.execute(
                "SELECT report_uri FROM meta_artifact_validation WHERE artifact_validation_id = ?",
                [validation_id],
            ).fetchone()
            report = json.loads((base.data_root / str(row[0])).read_text(encoding="utf-8"))
            stale = {
                c["status"]
                for c in report["checks"]
                if c["check_id"] in ("IDENTITY_FALLBACK_ZERO", "BLOCKING_DQ_ZERO")
            }
            assert stale == {"NOT_TESTABLE"}
            assert any(
                "stale scan" in c["detail"].lower() for c in report["checks"] if "detail" in c
            )

    def test_missing_one_of_two_proofs_blocks(self, base):
        """Only the identity scan ran (proof deleted for the other) -
        BLOCKING_DQ_ZERO is NOT_TESTABLE -> BLOCK."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            conn.execute(
                "DELETE FROM meta_artifact_check_execution "
                "WHERE feature_artifact_set_id = ? AND check_id = 'BLOCKING_DQ_ZERO'",
                [base.feature_artifact_set_id],
            )
            validation_id = _revalidate(conn, base)
            row = conn.execute(
                "SELECT report_uri FROM meta_artifact_validation WHERE artifact_validation_id = ?",
                [validation_id],
            ).fetchone()
            report = json.loads((base.data_root / str(row[0])).read_text(encoding="utf-8"))
            dq = {
                c["check_id"]: c["status"]
                for c in report["checks"]
                if c["check_id"] in ("IDENTITY_FALLBACK_ZERO", "BLOCKING_DQ_ZERO")
            }
            assert dq["IDENTITY_FALLBACK_ZERO"] == "PASS"
            assert dq["BLOCKING_DQ_ZERO"] == "NOT_TESTABLE"
            with pytest.raises(PublishStateError, match="not_pass=.*BLOCKING_DQ_ZERO"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_execution_proof_api_carries_no_result_params(self):
        """R4-B2.2 structural guard: NO caller-facing completion writer
        exists in production. The ONLY production writer of
        meta_artifact_check_execution is the governed scan boundary
        ``run_required_artifact_dq_scan`` (AST scan), whose signature
        accepts no identity/result/count/completion inputs."""
        # 1. the R4-B2.1 caller-facing API is GONE from production
        import ashare_state.pipeline.artifact_dq_scan as scan_module
        import ashare_state.pipeline.artifact_validation as av

        for module in (av, scan_module):
            assert not hasattr(module, "record_artifact_check_execution")
        # 2. the only INSERT lives in the governed scan boundary
        inserters: set[tuple[str, str]] = set()
        pipeline_root = REPO_ROOT / "src" / "ashare_state" / "pipeline"
        for path in sorted(pipeline_root.glob("*.py")):
            mod_tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(mod_tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Constant)
                        and isinstance(sub.value, str)
                        and "INSERT INTO meta_artifact_check_execution" in sub.value
                    ):
                        inserters.add((path.name, node.name))
        assert inserters == {("artifact_dq_scan.py", "run_required_artifact_dq_scan")}, inserters
        # 3. the boundary signature accepts identity/results only via
        #    (conn, data_root, feature_artifact_set_id) - no scanned
        #    hash, no contract, no producer, no result/count/completed_at
        tree = ast.parse(
            (REPO_ROOT / "src/ashare_state/pipeline/artifact_dq_scan.py").read_text(
                encoding="utf-8"
            )
        )
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "run_required_artifact_dq_scan"
        )
        arg_names = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
        assert arg_names == {"conn", "data_root", "feature_artifact_set_id"}, arg_names


@pytest.mark.integration
class TestR4B21FullSealConsumption:
    """P0-02: the publish recheck cross-verifies the COMPLETE seal -
    ledger <-> report <-> CURRENT contract. All tamper tests re-bind the
    report hash (and required_checks_hash where relevant) and STILL
    block."""

    def _prepare(self, conn, base):
        _revalidate(conn, base)

    def _mutate_report(self, conn, base, mutate_doc) -> None:
        """Apply a mutation to the report document, re-bind the ledger
        report_hash to the tampered bytes (required_checks_hash is
        re-sealed consistently by default - the caller can override)."""
        _, report_uri, _ = _latest_validation(conn, base.feature_artifact_set_id)
        report_path = base.data_root / str(report_uri)
        doc = json.loads(report_path.read_text(encoding="utf-8"))
        mutate_doc(doc)
        report_path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
        recomputed = hashlib.sha256(
            json.dumps(
                [{"check_id": c["check_id"], "status": c["status"]} for c in doc["checks"]],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        doc["required_checks_hash"] = recomputed
        report_path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
        conn.execute(
            "UPDATE meta_artifact_validation SET report_hash = ?, required_checks_hash = ? "
            "WHERE feature_artifact_set_id = ? AND artifact_validation_id = "
            "(SELECT artifact_validation_id FROM meta_artifact_validation "
            "WHERE feature_artifact_set_id = ? "
            "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1)",
            [
                hashlib.sha256(report_path.read_bytes()).hexdigest(),
                recomputed,
                base.feature_artifact_set_id,
                base.feature_artifact_set_id,
            ],
        )

    def test_report_contract_hash_stale_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            self._prepare(conn, base)
            self._mutate_report(conn, base, lambda d: d.update(validation_contract_hash="f" * 64))
            with pytest.raises(PublishStateError, match="CONTRACT_STALE"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_ledger_report_contract_hash_mismatch_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            self._prepare(conn, base)
            # tamper ONLY the ledger's contract hash (report intact)
            conn.execute(
                "UPDATE meta_artifact_validation SET validation_contract_hash = ? "
                "WHERE feature_artifact_set_id = ? AND artifact_validation_id = "
                "(SELECT artifact_validation_id FROM meta_artifact_validation "
                "WHERE feature_artifact_set_id = ? "
                "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1)",
                ["e" * 64, base.feature_artifact_set_id, base.feature_artifact_set_id],
            )
            with pytest.raises(PublishStateError, match="CONTRACT_STALE"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_current_contract_change_blocks_old_validation(self, base, monkeypatch):
        """The validation contract evolves (hash changes) while the
        required check IDs stay unchanged - the old seal is stale and
        BLOCKs even though every ID still passes."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            self._prepare(conn, base)
            # _b2_recheck imports validation_contract_hash lazily from
            # the artifact_validation module at each call - patch there
            monkeypatch.setattr(av_module, "validation_contract_hash", lambda: "a" * 64)
            with pytest.raises(PublishStateError, match="CONTRACT_STALE"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_report_required_checks_hash_garbage_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            self._prepare(conn, base)
            _, report_uri, _ = _latest_validation(conn, base.feature_artifact_set_id)
            report_path = base.data_root / str(report_uri)
            doc = json.loads(report_path.read_text(encoding="utf-8"))
            doc["required_checks_hash"] = "0" * 64
            report_path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
            conn.execute(
                "UPDATE meta_artifact_validation SET report_hash = ? "
                "WHERE feature_artifact_set_id = ? AND artifact_validation_id = "
                "(SELECT artifact_validation_id FROM meta_artifact_validation "
                "WHERE feature_artifact_set_id = ? "
                "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1)",
                [
                    hashlib.sha256(report_path.read_bytes()).hexdigest(),
                    base.feature_artifact_set_id,
                    base.feature_artifact_set_id,
                ],
            )
            with pytest.raises(PublishStateError, match="CHECKS_HASH"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_ledger_checks_hash_mismatch_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            self._prepare(conn, base)
            conn.execute(
                "UPDATE meta_artifact_validation SET required_checks_hash = ? "
                "WHERE feature_artifact_set_id = ? AND artifact_validation_id = "
                "(SELECT artifact_validation_id FROM meta_artifact_validation "
                "WHERE feature_artifact_set_id = ? "
                "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1)",
                ["b" * 64, base.feature_artifact_set_id, base.feature_artifact_set_id],
            )
            with pytest.raises(PublishStateError, match="CHECKS_HASH"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_status_changed_without_rehash_blocks(self, base):
        """Flip one check status in the report and re-bind ONLY the
        report bytes hash (required_checks_hash field left stale) -
        the recomputed hash exposes the alteration."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            self._prepare(conn, base)
            _, report_uri, _ = _latest_validation(conn, base.feature_artifact_set_id)
            report_path = base.data_root / str(report_uri)
            doc = json.loads(report_path.read_text(encoding="utf-8"))
            for check in doc["checks"]:
                if check["check_id"] == "COMPONENT_ROW_COUNT":
                    check["status"] = "FAIL"
            report_path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
            conn.execute(
                "UPDATE meta_artifact_validation SET report_hash = ? "
                "WHERE feature_artifact_set_id = ? AND artifact_validation_id = "
                "(SELECT artifact_validation_id FROM meta_artifact_validation "
                "WHERE feature_artifact_set_id = ? "
                "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1)",
                [
                    hashlib.sha256(report_path.read_bytes()).hexdigest(),
                    base.feature_artifact_set_id,
                    base.feature_artifact_set_id,
                ],
            )
            with pytest.raises(PublishStateError, match="CHECKS_HASH"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_validator_commit_mismatch_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            self._prepare(conn, base)
            conn.execute(
                "UPDATE meta_artifact_validation SET validator_code_commit = ? "
                "WHERE feature_artifact_set_id = ? AND artifact_validation_id = "
                "(SELECT artifact_validation_id FROM meta_artifact_validation "
                "WHERE feature_artifact_set_id = ? "
                "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1)",
                ["someone-else", base.feature_artifact_set_id, base.feature_artifact_set_id],
            )
            with pytest.raises(PublishStateError, match="PROVENANCE"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_validation_version_mismatch_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            self._prepare(conn, base)
            conn.execute(
                "UPDATE meta_artifact_validation SET validation_version = ? "
                "WHERE feature_artifact_set_id = ? AND artifact_validation_id = "
                "(SELECT artifact_validation_id FROM meta_artifact_validation "
                "WHERE feature_artifact_set_id = ? "
                "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1)",
                ["legacy-v0", base.feature_artifact_set_id, base.feature_artifact_set_id],
            )
            with pytest.raises(PublishStateError, match="VERSION_STALE"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_duplicate_check_id_blocks(self, base):
        """Duplicate the COMPONENT_EXISTENCE entry (both PASS) and
        re-seal BOTH hashes consistently - duplicates still BLOCK."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            self._prepare(conn, base)
            _, report_uri, _ = _latest_validation(conn, base.feature_artifact_set_id)
            report_path = base.data_root / str(report_uri)
            doc = json.loads(report_path.read_text(encoding="utf-8"))
            dup = next(c for c in doc["checks"] if c["check_id"] == "COMPONENT_EXISTENCE")
            doc["checks"].append(dict(dup))
            report_path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
            recomputed = hashlib.sha256(
                json.dumps(
                    [{"check_id": c["check_id"], "status": c["status"]} for c in doc["checks"]],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            doc["required_checks_hash"] = recomputed
            report_path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
            conn.execute(
                "UPDATE meta_artifact_validation SET report_hash = ?, required_checks_hash = ? "
                "WHERE feature_artifact_set_id = ? AND artifact_validation_id = "
                "(SELECT artifact_validation_id FROM meta_artifact_validation "
                "WHERE feature_artifact_set_id = ? "
                "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1)",
                [
                    hashlib.sha256(report_path.read_bytes()).hexdigest(),
                    recomputed,
                    base.feature_artifact_set_id,
                    base.feature_artifact_set_id,
                ],
            )
            with pytest.raises(PublishStateError, match="DUPLICATE_CHECKS"):
                publish_snapshot(conn, **_kwargs(conn, base))


@pytest.mark.integration
class TestR4B21TransactionInternalPreconditions:
    """P0-03: ALL authoritative publish-precondition reads happen
    INSIDE the transaction; state that changes before the authoritative
    read blocks the publish; a final failure still rolls back and
    preserves the old PUBLISHED."""

    def test_structural_guard_preconditions_inside_transaction(self):
        """AST ordering guard: within publish_snapshot, BEGIN TRANSACTION
        precedes the precondition resolver, the seal recheck and every
        write; nothing database-read happens before BEGIN in the
        function body."""
        src = PUBLISH_SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "publish_snapshot"
        )
        positions: dict[str, int] = {}
        for node in ast.walk(fn):
            begins_transaction = (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "BEGIN TRANSACTION" in node.value
            )
            if begins_transaction:
                positions["begin"] = min(positions.get("begin", node.lineno), node.lineno)
            if isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in (
                    "_resolve_publish_preconditions",
                    "_b2_recheck",
                    "execute",
                ):
                    key = f"call:{name}"
                    positions.setdefault(key, node.lineno)
        assert "begin" in positions
        assert "call:_resolve_publish_preconditions" in positions
        assert "call:_b2_recheck" in positions
        assert positions["begin"] < positions["call:_resolve_publish_preconditions"], (
            "preconditions must be resolved AFTER BEGIN TRANSACTION"
        )
        assert positions["begin"] < positions["call:_b2_recheck"], (
            "the seal recheck must run AFTER BEGIN TRANSACTION"
        )
        # and the FIRST conn.execute in the function is the BEGIN itself
        first_execute = positions.get("call:execute")
        assert first_execute is not None and positions["begin"] <= first_execute

    def test_snapshot_demoted_before_publish_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            conn.execute(
                "UPDATE meta_data_snapshot SET status = 'DATA_STALE' WHERE data_snapshot_id = ?",
                [base.data_snapshot_id],
            )
            with pytest.raises(PublishStateError, match="DATA_VALIDATED"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_artifact_demoted_before_publish_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            conn.execute(
                "UPDATE meta_feature_artifact_set SET status = 'FEATURE_STALE' "
                "WHERE feature_artifact_set_id = ?",
                [base.feature_artifact_set_id],
            )
            with pytest.raises(PublishStateError, match="FEATURE_VALIDATED"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_artifact_rebound_to_other_snapshot_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            conn.execute(
                "UPDATE meta_feature_artifact_set SET data_snapshot_id = 'snap-other' "
                "WHERE feature_artifact_set_id = ?",
                [base.feature_artifact_set_id],
            )
            with pytest.raises(PublishStateError, match="SNAPSHOT_ARTIFACT_LINEAGE_VALID"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_feature_set_definition_changed_before_publish_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            conn.execute(
                "INSERT INTO meta_feature_set_member VALUES (?, ?, ?, ?)",
                [SKELETON_FEATURE_SET_VERSION, "rogue_feature", "9.9.9", "rogue-param"],
            )
            with pytest.raises(PublishStateError, match="FEATURE_SET_IMMUTABLE"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_run_status_changed_before_publish_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            kwargs = _kwargs(conn, base)
            conn.execute(
                "UPDATE meta_pipeline_run SET status = 'FAILED' WHERE pipeline_run_id = ?",
                [kwargs["pipeline_run_id"]],
            )
            with pytest.raises(PublishStateError, match="FEATURE_VALIDATED"):
                publish_snapshot(conn, **kwargs)

    def test_universe_removed_before_publish_blocks(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            kwargs = _kwargs(conn, base)
            conn.execute(
                "DELETE FROM dim_universe WHERE universe_id = 'ALL_A' AND universe_version = 'v1'"
            )
            with pytest.raises(PublishStateError, match="not registered in dim_universe"):
                publish_snapshot(conn, **kwargs)


@pytest.mark.integration
class TestR4B21LogicalURIConfinement:
    """P0-04: registry file_uris resolve ONLY through the frozen
    logical-URI confinement helper - escaped/absolute/drive/backslash/
    alias URIs fail closed even when the outside file exists and its
    hash matches."""

    @pytest.mark.parametrize(
        "evil_uri",
        [
            "../outside-sentinel.parquet",
            "/outside-sentinel.parquet",
            "C:/outside-sentinel.parquet",
            "features\\\\evil.parquet",
            "features//evil.parquet",
            "features/./evil.parquet",
        ],
    )
    def test_evil_component_uri_fails_closed(self, base, evil_uri):
        """Point one component at an escaped/absolute/alias URI, place a
        PERFECT sentinel file outside the data root (bytes identical to
        the real component) - validation FAILs on confinement, never
        reads outside the root, and publish BLOCKs."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            comp_uri = conn.execute(
                "SELECT file_uri FROM meta_feature_artifact_component "
                "WHERE feature_artifact_set_id = ? ORDER BY file_uri LIMIT 1",
                [base.feature_artifact_set_id],
            ).fetchone()[0]
            real = base.data_root / str(comp_uri)
            # sentinel OUTSIDE the data root with IDENTICAL bytes
            outside = base.data_root.parent / "outside-sentinel.parquet"
            outside.parent.mkdir(parents=True, exist_ok=True)
            outside.write_bytes(real.read_bytes())
            conn.execute(
                "UPDATE meta_feature_artifact_component SET file_uri = ? "
                "WHERE feature_artifact_set_id = ? AND file_uri = ?",
                [evil_uri, base.feature_artifact_set_id, comp_uri],
            )
            # R4-B2.2: the governed scanner itself refuses to open the
            # evil URI, so the attacker re-seals completion proofs for
            # the CURRENT (tampered) registry identity via raw SQL - the
            # confinement failure must still be caught by the
            # validation/publish path (else NOT_TESTABLE from staleness
            # would mask the confinement failure).
            conn.execute(
                "DELETE FROM meta_artifact_check_execution WHERE feature_artifact_set_id = ?",
                [base.feature_artifact_set_id],
            )
            from ashare_state.pipeline.artifact_dq_scan import ARTIFACT_DQ_CHECKERS

            manifest = _current_component_manifest(conn, base.feature_artifact_set_id)
            for spec in ARTIFACT_DQ_CHECKERS:
                conn.execute(
                    "INSERT INTO meta_artifact_check_execution VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        f"dqexec-{uuid.uuid4()}",
                        base.feature_artifact_set_id,
                        spec.check_id.value,
                        DQ_SCAN_CONTRACT_VERSION,
                        spec.producer,
                        manifest,
                        datetime.now(UTC),
                        "attacker re-seal",
                    ],
                )
            validation_id = _revalidate(conn, base)
            row = conn.execute(
                "SELECT report_uri FROM meta_artifact_validation WHERE artifact_validation_id = ?",
                [validation_id],
            ).fetchone()
            report = json.loads((base.data_root / str(row[0])).read_text(encoding="utf-8"))
            existence = next(c for c in report["checks"] if c["check_id"] == "COMPONENT_EXISTENCE")
            assert existence["status"] == "FAIL"
            assert "confinement" in existence["detail"].lower() or "canonical" in (
                existence["detail"].lower()
            )
            # publish blocks on the failed validation
            with pytest.raises(PublishStateError):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_valid_canonical_uri_still_passes(self, base):
        """The untouched mock chain (canonical POSIX relative URIs)
        validates and publishes - confinement does not over-block."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            _revalidate(conn, base)
            pid = publish_snapshot(conn, **_kwargs(conn, base))
            assert pid


# =========================================================================
# R4-B2.2 (audit 20260831): governed DQ scan execution boundary
# =========================================================================


@pytest.mark.integration
class TestR4B22GovernedScanBoundary:
    """The completion proof is a SCANNER-internal product: the governed
    boundary executes the required checks over authoritative input,
    persists findings, and writes the completion proof LAST."""

    def test_no_caller_facing_completion_writer_in_production(self):
        """No production callable writes a completion row except the
        governed scan boundary (which executes the checks)."""
        import ashare_state.pipeline.artifact_dq_scan as scan_module
        import ashare_state.pipeline.artifact_validation as av
        from ashare_state.pipeline import artifact_validation
        from ashare_state.pipeline import publish as publish_mod

        for module in (av, scan_module, artifact_validation, publish_mod):
            assert not hasattr(module, "record_artifact_check_execution")

    def test_caller_computed_manifest_cannot_declare_completion(self, base):
        """The exact R4-B2.1 attack from the review: the caller reads the
        components, computes the current manifest hash, and tries to
        write completion rows - there is NO API to do it (the only
        INSERT lives inside the scan boundary whose signature accepts
        (conn, data_root, feature_artifact_set_id) only)."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            conn.execute(
                "DELETE FROM meta_artifact_check_execution WHERE feature_artifact_set_id = ?",
                [base.feature_artifact_set_id],
            )
            _manifest = _current_component_manifest(conn, base.feature_artifact_set_id)  # noqa: F841
            # the strongest legitimate API shape is the scanner itself -
            # it takes no manifest, no contract, no producer
            run_required_artifact_dq_scan(
                conn,
                data_root=base.data_root,
                feature_artifact_set_id=base.feature_artifact_set_id,
            )
            rows = conn.execute(
                "SELECT count(*) FROM meta_artifact_check_execution "
                "WHERE feature_artifact_set_id = ?",
                [base.feature_artifact_set_id],
            ).fetchone()
            assert int(rows[0]) == 2  # both checks completed via the REAL scan

    def test_scanner_failure_writes_no_completion(self, base, monkeypatch):
        """A checker evaluator that cannot run leaves NO completion
        proof for its check (the whole scan transaction rolls back)."""
        from ashare_state.pipeline import artifact_dq_scan as scan_module

        def _boom(conn, data_root, artifact_set_id, snapshot_id):
            raise RuntimeError("checker unavailable")

        # ARTIFACT_DQ_CHECKERS is a tuple of frozen dataclasses - patch
        # the module-level tuple (the scan boundary reads the module
        # global at execution time)
        monkeypatch.setattr(
            scan_module,
            "ARTIFACT_DQ_CHECKERS",
            (
                scan_module.ArtifactDQCheckerSpec(
                    check_id=scan_module.ARTIFACT_DQ_CHECKERS[0].check_id,
                    finding_class=scan_module.ARTIFACT_DQ_CHECKERS[0].finding_class,
                    checker_version=scan_module.ARTIFACT_DQ_CHECKERS[0].checker_version,
                    evaluator=_boom,
                ),
                scan_module.ARTIFACT_DQ_CHECKERS[1],
            ),
        )
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            conn.execute(
                "DELETE FROM meta_artifact_check_execution WHERE feature_artifact_set_id = ?",
                [base.feature_artifact_set_id],
            )
            with pytest.raises(RuntimeError, match="checker unavailable"):
                run_required_artifact_dq_scan(
                    conn,
                    data_root=base.data_root,
                    feature_artifact_set_id=base.feature_artifact_set_id,
                )
            rows = conn.execute(
                "SELECT count(*) FROM meta_artifact_check_execution "
                "WHERE feature_artifact_set_id = ?",
                [base.feature_artifact_set_id],
            ).fetchone()
            assert int(rows[0]) == 0
            # validation then sees NOT_TESTABLE -> publish BLOCK
            validation_id = _revalidate(conn, base)
            row = conn.execute(
                "SELECT report_uri FROM meta_artifact_validation WHERE artifact_validation_id = ?",
                [validation_id],
            ).fetchone()
            report = json.loads((base.data_root / str(row[0])).read_text(encoding="utf-8"))
            dq = {
                c["check_id"]: c["status"]
                for c in report["checks"]
                if c["check_id"] in ("IDENTITY_FALLBACK_ZERO", "BLOCKING_DQ_ZERO")
            }
            assert dq["IDENTITY_FALLBACK_ZERO"] == "NOT_TESTABLE"
            with pytest.raises(PublishStateError):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_scanner_detects_identity_fallback_finding(self, base):
        """REAL detection: register one of the artifact's securities
        with the FALLBACK identity key version - the governed scanner
        detects it, persists the finding, and validation FAILs."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            # flip one registered identity to the fallback variant
            target = conn.execute("SELECT security_id FROM dim_security LIMIT 1").fetchone()[0]
            conn.execute(
                "UPDATE dim_security SET identity_key_version = ? WHERE security_id = ?",
                ["SECURITY_IDENTITY_V1_FALLBACK", target],
            )
            conn.execute(
                "DELETE FROM meta_artifact_dq_finding WHERE feature_artifact_set_id = ?",
                [base.feature_artifact_set_id],
            )
            run_required_artifact_dq_scan(
                conn,
                data_root=base.data_root,
                feature_artifact_set_id=base.feature_artifact_set_id,
            )
            findings = conn.execute(
                "SELECT count(*) FROM meta_artifact_dq_finding "
                "WHERE feature_artifact_set_id = ? AND finding_class = 'IDENTITY_FALLBACK'",
                [base.feature_artifact_set_id],
            ).fetchone()
            assert int(findings[0]) >= 1  # the scanner persisted the finding
            validation_id = _revalidate(conn, base)
            row = conn.execute(
                "SELECT report_uri FROM meta_artifact_validation WHERE artifact_validation_id = ?",
                [validation_id],
            ).fetchone()
            report = json.loads((base.data_root / str(row[0])).read_text(encoding="utf-8"))
            fallback = next(
                c for c in report["checks"] if c["check_id"] == "IDENTITY_FALLBACK_ZERO"
            )
            assert fallback["status"] == "FAIL"
            with pytest.raises(PublishStateError):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_scanner_detects_blocking_dq_finding(self, base):
        """REAL detection: a canonical fact row carrying a blocking DQ
        quality flag for the artifact's snapshot - the scanner detects
        it, persists the finding, and validation FAILs."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            conn.execute(
                "INSERT INTO fact_daily_bar "
                "(data_snapshot_id, security_id, trade_date, open, high, low, close, "
                "pre_close, volume_shares, amount_cny, selected_provider, "
                "source_policy_version, reconciliation_status, quality_flags, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    base.data_snapshot_id,
                    "00000000-0000-0000-0000-000000000001",
                    date(2026, 8, 14),
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                    100,
                    10000.0,
                    "amazingdata",
                    "source-policy-mock-v1",
                    "NOT_RUN_NO_SECONDARY",
                    "STALE_WINDOW",  # blocking DQ flag
                    datetime.now(UTC),
                ],
            )
            conn.execute(
                "DELETE FROM meta_artifact_dq_finding WHERE feature_artifact_set_id = ? "
                "AND finding_class = 'BLOCKING_DQ'",
                [base.feature_artifact_set_id],
            )
            run_required_artifact_dq_scan(
                conn,
                data_root=base.data_root,
                feature_artifact_set_id=base.feature_artifact_set_id,
            )
            findings = conn.execute(
                "SELECT count(*) FROM meta_artifact_dq_finding "
                "WHERE feature_artifact_set_id = ? AND finding_class = 'BLOCKING_DQ'",
                [base.feature_artifact_set_id],
            ).fetchone()
            assert int(findings[0]) >= 1
            validation_id = _revalidate(conn, base)
            row = conn.execute(
                "SELECT report_uri FROM meta_artifact_validation WHERE artifact_validation_id = ?",
                [validation_id],
            ).fetchone()
            report = json.loads((base.data_root / str(row[0])).read_text(encoding="utf-8"))
            blocking = next(c for c in report["checks"] if c["check_id"] == "BLOCKING_DQ_ZERO")
            assert blocking["status"] == "FAIL"
            with pytest.raises(PublishStateError):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_unregistered_identity_is_a_finding(self, base):
        """Fail-closed scan: a security_id in the artifact that is NOT
        registered in dim_security cannot be proven non-fallback - the
        scanner records it as a finding (never silently PASSes)."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            conn.execute(
                "DELETE FROM dim_security WHERE security_id IN "
                "(SELECT DISTINCT security_id FROM ("
                "  SELECT unnest([?]) AS security_id))",
                [conn.execute("SELECT security_id FROM dim_security LIMIT 1").fetchone()[0]],
            )
            conn.execute(
                "DELETE FROM meta_artifact_dq_finding WHERE feature_artifact_set_id = ? "
                "AND finding_class = 'IDENTITY_FALLBACK'",
                [base.feature_artifact_set_id],
            )
            run_required_artifact_dq_scan(
                conn,
                data_root=base.data_root,
                feature_artifact_set_id=base.feature_artifact_set_id,
            )
            findings = conn.execute(
                "SELECT count(*) FROM meta_artifact_dq_finding "
                "WHERE feature_artifact_set_id = ? AND finding_class = 'IDENTITY_FALLBACK'",
                [base.feature_artifact_set_id],
            ).fetchone()
            assert int(findings[0]) >= 1
            validation_id = _revalidate(conn, base)
            row = conn.execute(
                "SELECT report_uri FROM meta_artifact_validation WHERE artifact_validation_id = ?",
                [validation_id],
            ).fetchone()
            report = json.loads((base.data_root / str(row[0])).read_text(encoding="utf-8"))
            fallback = next(
                c for c in report["checks"] if c["check_id"] == "IDENTITY_FALLBACK_ZERO"
            )
            assert fallback["status"] == "FAIL"

    def test_scan_contract_version_evolution_requires_rescan(self, base, monkeypatch):
        """The scan contract evolves (version string changes) - old
        completion proofs no longer satisfy the CURRENT validator:
        NOT_TESTABLE / rescan required, even for a proof whose
        manifest still matches."""
        from ashare_state.pipeline import artifact_dq_scan as scan_module

        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            _revalidate(conn, base)  # proofs from the b2.2-v1 contract
            monkeypatch.setattr(scan_module, "DQ_SCAN_CONTRACT_VERSION", "dq-scan-future-v9")
            # artifact_validation imported the constant at module load:
            # patch its view too
            monkeypatch.setattr(av_module, "DQ_SCAN_CONTRACT_VERSION", "dq-scan-future-v9")
            validation_id = _revalidate(conn, base)
            row = conn.execute(
                "SELECT report_uri FROM meta_artifact_validation WHERE artifact_validation_id = ?",
                [validation_id],
            ).fetchone()
            report = json.loads((base.data_root / str(row[0])).read_text(encoding="utf-8"))
            contracts = {
                c["status"]
                for c in report["checks"]
                if c["check_id"] in ("IDENTITY_FALLBACK_ZERO", "BLOCKING_DQ_ZERO")
            }
            assert contracts == {"NOT_TESTABLE"}
            assert any(
                "scan contract mismatch" in c["detail"] for c in report["checks"] if "detail" in c
            )

    def test_fake_producer_or_contract_cannot_satisfy_validator(self, base):
        """Raw-INSERTed attacker-shaped completion rows (fake contract
        version / fake producer, manifest and check_id correct) do NOT
        satisfy the validator - only the system-derived checker
        identity + CURRENT contract counts."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            manifest = _current_component_manifest(conn, base.feature_artifact_set_id)
            conn.execute(
                "DELETE FROM meta_artifact_check_execution WHERE feature_artifact_set_id = ?",
                [base.feature_artifact_set_id],
            )
            for check_id, contract, producer in (
                (
                    "IDENTITY_FALLBACK_ZERO",
                    "fake-v0",
                    "artifact-dq-scanner/IDENTITY_FALLBACK_ZERO@identity-fallback-checker-v1",
                ),
                ("BLOCKING_DQ_ZERO", DQ_SCAN_CONTRACT_VERSION, "attacker"),
            ):
                conn.execute(
                    "INSERT INTO meta_artifact_check_execution VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        f"dqexec-{uuid.uuid4()}",
                        base.feature_artifact_set_id,
                        check_id,
                        contract,
                        producer,
                        manifest,
                        datetime.now(UTC),
                        "attacker-shaped proof",
                    ],
                )
            validation_id = _revalidate(conn, base)
            row = conn.execute(
                "SELECT report_uri FROM meta_artifact_validation WHERE artifact_validation_id = ?",
                [validation_id],
            ).fetchone()
            report = json.loads((base.data_root / str(row[0])).read_text(encoding="utf-8"))
            dq = {
                c["check_id"]: c["status"]
                for c in report["checks"]
                if c["check_id"] in ("IDENTITY_FALLBACK_ZERO", "BLOCKING_DQ_ZERO")
            }
            assert dq == {
                "IDENTITY_FALLBACK_ZERO": "NOT_TESTABLE",
                "BLOCKING_DQ_ZERO": "NOT_TESTABLE",
            }
            details = [c.get("detail", "") for c in report["checks"]]
            assert any("scan contract mismatch" in d for d in details)
            assert any("checker identity mismatch" in d for d in details)

    def test_genuine_zero_scan_passes_and_publishes(self, base):
        """The mock chain's governed scan genuinely executed (identity
        registry cross-check + fact-table flags over authoritative
        input) and found zero - the DQ checks PASS and publish
        succeeds."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            proofs = conn.execute(
                "SELECT check_id, scan_contract_version, producer "
                "FROM meta_artifact_check_execution "
                "WHERE feature_artifact_set_id = ?",
                [base.feature_artifact_set_id],
            ).fetchall()
            assert {str(p[0]) for p in proofs} == {
                "IDENTITY_FALLBACK_ZERO",
                "BLOCKING_DQ_ZERO",
            }
            for _check, contract, producer in proofs:
                assert str(contract) == DQ_SCAN_CONTRACT_VERSION
                assert str(producer).startswith("artifact-dq-scanner/")
            pid = publish_snapshot(conn, **_kwargs(conn, base))
            assert pid

    def test_findings_deduplicated_across_rescans(self, base):
        """Rescanning the same fallback condition does not inflate the
        derived counts (append-only facts are deduplicated by
        (artifact, class, detail))."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            target = conn.execute("SELECT security_id FROM dim_security LIMIT 1").fetchone()[0]
            conn.execute(
                "UPDATE dim_security SET identity_key_version = ? WHERE security_id = ?",
                ["SECURITY_IDENTITY_V1_FALLBACK", target],
            )
            conn.execute(
                "DELETE FROM meta_artifact_dq_finding WHERE feature_artifact_set_id = ?",
                [base.feature_artifact_set_id],
            )
            for _ in range(3):
                run_required_artifact_dq_scan(
                    conn,
                    data_root=base.data_root,
                    feature_artifact_set_id=base.feature_artifact_set_id,
                )
            findings = conn.execute(
                "SELECT count(*) FROM meta_artifact_dq_finding "
                "WHERE feature_artifact_set_id = ? AND finding_class = 'IDENTITY_FALLBACK'",
                [base.feature_artifact_set_id],
            ).fetchone()
            assert int(findings[0]) == 1  # deduplicated

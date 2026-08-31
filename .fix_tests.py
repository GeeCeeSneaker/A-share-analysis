from pathlib import Path

path = Path("tests/integration/test_publish_validation_exactness.py")
src = path.read_text(encoding="utf-8")

# 1) scanner-failure test: evaluator kwarg -> resolve_input/evaluate shape
src = src.replace(
    """        def _boom(conn, data_root, artifact_set_id, snapshot_id):
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
        )""",
    """        def _boom(input_state):
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
                    resolve_input=scan_module.ARTIFACT_DQ_CHECKERS[0].resolve_input,
                    evaluate=_boom,
                ),
                scan_module.ARTIFACT_DQ_CHECKERS[1],
            ),
        )""",
)

# 2) all raw 8-value INSERTs -> explicit 10-column form with current
#    input seals (strongest attacker shape)
old_insert = '''                conn.execute(
                    "INSERT INTO meta_artifact_check_execution VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        f"dqexec-{uuid.uuid4()}",
'''
new_insert = '''                conn.execute(
                    "INSERT INTO meta_artifact_check_execution "
                    "(execution_id, feature_artifact_set_id, check_id, "
                    "scan_contract_version, producer, scanned_component_manifest_hash, "
                    "completed_at, detail, authoritative_input_hash, "
                    "scanned_data_snapshot_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        f"dqexec-{uuid.uuid4()}",
'''
count = src.count(old_insert)
src = src.replace(old_insert, new_insert)
print(f"replaced {count} INSERT headers")

# the value lists need 2 more entries; each ends with a detail string
# followed by '],' - append seal values using the CURRENT fingerprints
# (strongest attacker) - compute them via the public helper at the
# point of the INSERT. We patch per test below.

# foreign-proof test
src = src.replace(
    '''            manifest = _current_component_manifest(conn, base.feature_artifact_set_id)
            for check_id in ("IDENTITY_FALLBACK_ZERO", "BLOCKING_DQ_ZERO"):
                from ashare_state.pipeline.artifact_dq_scan import ARTIFACT_DQ_CHECKERS

                producer = next(s.producer for s in ARTIFACT_DQ_CHECKERS if s.check_id.value == check_id)
                conn.execute(
                    "INSERT INTO meta_artifact_check_execution "''',
    '''            manifest = _current_component_manifest(conn, base.feature_artifact_set_id)
            from ashare_state.pipeline.artifact_dq_scan import (
                current_authoritative_input_fingerprints,
            )

            seals = current_authoritative_input_fingerprints(
                conn, data_root=base.data_root, feature_artifact_set_id=base.feature_artifact_set_id
            )
            for check_id in ("IDENTITY_FALLBACK_ZERO", "BLOCKING_DQ_ZERO"):
                from ashare_state.pipeline.artifact_dq_scan import ARTIFACT_DQ_CHECKERS

                producer = next(s.producer for s in ARTIFACT_DQ_CHECKERS if s.check_id.value == check_id)
                conn.execute(
                    "INSERT INTO meta_artifact_check_execution "''',
)
src = src.replace(
    '''                        manifest,
                        datetime.now(UTC),
                        "foreign proof",
                    ],
                )''',
    '''                        manifest,
                        datetime.now(UTC),
                        "foreign proof",
                        seals[check_id],
                        "",
                    ],
                )''',
)

path.write_text(src, encoding="utf-8", newline="\n")
print("stage 1 done")

"""Read-only replay of one sealed Formal run.

The diagnostic reads only local raw/meta evidence and current in-memory
adapters/validators. It never constructs a provider target, SpikeRun,
catalog writer, or verdict writer. Its output contains hashes, counts,
classifications, and reason codes; provider rows and account data are not
emitted.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ashare_state.spike.capabilities import CORE_CAPABILITIES
from ashare_state.spike.golden_router import (
    CA_PROVIDER_FIELD_CONTRACT,
    CAProviderShapeError,
    DomainData,
    _ca_provider_view,
    _calendar_days,
    _payload_columns,
    validate_case_in_domain,
)
from ashare_state.spike.golden_store import GoldenTruthStore
from ashare_state.spike.model import CaseResult
from ashare_state.spike.row_adapter import (
    ProviderRowShapeError,
    canonical_daily_bar_view,
    canonical_status_view,
    date_key,
    key_preserving_table_rows,
    provider_symbol,
)
from ashare_state.spike.trading_rule import load_bound_rule_book
from ashare_state.spike.validators import (
    ValidationOutcome,
    validate_adj_continuity,
    validate_daily_bar_units,
    validate_history_coverage_by_symbol,
    validate_security_master_delisted,
    validate_st_suspend_flags,
    validate_symbol_mapping,
)
from ashare_state.storage.raw_writer import RawWriter, verify_meta_closure

SEALED_RUN_ID = "dad1e1b8-0c34-4031-8e94-cc87a03dbbf4"
SEALED_CATALOG_SHA256 = "bad92a04ae6008cc094d72a213f670f0ccdf9ab5befc285b29e46d0a7a9dee53"
SEALED_GOLDEN_SHA256 = "a51013f8fbfb2e9addceb4b75c2213d35a30c3b65459928164b77597aecb983e"
SEALED_RULE_DATASET_SHA256 = "b8b77ef83f5741c12a2effef988f793c0827f737ea471494814c1b0b6d7f9aed"
EXPECTED_CASE_COUNT = 178

GOLDEN_BUNDLES = {
    "golden_st_transition": "st_status-773ff1c2.json",
    "golden_delisted": "delisted_master-5dfa186b.json",
    "golden_limit_regime": "limit_pit_rule-c7cd2ddc.json",
    "golden_corporate_action": "corp_action_context-ce7d64e1.json",
}


@dataclass(frozen=True)
class LoadedEvidence:
    anchor: dict[str, Any]
    meta: dict[str, Any]
    payload: Any
    payload_loaded: bool


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _path_inside(path: Path, parent: Path) -> None:
    if not path.is_relative_to(parent):
        raise ValueError(f"path escapes confined root: {path}")


def _tree_anchor(root: Path) -> dict[str, Any]:
    """Hash all files by logical path, size, and content hash."""

    root = root.resolve()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    total_bytes = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        content_hash = _sha256_file(path)
        digest.update(f"{relative}\0{size}\0{content_hash}\n".encode())
        total_bytes += size
    return {
        "file_count": len(files),
        "bytes": total_bytes,
        "inventory_sha256": digest.hexdigest(),
    }


def _raw_relative_path(raw_root: Path, reference: str) -> Path:
    normalized = str(reference).replace("\\", "/")
    if "/raw/" in normalized:
        relative_text = normalized.split("/raw/", 1)[1]
    elif normalized.startswith("raw/"):
        relative_text = normalized[4:]
    else:
        raise ValueError("evidence reference does not contain a raw path")
    path = (raw_root / Path(relative_text)).resolve()
    _path_inside(path, raw_root.resolve())
    if not path.name.endswith(".meta.json"):
        raise ValueError("evidence reference is not a raw meta document")
    return path


def _payload_anchor(meta_path: Path, meta: dict[str, Any]) -> str:
    tables = [
        {
            "content_hash": str(table.get("content_hash", "")),
            "file": str(table.get("file", "")),
            "name": table.get("name"),
            "row_count": int(table.get("row_count", 0) or 0),
            "schema_hash": str(table.get("schema_hash", "")),
        }
        for table in meta.get("tables") or []
    ]
    return _canonical_hash(
        {
            "content_hash": str(meta.get("content_hash", "")),
            "meta_path": meta_path.name,
            "null_tables": [str(name) for name in meta.get("null_tables") or []],
            "payload_kind": str(meta.get("payload_kind", "")),
            "tables": tables,
        }
    )


def _meta_anchor(
    run_root: Path,
    meta_path: Path,
    meta: dict[str, Any],
) -> dict[str, Any]:
    return {
        "logical_path": meta_path.relative_to(run_root).as_posix(),
        "provider_dataset": str(meta.get("provider_dataset", "")),
        "meta_sha256": _sha256_file(meta_path),
        "declared_payload_content_hash": str(meta.get("content_hash", "")),
        "declared_payload_anchor_sha256": _payload_anchor(meta_path, meta),
        "payload_kind": str(meta.get("payload_kind", "")),
        "declared_rows": int(meta.get("row_count", 0) or 0),
        "table_count": len(meta.get("tables") or []),
        "null_table_count": len(meta.get("null_tables") or []),
    }


class EvidenceReader:
    """Read-only meta/payload reader; no provider or write path is imported."""

    def __init__(self, run_root: Path) -> None:
        self.run_root = run_root.resolve()
        self.raw_root = (self.run_root / "raw").resolve()
        self.raw_writer = RawWriter(self.raw_root)
        self._loaded: dict[str, LoadedEvidence] = {}
        self.anchors: dict[str, dict[str, Any]] = {}
        self.meta_read_count = 0
        self.payload_read_count = 0

    def read_ref(
        self,
        reference: str,
        *,
        expected_meta_hash: str = "",
        load_payload: bool = True,
    ) -> LoadedEvidence:
        meta_path = _raw_relative_path(self.raw_root, reference)
        logical_path = meta_path.relative_to(self.run_root).as_posix()
        cached = self._loaded.get(logical_path)
        if cached is not None and (not load_payload or cached.payload_loaded):
            return cached

        meta_bytes = meta_path.read_bytes()
        actual_meta_hash = hashlib.sha256(meta_bytes).hexdigest()
        if expected_meta_hash and actual_meta_hash != expected_meta_hash:
            raise RuntimeError(f"bundle meta anchor mismatch for {logical_path}")
        meta = json.loads(meta_bytes.decode("utf-8"))
        if str(meta.get("ingest_run_id", "")) not in ("", SEALED_RUN_ID):
            raise RuntimeError(f"raw meta is bound to a different run: {logical_path}")
        problems = verify_meta_closure(meta_path.parent, meta)
        if problems:
            raise RuntimeError(f"raw closure failed for {logical_path}: {problems[:2]}")

        anchor = _meta_anchor(self.run_root, meta_path, meta)
        self.anchors[logical_path] = anchor
        self.meta_read_count += 1
        payload: Any = None
        if load_payload:
            if str(meta.get("payload_kind", "")) != "failure":
                payload = self.raw_writer.read(
                    provider=str(meta.get("provider", "amazingdata")),
                    dataset=str(meta["provider_dataset"]),
                    request_id=str(meta["request_id"]),
                    verify=False,
                )
            self.payload_read_count += 1
        loaded = LoadedEvidence(
            anchor=anchor,
            meta=meta,
            payload=payload,
            payload_loaded=load_payload,
        )
        self._loaded[logical_path] = loaded
        return loaded

    def read_bundle(self, bundle_name: str) -> tuple[list[LoadedEvidence], dict[str, Any]]:
        bundle_path = (self.raw_root / "bundles" / bundle_name).resolve()
        _path_inside(bundle_path, self.raw_root.resolve())
        bundle_bytes = bundle_path.read_bytes()
        bundle = json.loads(bundle_bytes.decode("utf-8"))
        if str(bundle.get("spike_run_id", "")) != SEALED_RUN_ID:
            raise RuntimeError(f"bundle is bound to a different run: {bundle_name}")
        bundle_anchor = {
            "logical_path": bundle_path.relative_to(self.run_root).as_posix(),
            "sha256": hashlib.sha256(bundle_bytes).hexdigest(),
            "bytes": len(bundle_bytes),
            "exchange_count": len(bundle.get("exchanges") or []),
        }
        self.anchors[bundle_anchor["logical_path"]] = bundle_anchor
        loaded = [
            self.read_ref(
                str(entry["meta_ref"]),
                expected_meta_hash=str(entry.get("meta_hash", "")),
                load_payload=True,
            )
            for entry in bundle.get("exchanges") or []
        ]
        return loaded, bundle_anchor


def _rows(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        result: list[dict[str, Any]] = []
        for value in payload.values():
            result.extend(_rows(value))
        return result
    if isinstance(payload, list):
        return [dict(row) if isinstance(row, dict) else {"value": row} for row in payload]
    rows_method = getattr(payload, "rows", None)
    if callable(rows_method) and hasattr(payload, "columns"):
        return [dict(zip(payload.columns, row, strict=True)) for row in rows_method()]
    to_dict = getattr(payload, "to_dict", None)
    if callable(to_dict):
        try:
            records = to_dict(orient="records")
        except TypeError:
            records = None
        if records is not None:
            return [dict(row) for row in records]
    return []


_STATUS_ROW_FIELDS = {
    "market_code",
    "trade_date",
    "preclose",
    "high_limited",
    "low_limited",
    "price_high_lmt_rate",
    "price_low_lmt_rate",
    "is_st_sec",
    "is_susp_sec",
    "is_wd_sec",
    "is_xr_sec",
}


def _status_table_members(payload: Any) -> list[tuple[Any | None, Any]]:
    """Return status payload members without exposing table keys."""

    if isinstance(payload, dict) and not any(
        str(key).casefold() in _STATUS_ROW_FIELDS for key in payload
    ):
        return list(payload.items())
    return [(None, payload)]


_STATUS_IDENTITY_FIELDS = {
    "provider_symbol",
    "security_code",
    "market_code",
    "code",
    "market",
    "value",
}
_STATUS_EMPTY_MEMBER_UNRESOLVED = "STATUS_MEMBER_EMPTY_OR_NULL_WITHOUT_QUALIFIED_KEY"


def _status_outer_symbol(table_key: Any) -> str:
    """Return a qualified outer key only when the key proves a symbol."""

    raw_key = str(table_key or "").strip()
    if "." not in raw_key:
        return ""
    symbol = provider_symbol({"MARKET_CODE": raw_key})
    return symbol if "." in symbol else ""


def _status_identity_value_present(value: Any) -> bool:
    """Treat null-like identity cells as absent without normalizing values."""

    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return not (isinstance(value, float) and value != value)  # NaN from a frame cell


def _status_row_has_identity_value(row: dict[str, Any]) -> bool:
    return any(
        str(key).casefold() in _STATUS_IDENTITY_FIELDS and _status_identity_value_present(value)
        for key, value in row.items()
    )


def _status_member_rows(member: Any) -> list[dict[str, Any]]:
    """Flatten one status member without interpreting its outer table key."""

    try:
        return key_preserving_table_rows(member)
    except ProviderRowShapeError as exc:
        raise ProviderRowShapeError(str(exc), view="status_keyed_table_rows") from exc


def _status_attach_table_identity(row: dict[str, Any], symbol: str) -> dict[str, Any]:
    """Use a valid status table key while checking any embedded identity."""

    embedded = provider_symbol(row)
    if embedded:
        embedded_code = embedded.split(".", 1)[0]
        if embedded != symbol and embedded_code != symbol.split(".", 1)[0]:
            raise ProviderRowShapeError(
                "status keyed table identity conflict between outer key and row",
                view="status_keyed_table_rows",
            )
    elif _status_row_has_identity_value(row):
        raise ProviderRowShapeError(
            "status keyed table row has ambiguous embedded identity",
            view="status_keyed_table_rows",
        )
    canonical = dict(row)
    canonical["PROVIDER_SYMBOL"] = symbol
    canonical["_TABLE_KEY"] = symbol
    return canonical


def _status_table_member_rows(
    table_key: Any | None,
    member: Any,
) -> tuple[list[dict[str, Any]], collections.Counter[str]]:
    """Materialize a status member with a status-specific key boundary."""

    symbol = _status_outer_symbol(table_key)
    member_rows = _status_member_rows(member)
    if not symbol:
        if not member_rows:
            return [], collections.Counter({_STATUS_EMPTY_MEMBER_UNRESOLVED: 1})
        # A non-qualified outer key is deliberately ignored.  Native row
        # identity/date fields must be adjudicated by canonical_status_view.
        return member_rows, collections.Counter()
    if not member_rows:
        return [
            {
                "PROVIDER_SYMBOL": symbol,
                "_TABLE_KEY": symbol,
                "_TABLE_NONE": member is None,
                "_TABLE_EMPTY": member is not None,
            }
        ], collections.Counter()
    return [
        _status_attach_table_identity(row, symbol) for row in member_rows
    ], collections.Counter()


def _status_keyed_table_rows(
    payload: Any,
) -> tuple[list[dict[str, Any]], collections.Counter[str]]:
    """Flatten status tables without applying the K-line outer-key contract."""

    members = _status_table_members(payload)
    if not members:
        return [], collections.Counter({_STATUS_EMPTY_MEMBER_UNRESOLVED: 1})
    rows: list[dict[str, Any]] = []
    unresolved: collections.Counter[str] = collections.Counter()
    for table_key, member in members:
        member_rows, member_unresolved = _status_table_member_rows(table_key, member)
        rows.extend(member_rows)
        unresolved.update(member_unresolved)
    return rows, unresolved


def _status_shape_code(error_text: str) -> str:
    """Map a shape exception to a stable, value-free diagnostic code."""

    folded = error_text.casefold()
    if "conflict" in folded:
        return "STATUS_IDENTITY_CONFLICT"
    if "identity" in folded or "mapping key" in folded or "ambiguous" in folded:
        return "STATUS_IDENTITY_MISSING_OR_AMBIGUOUS"
    if "trade_date" in folded or "date" in folded:
        return "STATUS_DATE_MISSING_OR_INVALID"
    return "STATUS_OTHER_SHAPE"


def _status_shape_diagnostics(
    payload: Any,
    *,
    declared_rows: int,
    declared_table_count: int,
) -> dict[str, Any]:
    """Count status shape failures from sealed bytes without emitting values."""

    counts: collections.Counter[str] = collections.Counter()
    unresolved_counts: collections.Counter[str] = collections.Counter()
    affected_tables: dict[str, set[int]] = collections.defaultdict(set)

    def record_failure(error_text: str, table_index: int, row_count: int = 1) -> None:
        code = _status_shape_code(error_text)
        counts[code] += row_count
        affected_tables[code].add(table_index)

    def record_unresolved(code: str, table_index: int, member_count: int = 1) -> None:
        unresolved_counts[code] += member_count
        affected_tables[code].add(table_index)

    def inspect_rows(rows: list[dict[str, Any]], table_index: int) -> None:
        for row in rows:
            try:
                canonical_status_view([row])
            except ProviderRowShapeError as exc:
                record_failure(str(exc), table_index)

    members = _status_table_members(payload)
    if not members:
        record_unresolved(_STATUS_EMPTY_MEMBER_UNRESOLVED, 0)
    for table_index, (table_key, member) in enumerate(members):
        try:
            preserved_rows, member_unresolved = _status_table_member_rows(table_key, member)
        except ProviderRowShapeError as exc:
            try:
                raw_rows = _status_member_rows(member)
            except ProviderRowShapeError:
                raw_rows = []
            if not raw_rows:
                record_failure(str(exc), table_index)
                continue
            # Re-run one member at a time so one conflicting row does not hide
            # the deterministic count of other rows in the same table.
            for raw_row in raw_rows:
                try:
                    one_row, one_unresolved = _status_table_member_rows(table_key, [raw_row])
                except ProviderRowShapeError as row_exc:
                    record_failure(str(row_exc), table_index)
                else:
                    for code, count in one_unresolved.items():
                        record_unresolved(code, table_index, count)
                    inspect_rows(one_row, table_index)
        else:
            for code, count in member_unresolved.items():
                record_unresolved(code, table_index, count)
            inspect_rows(preserved_rows, table_index)

    all_subreason_counts = collections.Counter(counts)
    all_subreason_counts.update(unresolved_counts)
    subreasons = [
        {
            "code": code,
            "affected_row_count": counts[code],
            "affected_member_count": unresolved_counts[code],
            "affected_table_count": len(affected_tables[code]),
        }
        for code in sorted(all_subreason_counts)
    ]
    return {
        "shape_diagnostics": {
            "declared_row_count": declared_rows,
            "declared_table_count": declared_table_count,
            "affected_row_count": sum(counts.values()),
            "unresolved_member_count": sum(unresolved_counts.values()),
            "affected_table_count": len(
                {index for indexes in affected_tables.values() for index in indexes}
            ),
            "subreasons": subreasons,
        }
    }


def _ca_schema_diagnostics(
    stream: str,
    payload: Any,
    *,
    declared_rows: int,
    declared_table_count: int,
) -> dict[str, Any]:
    """Describe a CA contract failure using field names and counts only."""

    contract = CA_PROVIDER_FIELD_CONTRACT[stream]
    required_fields = [contract["code"], contract["ex_date"]]
    rows = _rows(payload)
    columns = _payload_columns(payload)
    missing_field_rows: collections.Counter[str] = collections.Counter()
    invalid_field_rows: collections.Counter[str] = collections.Counter()
    affected_rows = 0

    for row in rows:
        missing = {field for field in required_fields if row.get(field) is None}
        invalid: set[str] = set()
        for field in required_fields:
            raw_value = row.get(field)
            if field in missing:
                continue
            if field == contract["code"]:
                if not provider_symbol({"MARKET_CODE": raw_value}).split(".", 1)[0]:
                    invalid.add(field)
            elif not date_key(raw_value):
                invalid.add(field)
        for field in missing:
            missing_field_rows[field] += 1
        for field in invalid:
            invalid_field_rows[field] += 1
        if missing or invalid:
            affected_rows += 1

    missing_columns = set(required_fields) - columns if columns is not None and not rows else set()
    missing_fields = sorted(set(missing_field_rows) | missing_columns)
    invalid_fields = sorted(set(invalid_field_rows) - set(missing_fields))
    affected_table_count = declared_table_count if missing_columns else (1 if affected_rows else 0)
    return {
        "stream": stream,
        "documented_contract_fields": sorted(required_fields),
        "missing_documented_fields": missing_fields,
        "invalid_documented_fields": invalid_fields,
        "missing_field_row_counts": dict(sorted(missing_field_rows.items())),
        "invalid_field_row_counts": dict(sorted(invalid_field_rows.items())),
        "affected_row_count": affected_rows,
        "affected_table_count": affected_table_count,
        "declared_row_count": declared_rows,
        "declared_table_count": declared_table_count,
    }


def _scalar_values(payload: Any) -> list[Any]:
    return [row["value"] for row in _rows(payload) if set(row) == {"value"}]


def _old_summary(case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    results = collections.Counter(str(row.get("result", "")) for row in case_rows)
    reasons = collections.Counter(str(row.get("reason_code", "")) for row in case_rows)
    return {
        "case_count": len(case_rows),
        "result_counts": dict(sorted(results.items())),
        "reason_counts": dict(sorted(reasons.items())),
    }


def _result_name(result: Any) -> str:
    return str(getattr(result, "value", result))


def _outcome_summary(outcomes: list[ValidationOutcome]) -> dict[str, Any]:
    results = collections.Counter(_result_name(outcome.result) for outcome in outcomes)
    reasons = collections.Counter(str(outcome.reason_code or "") for outcome in outcomes)
    summary = {
        "case_count": len(outcomes),
        "result_counts": dict(sorted(results.items())),
        "reason_counts": dict(sorted(reasons.items())),
    }
    if len(results) == 1:
        summary["result"] = next(iter(results))
    return summary


def _outcome_replay(
    outcome: ValidationOutcome,
    classification: str,
    *,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    replay = {
        "classification": classification,
        "result": _result_name(outcome.result),
        "reason_codes": [str(outcome.reason_code)] if outcome.reason_code else [],
    }
    if facts:
        replay.update(facts)
    return replay


def _shape_replay(
    view: str,
    reason_code: str,
    error_text: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    replay = {
        "classification": "REPLAY_PROVIDER_SHAPE_BLOCKED",
        "result": _result_name(CaseResult.VALIDATED_FAIL),
        "reason_codes": [reason_code],
        "view": view,
    }
    match = re.search(r"(?:row|index)\s+(\d+)", error_text)
    if match:
        replay["row_ordinal"] = int(match.group(1))
    if details:
        replay.update(details)
    return replay


def _status_unresolved_replay(
    payload: Any,
    *,
    declared_rows: int,
    declared_table_count: int,
    unresolved: collections.Counter[str],
) -> dict[str, Any]:
    """Keep unkeyed empty status members unresolved instead of fabricating rows."""

    return {
        "classification": "REPLAY_UNRESOLVED_PROVIDER_SHAPE",
        "result": _result_name(CaseResult.MISSING),
        "reason_codes": sorted(unresolved),
        "view": "status_keyed_table_rows",
        **_status_shape_diagnostics(
            payload,
            declared_rows=declared_rows,
            declared_table_count=declared_table_count,
        ),
    }


def _case_rows_by_type(
    catalog_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in catalog_rows:
        grouped[str(row.get("case_type", ""))].append(row)
    return dict(grouped)


def _one_case(
    grouped: dict[str, list[dict[str, Any]]],
    case_type: str,
    *,
    contains: str = "",
) -> dict[str, Any]:
    candidates = grouped.get(case_type, [])
    if contains:
        candidates = [row for row in candidates if contains in str(row.get("case_id", ""))]
    if len(candidates) != 1:
        raise RuntimeError(f"expected one {case_type} case, got {len(candidates)}")
    return candidates[0]


def _add_capability(
    records: list[dict[str, Any]],
    *,
    stage: str,
    capability: str,
    old_rows: list[dict[str, Any]],
    replay: dict[str, Any],
    evidence: list[str] | None = None,
    note: str = "",
) -> None:
    record: dict[str, Any] = {
        "stage": stage,
        "capability": capability,
        "case_types": sorted(
            {str(row.get("case_type", "")) for row in old_rows if str(row.get("case_type", ""))}
        ),
        "old_recorded": _old_summary(old_rows),
        "replay": replay,
        "evidence": sorted(set(evidence or [])),
    }
    if note:
        record["note"] = note
    records.append(record)


def _replay_result_counts(replay: dict[str, Any]) -> collections.Counter[str]:
    counts: collections.Counter[str] = collections.Counter()
    raw_counts = replay.get("result_counts")
    if isinstance(raw_counts, dict):
        for result, count in raw_counts.items():
            try:
                counts[str(result)] += int(count)
            except (TypeError, ValueError):
                continue
    if not counts and replay.get("result"):
        counts[str(replay["result"])] = 1
    return counts


def _core_capability_projection(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Project replay records onto the frozen multi-case core contract."""

    records_by_case_type: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for record in records:
        for case_type in record.get("case_types", []):
            records_by_case_type[str(case_type)].append(record)

    unresolved_results = {
        "MISSING",
        "NOT_RUN_OFFLINE",
        "NOT_TESTABLE_PERMISSION",
        "OBSERVED",
        "OBSERVED_ONLY",
    }
    valid_results = {"VALIDATED_PASS", "DIFF_EXPLAINED"}
    projected: list[dict[str, Any]] = []

    for definition in CORE_CAPABILITIES:
        required: list[dict[str, Any]] = []
        replayed_case_types: list[str] = []
        absent_case_types: list[str] = []
        capability_results: collections.Counter[str] = collections.Counter()
        capability_reasons: set[str] = set()
        has_failed = False
        has_deferred_fixture = False
        all_minimums_met = True

        for case_type in definition.required_case_types:
            case_records = records_by_case_type.get(case_type, [])
            minimum = int(definition.required_case_counts[case_type])
            if not case_records:
                absent_case_types.append(case_type)
                all_minimums_met = False
                required.append(
                    {
                        "case_type": case_type,
                        "required_minimum": minimum,
                        "presence": "ABSENT",
                        "replay_record_count": 0,
                        "replay_case_count": 0,
                        "replay_valid_count": 0,
                        "replay_result_counts": {},
                        "replay_classifications": [],
                        "reason_codes": ["REPLAY_REQUIRED_CASE_TYPE_ABSENT"],
                    }
                )
                capability_reasons.add("REPLAY_REQUIRED_CASE_TYPE_ABSENT")
                continue

            replayed_case_types.append(case_type)
            case_counts: collections.Counter[str] = collections.Counter()
            classifications: set[str] = set()
            reasons: set[str] = set()
            for record in case_records:
                replay = record.get("replay", {})
                case_counts.update(_replay_result_counts(replay))
                classification = str(replay.get("classification", ""))
                if classification:
                    classifications.add(classification)
                reasons.update(str(code) for code in replay.get("reason_codes", []) if code)
                reason_counts = replay.get("reason_counts")
                if isinstance(reason_counts, dict):
                    reasons.update(str(code) for code in reason_counts if code)
                has_deferred_fixture |= bool(replay.get("deferred_fixture"))
            valid_count = sum(case_counts[result] for result in valid_results)
            capability_results.update(case_counts)
            has_failed |= "VALIDATED_FAIL" in case_counts
            if valid_count < minimum:
                all_minimums_met = False
            capability_reasons.update(reasons)
            required.append(
                {
                    "case_type": case_type,
                    "required_minimum": minimum,
                    "presence": "REPLAYED",
                    "replay_record_count": len(case_records),
                    "replay_case_count": sum(case_counts.values()),
                    "replay_valid_count": valid_count,
                    "replay_result_counts": dict(sorted(case_counts.items())),
                    "replay_classifications": sorted(classifications),
                    "reason_codes": sorted(reasons),
                }
            )

        if absent_case_types:
            status = "MISSING"
        elif has_failed:
            status = "FAILED"
        elif definition.capability_id == "history_start_2020" and has_deferred_fixture:
            capability_reasons.add("HISTORICAL_DELISTED_FIXTURE_DEFERRED")
            status = "UNRESOLVED"
        elif (
            any(result in unresolved_results for result in capability_results)
            or not all_minimums_met
        ):
            status = "UNRESOLVED"
        else:
            status = "PASS"

        if definition.capability_id == "symbol_mapping_unambiguous" and "golden_bj_mapping" in (
            absent_case_types
        ):
            capability_reasons.add("BJ_SEMANTIC_MAPPING_NOT_PROVEN")
        projected.append(
            {
                "capability_id": definition.capability_id,
                "required_case_types": list(definition.required_case_types),
                "required_case_counts": {
                    case_type: int(definition.required_case_counts[case_type])
                    for case_type in definition.required_case_types
                },
                "replayed_case_types": replayed_case_types,
                "absent_case_types": absent_case_types,
                "case_type_details": required,
                "replay_result_counts": dict(sorted(capability_results.items())),
                "replay_status": status,
                "replay_classification": f"REPLAY_CORE_{status}",
                "reason_codes": sorted(capability_reasons),
            }
        )

    return {
        "diagnostic_only": True,
        "contract_source": "ashare_state.spike.capabilities.CORE_CAPABILITIES",
        "capabilities": projected,
    }


def _observe_units(rows: list[dict[str, Any]]) -> tuple[dict[str, str], int, int]:
    checked = 0
    consistent = 0
    for row in canonical_daily_bar_view(rows):
        try:
            close = float(row.get("CLOSE_PRICE") or 0)
            volume = float(row.get("VOLUME") or 0)
            amount = float(row.get("AMOUNT") or 0)
        except (TypeError, ValueError):
            continue
        if close > 0 and volume > 0 and amount > 0:
            checked += 1
            if abs(amount / volume - close) / close <= 0.15:
                consistent += 1
    if checked and consistent / checked >= 0.9:
        return {"volume": "shares", "amount": "CNY"}, checked, consistent
    return {"volume": "UNDETERMINED", "amount": "UNDETERMINED"}, checked, consistent


def _replay_core(
    reader: EvidenceReader,
    grouped: dict[str, list[dict[str, Any]]],
    rule_book: Any,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    _add_capability(
        records,
        stage="B1",
        capability="formal_runtime_gate",
        old_rows=grouped.get("formal_runtime_gate", []),
        replay={
            "classification": "REPLAY_NOT_APPLICABLE_OFFLINE",
            "result": "NOT_RUN_OFFLINE",
            "reason_codes": ["SDK_RUNTIME_ACCOUNT_GATE_NOT_REEXECUTED"],
        },
        note=(
            "B1 is recorded from the sealed catalog; this lane does not re-run "
            "SDK/runtime/account gates."
        ),
    )

    security_case = _one_case(grouped, "security_master_with_delisted")
    security = reader.read_ref(str(security_case["evidence_ref"]))
    security_rows = _rows(security.payload)
    security_outcome = validate_security_master_delisted(security_rows)
    _add_capability(
        records,
        stage="B2",
        capability="security_master_with_delisted",
        old_rows=[security_case],
        replay=_outcome_replay(
            security_outcome,
            "REPLAY_SEMANTIC_MISSING",
            facts={
                "value_only_rows": sum(set(row) == {"value"} for row in security_rows),
                "rows_without_delisted_semantic_fields": len(security_rows),
                "required_delisted_semantic_fields": ["IS_LISTED", "DELISTING_DATE"],
                "declared_table_count": int(security.anchor["table_count"]),
            },
        ),
        evidence=[security.anchor["logical_path"]],
        note="Historical-code membership does not prove IS_LISTED=3 or DELISTING_DATE.",
    )

    daily_case = _one_case(grouped, "daily_bar_units")
    daily = reader.read_ref(str(daily_case["evidence_ref"]))
    try:
        daily_rows = canonical_daily_bar_view(key_preserving_table_rows(daily.payload))
    except ProviderRowShapeError as exc:
        daily_replay = _shape_replay(
            "key_preserving_table_rows",
            "PROVIDER_KLINE_SHAPE",
            str(exc),
        )
    else:
        observed_units, checked, consistent = _observe_units(daily_rows)
        daily_outcome = validate_daily_bar_units(
            daily_rows,
            documented_units={"volume": "shares", "amount": "CNY"},
            observed_units=observed_units,
        )
        daily_replay = _outcome_replay(
            daily_outcome,
            "REPLAY_VALIDATED_PASS"
            if _result_name(daily_outcome.result) == "VALIDATED_PASS"
            else "REPLAY_SEMANTIC_MISMATCH",
            facts={
                "rows_after_key_preserving_view": len(daily_rows),
                "unit_checked_rows": checked,
                "unit_consistent_rows": consistent,
            },
        )
    _add_capability(
        records,
        stage="B3",
        capability="daily_bar_units",
        old_rows=[daily_case],
        replay=daily_replay,
        evidence=[daily.anchor["logical_path"]],
        note=(
            "The repaired keyed-table and lowercase-field path reaches the "
            "independent amount/volume check."
        ),
    )

    status_case = _one_case(grouped, "historical_st_suspend")
    status = reader.read_ref(str(status_case["evidence_ref"]))
    try:
        status_rows, status_unresolved = _status_keyed_table_rows(status.payload)
        if status_unresolved:
            status_replay = _status_unresolved_replay(
                status.payload,
                declared_rows=int(status.anchor["declared_rows"]),
                declared_table_count=int(status.anchor["table_count"]),
                unresolved=status_unresolved,
            )
        else:
            canonical_status_rows = canonical_status_view(status_rows)
    except ProviderRowShapeError as exc:
        status_replay = _shape_replay(
            exc.view,
            "PROVIDER_STATUS_SHAPE",
            str(exc),
            details=_status_shape_diagnostics(
                status.payload,
                declared_rows=int(status.anchor["declared_rows"]),
                declared_table_count=int(status.anchor["table_count"]),
            ),
        )
    else:
        if not status_unresolved:
            status_outcome = validate_st_suspend_flags(canonical_status_rows, golden_facts=[])
            status_replay = _outcome_replay(
                status_outcome,
                "REPLAY_STRUCTURAL_ONLY",
                facts={"canonical_rows": len(canonical_status_rows)},
            )
    _add_capability(
        records,
        stage="B3",
        capability="historical_st_suspend",
        old_rows=[status_case],
        replay=status_replay,
        evidence=[status.anchor["logical_path"]],
        note=(
            "Status table keys are preserved before canonicalization; any remaining "
            "shape failure is reported with value-free identity/date subreasons."
        ),
    )

    limit_sample = _one_case(
        grouped,
        "limit_price_and_no_limit_days",
        contains="-SAMPLE-",
    )
    limit_status = reader.read_ref(str(limit_sample["evidence_ref"]))
    try:
        limit_rows, limit_unresolved = _status_keyed_table_rows(limit_status.payload)
        if limit_unresolved:
            limit_replay = _status_unresolved_replay(
                limit_status.payload,
                declared_rows=int(limit_status.anchor["declared_rows"]),
                declared_table_count=int(limit_status.anchor["table_count"]),
                unresolved=limit_unresolved,
            )
        else:
            limit_rows = canonical_status_view(limit_rows)
    except ProviderRowShapeError as exc:
        limit_replay = _shape_replay(
            exc.view,
            "PROVIDER_STATUS_SHAPE",
            str(exc),
            details=_status_shape_diagnostics(
                limit_status.payload,
                declared_rows=int(limit_status.anchor["declared_rows"]),
                declared_table_count=int(limit_status.anchor["table_count"]),
            ),
        )
    else:
        if not limit_unresolved:
            from ashare_state.spike.validators import validate_limit_rule

            limit_outcome = validate_limit_rule(limit_rows, book=rule_book)
            limit_replay = _outcome_replay(
                limit_outcome,
                "REPLAY_VALIDATED_PASS"
                if _result_name(limit_outcome.result) == "VALIDATED_PASS"
                else "REPLAY_SEMANTIC_MISMATCH",
                facts={"canonical_rows": len(limit_rows)},
            )
    _add_capability(
        records,
        stage="B3",
        capability="limit_price_and_no_limit_days.sample",
        old_rows=[limit_sample],
        replay=limit_replay,
        evidence=[limit_status.anchor["logical_path"]],
        note=(
            "Status table keys are preserved before rule arithmetic; any remaining "
            "shape failure is reported with value-free identity/date subreasons."
        ),
    )

    bse_case = _one_case(
        grouped,
        "limit_price_and_no_limit_days",
        contains="-BSE-",
    )
    bse = reader.read_ref(str(bse_case["evidence_ref"]))
    bse_rows = _rows(bse.payload)
    if not bse_rows:
        bse_replay = {
            "classification": "REPLAY_UNRESOLVED_PROVIDER_SEMANTICS",
            "result": _result_name(CaseResult.MISSING),
            "reason_codes": ["PROVIDER_EMPTY_STATUS_UNRESOLVED"],
            "empty_status": True,
            "declared_row_count": int(bse.anchor["declared_rows"]),
            "declared_table_count": int(bse.anchor["table_count"]),
        }
    else:
        bse_replay = {
            "classification": "REPLAY_SEMANTIC_REVIEW_REQUIRED",
            "result": "NOT_RUN_OFFLINE",
            "reason_codes": ["BSE_STATUS_NOT_EMPTY"],
        }
    _add_capability(
        records,
        stage="B3",
        capability="limit_price_and_no_limit_days.BSE",
        old_rows=[bse_case],
        replay=bse_replay,
        evidence=[bse.anchor["logical_path"]],
        note="Successful empty BSE status is intentionally not upgraded to a capability result.",
    )

    adj_case = _one_case(grouped, "adj_factor_corporate_action_continuity")
    adj = reader.read_ref(str(adj_case["evidence_ref"]))
    adj_outcome = validate_adj_continuity(_rows(adj.payload))
    _add_capability(
        records,
        stage="B3",
        capability="adj_factor_corporate_action_continuity",
        old_rows=[adj_case],
        replay=_outcome_replay(
            adj_outcome,
            "REPLAY_STRUCTURAL_ONLY",
            facts={"price_context_supplied": False},
        ),
        evidence=[adj.anchor["logical_path"]],
        note=(
            "The old evidence contains adjustment rows but no price context; "
            "continuity stays deferred."
        ),
    )

    sdk_case = _one_case(grouped, "sdk_permission_cache_freshness")
    sdk = reader.read_ref(str(sdk_case["evidence_ref"]))
    calendar_days = _calendar_days(sdk.payload)
    _add_capability(
        records,
        stage="B5",
        capability="sdk_permission_cache_freshness",
        old_rows=[sdk_case],
        replay={
            "classification": "REPLAY_NOT_APPLICABLE_OFFLINE",
            "result": "NOT_RUN_OFFLINE",
            "reason_codes": ["ACCOUNT_PERMISSION_IDENTITY_NOT_REEXECUTED"],
            "calendar_days_read": len(calendar_days),
        },
        evidence=[sdk.anchor["logical_path"]],
        note=(
            "Calendar bytes are readable, but account permission/cache behavior "
            "requires the live target."
        ),
    )

    history_case = _one_case(grouped, "history_start_2020")
    history = reader.read_ref(str(history_case["evidence_ref"]))
    try:
        history_rows = canonical_daily_bar_view(key_preserving_table_rows(history.payload))
    except ProviderRowShapeError as exc:
        history_replay = _shape_replay(
            "key_preserving_table_rows",
            "PROVIDER_KLINE_SHAPE",
            str(exc),
        )
    else:
        earliest_by_symbol: dict[str, str] = {}
        for row in history_rows:
            symbol = str(row.get("PROVIDER_SYMBOL") or "").upper()
            day = date_key(row.get("TRADE_DATE"))
            if (
                symbol
                and day
                and (symbol not in earliest_by_symbol or day < earliest_by_symbol[symbol])
            ):
                earliest_by_symbol[symbol] = day
        history_outcome = validate_history_coverage_by_symbol(
            earliest_by_symbol,
            expected_symbols=["600519.SH", "000001.SZ", "835185.BJ"],
            calendar_days=calendar_days,
            applicable_from_by_symbol={"835185.BJ": "20211115"},
        )
        history_replay = _outcome_replay(
            history_outcome,
            "REPLAY_VALIDATED_PASS"
            if _result_name(history_outcome.result) == "VALIDATED_PASS"
            else "REPLAY_SEMANTIC_MISMATCH",
            facts={
                "covered_fixture_count": len(
                    set(earliest_by_symbol).intersection({"600519.SH", "000001.SZ", "835185.BJ"})
                ),
                "deferred_fixture": "300104.SZ",
            },
        )
    _add_capability(
        records,
        stage="B5",
        capability="history_start_2020",
        old_rows=[history_case],
        replay=history_replay,
        evidence=[history.anchor["logical_path"], sdk.anchor["logical_path"]],
        note=(
            "Three explicit fixtures pass at their first applicable session; "
            "300104.SZ remains deferred."
        ),
    )

    mapping_case = _one_case(grouped, "symbol_mapping_unambiguous")
    mapping = reader.read_ref(str(mapping_case["evidence_ref"]))
    mapping_values = [str(value) for value in _scalar_values(mapping.payload)]
    mapping_outcome = validate_symbol_mapping(mapping_values)
    _add_capability(
        records,
        stage="B5",
        capability="symbol_mapping_unambiguous",
        old_rows=[mapping_case],
        replay=_outcome_replay(
            mapping_outcome,
            "REPLAY_VALIDATED_PASS"
            if _result_name(mapping_outcome.result) == "VALIDATED_PASS"
            else "REPLAY_SEMANTIC_MISMATCH",
            facts={"scalar_values_read": len(mapping_values)},
        ),
        evidence=[mapping.anchor["logical_path"]],
    )

    free_float = _one_case(grouped, "free_float_equivalence")
    taxonomy = _one_case(grouped, "sw_taxonomy")
    optional = reader.read_ref(str(free_float["evidence_ref"]))
    optional_replay = {
        "classification": "REPLAY_STRUCTURAL_ONLY",
        "result": "OBSERVED_ONLY",
        "reason_codes": ["OPTIONAL_SEMANTIC_CHECK_NOT_REEXECUTED"],
        "rows_read": len(_rows(optional.payload)),
    }
    _add_capability(
        records,
        stage="B6",
        capability="free_float_equivalence",
        old_rows=[free_float],
        replay=optional_replay,
        evidence=[optional.anchor["logical_path"]],
        note="The old B6 path recorded shape only; no offline equivalence claim is added.",
    )
    _add_capability(
        records,
        stage="B6",
        capability="sw_taxonomy",
        old_rows=[taxonomy],
        replay=dict(optional_replay),
        evidence=[optional.anchor["logical_path"]],
        note="Taxonomy owner still requires live endpoint/semantic review.",
    )

    benchmark_case = _one_case(grouped, "benchmark_index_availability")
    benchmark = reader.read_ref(str(benchmark_case["evidence_ref"]))
    _add_capability(
        records,
        stage="B6",
        capability="benchmark_index_availability",
        old_rows=[benchmark_case],
        replay={
            "classification": "REPLAY_STRUCTURAL_ONLY",
            "result": "OBSERVED_ONLY",
            "reason_codes": ["INDEX_SEMANTIC_CHECK_NOT_REEXECUTED"],
            "rows_read": len(_rows(benchmark.payload)),
        },
        evidence=[benchmark.anchor["logical_path"]],
    )

    capacity_case = _one_case(grouped, "capacity_backfill")
    capacity = reader.read_ref(
        str(capacity_case["evidence_ref"]),
        load_payload=False,
    )
    _add_capability(
        records,
        stage="B7",
        capability="capacity_backfill",
        old_rows=[capacity_case],
        replay={
            "classification": "REPLAY_NOT_APPLICABLE_OFFLINE",
            "result": "NOT_RUN_OFFLINE",
            "reason_codes": ["CAPACITY_TIMING_METRICS_NOT_IN_RAW_PAYLOAD"],
            "declared_rows": capacity.anchor["declared_rows"],
            "declared_table_count": capacity.anchor["table_count"],
        },
        evidence=[capacity.anchor["logical_path"]],
        note=(
            "Only immutable raw metadata was checked; no backfill loop or timing "
            "measurement was run."
        ),
    )
    return records


def _replay_golden(
    reader: EvidenceReader,
    grouped: dict[str, list[dict[str, Any]]],
    rule_book: Any,
    golden_cases: list[Any],
) -> list[dict[str, Any]]:
    cases_by_type: dict[str, list[Any]] = collections.defaultdict(list)
    for case in golden_cases:
        cases_by_type[case.case_type].append(case)
    records: list[dict[str, Any]] = []

    for case_type, bundle_name in GOLDEN_BUNDLES.items():
        loaded, _bundle_anchor = reader.read_bundle(bundle_name)
        cases = cases_by_type[case_type]
        evidence = [item.anchor["logical_path"] for item in loaded]
        shape_failure: ProviderRowShapeError | None = None
        shape_source = ""
        shape_payload: Any = None
        shape_anchor: dict[str, Any] | None = None
        status_unresolved: collections.Counter[str] = collections.Counter()
        ca_failure = False
        ca_stream = ""
        ca_schema_details: list[dict[str, Any]] = []
        data: DomainData | None = None

        if case_type == "golden_st_transition":
            status = next(
                item.payload
                for item in loaded
                if item.meta.get("provider_dataset") == "history_stock_status"
            )
            try:
                shape_source = "status"
                shape_payload = status
                shape_anchor = next(
                    item.anchor
                    for item in loaded
                    if item.meta.get("provider_dataset") == "history_stock_status"
                )
                status_rows, status_unresolved = _status_keyed_table_rows(status)
                if not status_unresolved:
                    data = DomainData(
                        domain="ST_STATUS",
                        status_rows=canonical_status_view(status_rows),
                    )
            except ProviderRowShapeError as exc:
                shape_failure = exc

        elif case_type == "golden_delisted":
            hist = next(
                item.payload
                for item in loaded
                if item.meta.get("provider_dataset") == "hist_code_list"
            )
            basic = next(
                item.payload
                for item in loaded
                if item.meta.get("provider_dataset") == "stock_basic"
            )
            data = DomainData(
                domain="DELISTED_MASTER",
                hist_code_rows=_rows(hist),
                stock_basic_rows=_rows(basic),
            )

        elif case_type == "golden_limit_regime":
            status = next(
                item.payload
                for item in loaded
                if item.meta.get("provider_dataset") == "history_stock_status"
            )
            hist = next(
                item.payload
                for item in loaded
                if item.meta.get("provider_dataset") == "hist_code_list"
            )
            calendar = next(
                item.payload
                for item in loaded
                if item.meta.get("provider_dataset") == "trade_calendar"
            )
            try:
                shape_source = "status"
                shape_payload = status
                shape_anchor = next(
                    item.anchor
                    for item in loaded
                    if item.meta.get("provider_dataset") == "history_stock_status"
                )
                status_rows, status_unresolved = _status_keyed_table_rows(status)
                if not status_unresolved:
                    data = DomainData(
                        domain="LIMIT_PIT_RULE",
                        status_rows=canonical_status_view(status_rows),
                        hist_code_rows=_rows(hist),
                        calendar_days=_calendar_days(calendar),
                    )
            except ProviderRowShapeError as exc:
                shape_failure = exc

        elif case_type == "golden_corporate_action":
            status = next(
                item.payload
                for item in loaded
                if item.meta.get("provider_dataset") == "history_stock_status"
            )
            adj = next(
                item.payload for item in loaded if item.meta.get("provider_dataset") == "adj_factor"
            )
            calendar = next(
                item.payload
                for item in loaded
                if item.meta.get("provider_dataset") == "trade_calendar"
            )
            kline = next(
                item.payload for item in loaded if item.meta.get("provider_dataset") == "daily_bar"
            )
            try:
                shape_source = "status"
                shape_payload = status
                shape_anchor = next(
                    item.anchor
                    for item in loaded
                    if item.meta.get("provider_dataset") == "history_stock_status"
                )
                status_rows, status_unresolved = _status_keyed_table_rows(status)
                if not status_unresolved:
                    status_rows = canonical_status_view(status_rows)
                dividend_rows: list[dict[str, Any]] = []
                right_issue_rows: list[dict[str, Any]] = []
                for item in loaded:
                    if item.meta.get("provider_dataset") != "corporate_action":
                        continue
                    endpoint = str(item.meta.get("endpoint", ""))
                    stream = (
                        "right_issue"
                        if "get_right_issue" in endpoint
                        else "dividend"
                        if "get_dividend" in endpoint
                        else ""
                    )
                    if not stream:
                        raise RuntimeError("corporate-action endpoint stream is unresolved")
                    ca_stream = stream
                    try:
                        view = _ca_provider_view(
                            stream,
                            _rows(item.payload),
                            source_endpoint=endpoint,
                            raw_request_id=str(item.meta["request_id"]),
                            payload_columns=_payload_columns(item.payload),
                        )
                    except CAProviderShapeError:
                        ca_schema_details.append(
                            _ca_schema_diagnostics(
                                stream,
                                item.payload,
                                declared_rows=int(item.anchor["declared_rows"]),
                                declared_table_count=int(item.anchor["table_count"]),
                            )
                        )
                        continue
                    if stream == "right_issue":
                        right_issue_rows.extend(view)
                    else:
                        dividend_rows.extend(view)
                if not ca_schema_details and not status_unresolved:
                    shape_source = "kline"
                    shape_payload = kline
                    data = DomainData(
                        domain="CORP_ACTION_CONTEXT",
                        status_rows=status_rows,
                        adj_rows=_rows(adj),
                        dividend_rows=dividend_rows,
                        right_issue_rows=right_issue_rows,
                        kline_rows=key_preserving_table_rows(kline),
                        calendar_days=_calendar_days(calendar),
                    )
                else:
                    ca_failure = True
            except ProviderRowShapeError as exc:
                shape_failure = exc

        if status_unresolved:
            replay = _status_unresolved_replay(
                shape_payload,
                declared_rows=int((shape_anchor or {}).get("declared_rows", 0)),
                declared_table_count=int((shape_anchor or {}).get("table_count", 0)),
                unresolved=status_unresolved,
            )
            replay["result_counts"] = {"MISSING": len(cases)}
            replay["reason_counts"] = {code: len(cases) for code in sorted(status_unresolved)}
            note = (
                "An empty/null status member without a qualified key remains unresolved; "
                "no status row is fabricated."
            )
        elif shape_failure is not None:
            view = getattr(shape_failure, "view", "provider_row")
            if shape_source == "status":
                reason = "PROVIDER_STATUS_SHAPE"
                details = _status_shape_diagnostics(
                    shape_payload,
                    declared_rows=int((shape_anchor or {}).get("declared_rows", 0)),
                    declared_table_count=int((shape_anchor or {}).get("table_count", 0)),
                )
            else:
                reason = (
                    "PROVIDER_KLINE_SHAPE"
                    if view == "key_preserving_table_rows"
                    else "PROVIDER_ROW_SHAPE"
                )
                details = None
            replay = _shape_replay(view, reason, str(shape_failure), details=details)
            replay["result_counts"] = {"VALIDATED_FAIL": len(cases)}
            replay["reason_counts"] = {reason: len(cases)}
            note = (
                "Key-preserving status identity was retained before canonicalization, but "
                "the sealed rows still fail closed on the reported shape subreason."
                if shape_source == "status"
                else "Canonical provider view rejected a native row before semantic comparison."
            )
        elif ca_failure:
            replay = {
                "classification": "REPLAY_PROVIDER_SCHEMA_BLOCKED",
                "result": _result_name(CaseResult.VALIDATED_FAIL),
                "reason_codes": ["PROVIDER_SCHEMA"],
                "failed_stream": ca_stream or "dividend_or_right_issue",
                "result_counts": {"VALIDATED_FAIL": len(cases)},
                "reason_counts": {"PROVIDER_SCHEMA": len(cases)},
                "schema_subreasons": ca_schema_details,
            }
            note = (
                "A corporate-action stream row lacks a documented contract field; "
                "raw content is intentionally omitted."
            )
        else:
            if data is None:
                raise RuntimeError(f"no replay domain data for {case_type}")
            outcomes = [validate_case_in_domain(case, data, rule_book=rule_book) for case in cases]
            summary = _outcome_summary(outcomes)
            replay = {
                "classification": (
                    "REPLAY_VALIDATED_OR_MIXED"
                    if any(_result_name(outcome.result) == "VALIDATED_PASS" for outcome in outcomes)
                    else "REPLAY_SEMANTIC_MISMATCH"
                ),
                **summary,
            }
            note = "Current merged validator path was reached for every case in this bundle."

        _add_capability(
            records,
            stage="B4",
            capability=case_type,
            old_rows=grouped.get(case_type, []),
            replay=replay,
            evidence=evidence,
            note=note,
        )
    return records


def _repo_binding_anchors(repo_root: Path, old_run: dict[str, Any]) -> dict[str, Any]:
    golden_root = repo_root / "data" / "golden" / "provider" / "amazingdata"
    rules_root = repo_root / "configs" / "trading_rules"
    golden_path = golden_root / str(old_run["golden_dataset_file"])
    golden_manifest = golden_root / "truth_manifest_v7.json"
    rule_manifest = rules_root / "rule_manifest.json"
    rule_file = rules_root / Path(str(old_run["trading_rule_dataset_files"][0]))
    return {
        "golden_dataset": {
            "logical_path": golden_path.relative_to(repo_root).as_posix(),
            "bytes": golden_path.stat().st_size,
            "sha256": _sha256_file(golden_path),
            "expected_sha256": SEALED_GOLDEN_SHA256,
        },
        "golden_manifest": {
            "logical_path": golden_manifest.relative_to(repo_root).as_posix(),
            "bytes": golden_manifest.stat().st_size,
            "sha256": _sha256_file(golden_manifest),
        },
        "trading_rule_manifest": {
            "logical_path": rule_manifest.relative_to(repo_root).as_posix(),
            "bytes": rule_manifest.stat().st_size,
            "sha256": _sha256_file(rule_manifest),
        },
        "trading_rule_dataset_file": {
            "logical_path": rule_file.relative_to(repo_root).as_posix(),
            "bytes": rule_file.stat().st_size,
            "sha256": _sha256_file(rule_file),
            "expected_manifest_hash": SEALED_RULE_DATASET_SHA256,
        },
    }


def _build_artifact(
    *,
    repo_root: Path,
    evidence_root: Path,
    replay_code_head: str,
) -> dict[str, Any]:
    before = _tree_anchor(evidence_root)
    run_metadata_path = evidence_root / "spike_run.json"
    verdict_path = evidence_root / "verdict.json"
    catalog_path = evidence_root / "cases" / "spike_case_catalog.jsonl"
    old_run = json.loads(run_metadata_path.read_text(encoding="utf-8"))
    if str(old_run.get("spike_run_id", "")) != SEALED_RUN_ID:
        raise RuntimeError("unexpected sealed run id")
    catalog_bytes = catalog_path.read_bytes()
    catalog_hash = hashlib.sha256(catalog_bytes).hexdigest()
    if catalog_hash != SEALED_CATALOG_SHA256:
        raise RuntimeError("sealed catalog hash mismatch")
    catalog_rows = [
        json.loads(line) for line in catalog_bytes.decode("utf-8").splitlines() if line.strip()
    ]
    if len(catalog_rows) != EXPECTED_CASE_COUNT:
        raise RuntimeError("unexpected sealed catalog case count")
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    grouped = _case_rows_by_type(catalog_rows)
    reader = EvidenceReader(evidence_root)

    golden_root = repo_root / "data" / "golden" / "provider" / "amazingdata"
    golden_store = GoldenTruthStore(root=golden_root)
    golden_cases, golden_manifest = golden_store.load_bound(
        dataset_file=str(old_run["golden_dataset_file"]),
        truth_version=str(old_run["golden_truth_version"]),
        dataset_hash=str(old_run["golden_dataset_hash"]),
    )
    rules_root = repo_root / "configs" / "trading_rules"
    rule_book = load_bound_rule_book(
        rule_version=str(old_run["trading_rule_version"]),
        dataset_files=list(old_run["trading_rule_dataset_files"]),
        dataset_hash=str(old_run["trading_rule_dataset_hash"]),
        dataset_version=str(old_run["trading_rule_dataset_version"]),
        source_version=str(old_run["trading_rule_source_version"]),
        review_status=str(old_run["trading_rule_review_status"]),
        rules_root=rules_root,
    )

    capabilities = _replay_core(reader, grouped, rule_book)
    capabilities.extend(_replay_golden(reader, grouped, rule_book, golden_cases))
    core_projection = _core_capability_projection(capabilities)
    after = _tree_anchor(evidence_root)
    if before != after:
        raise RuntimeError("sealed evidence tree changed during read-only replay")

    return {
        "artifact_kind": "REPLAY_DIAGNOSTIC",
        "artifact_schema": "formal-readonly-replay-v3",
        "source": {
            "sealed_run_id": SEALED_RUN_ID,
            "sealed_run_status": str(old_run.get("status", "")),
            "sealed_run_as_of_date": str(old_run.get("as_of_date", "")),
            "sealed_run_code_commit": str(old_run.get("code_commit", "")),
            "sealed_verdict": str(verdict.get("verdict", "")),
            "catalog_sha256": catalog_hash,
            "catalog_case_count": len(catalog_rows),
        },
        "replay_binding": {
            "replay_code_head": replay_code_head,
            "golden_truth_version": golden_manifest.truth_version,
            "golden_dataset_file": golden_manifest.dataset_file,
            "golden_dataset_sha256": golden_manifest.dataset_hash,
            "golden_case_count": golden_manifest.case_count,
            "trading_rule_version": str(old_run["trading_rule_version"]),
            "trading_rule_dataset_version": str(old_run["trading_rule_dataset_version"]),
            "trading_rule_dataset_sha256": str(old_run["trading_rule_dataset_hash"]),
            "trading_rule_review_status": str(old_run["trading_rule_review_status"]),
        },
        "read_only_controls": {
            "provider_calls": 0,
            "provider_sdk_target_constructed": False,
            "spike_run_created": False,
            "raw_writer_write_calls": 0,
            "catalog_write_calls": 0,
            "verdict_write_calls": 0,
            "sealed_evidence_tree_before": before,
            "sealed_evidence_tree_after": after,
            "sealed_evidence_tree_unchanged": before == after,
        },
        "read_counts": {
            "verified_meta_documents": reader.meta_read_count,
            "materialized_payloads": reader.payload_read_count,
            "anchors_emitted": len(reader.anchors),
        },
        "repo_binding_anchors": _repo_binding_anchors(repo_root, old_run),
        "sealed_run_file_anchors": {
            "spike_run.json": {
                "bytes": run_metadata_path.stat().st_size,
                "sha256": _sha256_file(run_metadata_path),
            },
            "verdict.json": {
                "bytes": verdict_path.stat().st_size,
                "sha256": _sha256_file(verdict_path),
            },
            "cases/spike_case_catalog.jsonl": {
                "bytes": catalog_path.stat().st_size,
                "sha256": catalog_hash,
            },
        },
        "evidence_anchors": sorted(
            reader.anchors.values(),
            key=lambda anchor: str(anchor["logical_path"]),
        ),
        "capabilities": capabilities,
        "core_capability_projection": core_projection,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only replay of one sealed Formal run; prints sanitized JSON."
    )
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--replay-code-head", required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    artifact = _build_artifact(
        repo_root=args.repo_root.resolve(),
        evidence_root=args.evidence_root.resolve(),
        replay_code_head=str(args.replay_code_head),
    )
    print(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

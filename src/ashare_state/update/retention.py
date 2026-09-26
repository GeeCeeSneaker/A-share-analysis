"""Small immutable archives for accepted daily-update raw evidence."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ashare_state.storage.atomic_files import write_file_atomic
from ashare_state.storage.paths import (
    physical_from_logical_uri,
    validate_logical_uri,
)
from ashare_state.storage.raw_writer import verify_raw_evidence

_ARCHIVE_PREFIX = "archives/daily_update"
_RECEIPT_PREFIX = "retention/daily_update"
_ARCHIVE_MANIFEST_NAME = "archive-manifest.json"
_RUN_MANIFEST_NAME = "daily-update-manifest.json"


class EvidenceRetentionError(RuntimeError):
    """A daily-update archive cannot be safely created or verified."""


@dataclass(frozen=True)
class EvidenceArchiveResult:
    update_run_id: str
    archive_uri: str
    archive_sha256: str
    receipt_uri: str
    entry_count: int


@dataclass(frozen=True)
class EvidenceRetentionVerification:
    checked_count: int
    verified_count: int
    issues: tuple[dict[str, str], ...]


def archive_daily_update(
    conn: Any,
    *,
    update_run_id: str,
    data_root: Path,
    raw_root: Path,
    secondary_root: Path,
) -> EvidenceArchiveResult:
    """Archive one accepted run's manifest and exact anchored raw files.

    The archive and its sidecar receipt are immutable: exact retries are
    no-ops, while changed bytes at either destination fail closed.
    """
    primary = Path(data_root).resolve()
    raw = Path(raw_root).resolve()
    secondary = Path(secondary_root).resolve()
    _validate_secondary_root(primary, secondary)

    row = conn.execute(
        "SELECT status, manifest_uri, manifest_hash FROM meta_daily_update_run "
        "WHERE update_run_id = ?",
        [update_run_id],
    ).fetchone()
    if row is None or str(row[0]) != "SUCCESS" or not row[1] or not row[2]:
        raise EvidenceRetentionError("daily update is not an accepted successful run")
    manifest_uri, manifest_hash = str(row[1]), str(row[2])
    manifest_path = physical_from_logical_uri(primary, manifest_uri)
    manifest_bytes = _read_sealed_file(manifest_path, manifest_hash, "update manifest")
    try:
        update_manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceRetentionError("accepted daily update manifest is malformed") from exc
    if (
        not isinstance(update_manifest, dict)
        or update_manifest.get("update_run_id") != update_run_id
        or update_manifest.get("acceptance") != "SUCCESS"
    ):
        raise EvidenceRetentionError("accepted daily update manifest identity does not match")
    receipts = update_manifest.get("request_receipts")
    if not isinstance(receipts, list) or not receipts:
        raise EvidenceRetentionError("accepted daily update has no raw request receipts")

    files: dict[str, bytes] = {_RUN_MANIFEST_NAME: manifest_bytes}
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise EvidenceRetentionError("daily update contains a malformed raw receipt")
        dataset = str(receipt.get("provider_dataset") or "")
        request_id = str(receipt.get("request_id") or "")
        expected_uri = str(receipt.get("raw_evidence_uri") or "")
        expected_hash = str(receipt.get("raw_evidence_hash") or "")
        if not dataset or not request_id or not expected_uri or len(expected_hash) != 64:
            raise EvidenceRetentionError("daily update contains an incomplete raw receipt")
        try:
            verified = verify_raw_evidence(
                raw,
                provider="amazingdata",
                dataset=dataset,
                request_id=request_id,
            )
        except Exception as exc:  # noqa: BLE001 - sanitize raw closure details
            raise EvidenceRetentionError(
                "raw evidence failed its trust-anchor closure check"
            ) from exc
        if verified.evidence_uri != expected_uri or verified.evidence_hash != expected_hash:
            raise EvidenceRetentionError("raw evidence does not match the accepted run receipt")

        dataset_dir = raw / "provider=amazingdata" / f"dataset={dataset}"
        meta_path = dataset_dir / f"{request_id}.meta.json"
        meta_bytes = _read_sealed_file(meta_path, expected_hash, "raw evidence metadata")
        _add_archive_file(files, f"raw/{expected_uri}", meta_bytes)
        tables = verified.meta.get("tables")
        if not isinstance(tables, list):
            raise EvidenceRetentionError("raw evidence table inventory is malformed")
        for table in tables:
            if not isinstance(table, dict):
                raise EvidenceRetentionError("raw evidence table entry is malformed")
            filename = str(table.get("file") or "")
            _validate_member_name(filename)
            content_hash = str(table.get("content_hash") or "")
            table_path = dataset_dir.joinpath(*PurePosixPath(filename).parts)
            table_bytes = _read_sealed_file(table_path, content_hash, "raw payload")
            member_name = f"raw/provider=amazingdata/dataset={dataset}/{filename}"
            _add_archive_file(files, member_name, table_bytes)

    entries = [
        {"member": name, "sha256": _sha256(data), "size": len(data)}
        for name, data in sorted(files.items())
    ]
    archive_manifest = {
        "archive_schema": "ashare-daily-evidence-archive-v1",
        "update_run_id": update_run_id,
        "update_manifest_uri": manifest_uri,
        "update_manifest_sha256": manifest_hash,
        "entries": entries,
    }
    archive_manifest_bytes = _canonical_json_bytes(archive_manifest)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(_zip_info(name), data)
        archive.writestr(_zip_info(_ARCHIVE_MANIFEST_NAME), archive_manifest_bytes)
    archive_bytes = buffer.getvalue()
    archive_hash = _sha256(archive_bytes)

    archive_uri = f"{_ARCHIVE_PREFIX}/run={update_run_id}.zip"
    receipt_uri = f"{_RECEIPT_PREFIX}/run={update_run_id}.json"
    archive_path = physical_from_logical_uri(primary, archive_uri)
    secondary_archive_path = physical_from_logical_uri(secondary, archive_uri)
    write_file_atomic(
        archive_path,
        archive_bytes,
        expected_sha256=archive_hash,
        allow_existing_identical=True,
    )
    write_file_atomic(
        secondary_archive_path,
        archive_bytes,
        expected_sha256=archive_hash,
        allow_existing_identical=True,
    )

    archive_manifest_hash = _sha256(archive_manifest_bytes)
    receipt = {
        "receipt_schema": "ashare-daily-evidence-retention-v1",
        "update_run_id": update_run_id,
        "update_manifest_uri": manifest_uri,
        "update_manifest_sha256": manifest_hash,
        "archive_uri": archive_uri,
        "archive_sha256": archive_hash,
        "archive_manifest_sha256": archive_manifest_hash,
        "secondary_archive_uri": archive_uri,
        "secondary_receipt_uri": receipt_uri,
        "entry_count": len(entries),
    }
    receipt_bytes = _canonical_json_bytes(receipt)
    receipt_path = physical_from_logical_uri(primary, receipt_uri)
    secondary_receipt_path = physical_from_logical_uri(secondary, receipt_uri)
    write_file_atomic(
        receipt_path,
        receipt_bytes,
        expected_sha256=_sha256(receipt_bytes),
        allow_existing_identical=True,
    )
    write_file_atomic(
        secondary_receipt_path,
        receipt_bytes,
        expected_sha256=_sha256(receipt_bytes),
        allow_existing_identical=True,
    )
    return EvidenceArchiveResult(
        update_run_id=update_run_id,
        archive_uri=archive_uri,
        archive_sha256=archive_hash,
        receipt_uri=receipt_uri,
        entry_count=len(entries),
    )


def verify_daily_update_archives(
    conn: Any, *, data_root: Path, secondary_root: Path
) -> EvidenceRetentionVerification:
    """Verify each accepted update receipt resolves to matching local and backup bytes."""
    primary = Path(data_root).resolve()
    secondary = Path(secondary_root).resolve()
    _validate_secondary_root(primary, secondary)
    rows = conn.execute(
        "SELECT update_run_id, manifest_uri, manifest_hash FROM meta_daily_update_run "
        "WHERE status = 'SUCCESS' ORDER BY through_date, update_run_id"
    ).fetchall()
    issues: list[dict[str, str]] = []
    verified_count = 0
    for update_run_id_raw, manifest_uri_raw, manifest_hash_raw in rows:
        update_run_id = str(update_run_id_raw)
        try:
            manifest_uri = str(manifest_uri_raw)
            manifest_hash = str(manifest_hash_raw)
            manifest_path = physical_from_logical_uri(primary, manifest_uri)
            manifest_bytes = _read_sealed_file(manifest_path, manifest_hash, "update manifest")
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if not isinstance(manifest, dict) or manifest.get("update_run_id") != update_run_id:
                raise EvidenceRetentionError("update manifest identity mismatch")

            receipt_uri = f"{_RECEIPT_PREFIX}/run={update_run_id}.json"
            receipt_path = physical_from_logical_uri(primary, receipt_uri)
            receipt_bytes = receipt_path.read_bytes()
            receipt = json.loads(receipt_bytes.decode("utf-8"))
            if not isinstance(receipt, dict):
                raise EvidenceRetentionError("retention receipt is malformed")
            if (
                receipt.get("update_run_id") != update_run_id
                or receipt.get("update_manifest_uri") != manifest_uri
                or receipt.get("update_manifest_sha256") != manifest_hash
            ):
                raise EvidenceRetentionError("retention receipt does not match the accepted update")

            archive_uri = str(receipt.get("archive_uri") or "")
            secondary_uri = str(receipt.get("secondary_archive_uri") or "")
            secondary_receipt_uri = str(receipt.get("secondary_receipt_uri") or "")
            validate_logical_uri(archive_uri)
            validate_logical_uri(secondary_uri)
            validate_logical_uri(secondary_receipt_uri)
            if secondary_receipt_uri != receipt_uri:
                raise EvidenceRetentionError("secondary receipt URI does not match the run")
            archive_bytes = _read_sealed_file(
                physical_from_logical_uri(primary, archive_uri),
                str(receipt.get("archive_sha256") or ""),
                "local evidence archive",
            )
            _verify_archive_bytes(archive_bytes, receipt, manifest)
            _read_sealed_file(
                physical_from_logical_uri(secondary, secondary_uri),
                str(receipt.get("archive_sha256") or ""),
                "secondary evidence archive",
            )
            _read_sealed_file(
                physical_from_logical_uri(secondary, secondary_receipt_uri),
                _sha256(receipt_bytes),
                "secondary retention receipt",
            )
        except Exception as exc:  # noqa: BLE001 - return a safe bounded diagnostic
            issues.append(
                {
                    "update_run_id": update_run_id,
                    "failure_class": (
                        type(exc).__name__
                        if isinstance(exc, EvidenceRetentionError)
                        else "RETENTION_INTEGRITY_ERROR"
                    ),
                }
            )
        else:
            verified_count += 1
    return EvidenceRetentionVerification(
        checked_count=len(rows),
        verified_count=verified_count,
        issues=tuple(issues),
    )


def _verify_archive_bytes(
    archive_bytes: bytes, receipt: dict[str, Any], manifest: dict[str, Any]
) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as archive:
            if archive.testzip() is not None:
                raise EvidenceRetentionError("archive CRC verification failed")
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise EvidenceRetentionError("archive contains duplicate member paths")
            archive_manifest_bytes = archive.read(_ARCHIVE_MANIFEST_NAME)
            archive_manifest = json.loads(archive_manifest_bytes.decode("utf-8"))
            if _sha256(archive_manifest_bytes) != receipt.get("archive_manifest_sha256"):
                raise EvidenceRetentionError("archive manifest checksum mismatch")
            if (
                not isinstance(archive_manifest, dict)
                or archive_manifest.get("archive_schema") != "ashare-daily-evidence-archive-v1"
                or archive_manifest.get("update_run_id") != receipt.get("update_run_id")
                or archive_manifest.get("update_manifest_sha256")
                != receipt.get("update_manifest_sha256")
                or archive_manifest.get("update_manifest_uri") != receipt.get("update_manifest_uri")
            ):
                raise EvidenceRetentionError("archive manifest does not match its receipt")
            if (
                manifest.get("update_run_id") != receipt.get("update_run_id")
                or manifest.get("acceptance") != "SUCCESS"
                or _sha256(archive.read(_RUN_MANIFEST_NAME))
                != receipt.get("update_manifest_sha256")
            ):
                raise EvidenceRetentionError("archived update manifest is not the accepted run")
            entries = archive_manifest.get("entries")
            if not isinstance(entries, list) or len(entries) != int(receipt.get("entry_count", -1)):
                raise EvidenceRetentionError("archive member inventory is malformed")
            declared: dict[str, dict[str, Any]] = {}
            for entry in entries:
                if not isinstance(entry, dict):
                    raise EvidenceRetentionError("archive member entry is malformed")
                name = str(entry.get("member") or "")
                _validate_member_name(name)
                if name == _ARCHIVE_MANIFEST_NAME or name in declared:
                    raise EvidenceRetentionError("archive member inventory has duplicate paths")
                member_bytes = archive.read(name)
                if len(member_bytes) != int(entry.get("size", -1)) or _sha256(member_bytes) != str(
                    entry.get("sha256") or ""
                ):
                    raise EvidenceRetentionError("archive member checksum mismatch")
                declared[name] = entry
            expected_names = _expected_raw_members(archive, manifest)
            if set(declared) != expected_names:
                raise EvidenceRetentionError("archive members do not match accepted raw receipts")
            if set(names) != expected_names | {_ARCHIVE_MANIFEST_NAME}:
                raise EvidenceRetentionError("archive contains undeclared members")
    except EvidenceRetentionError:
        raise
    except (
        OSError,
        KeyError,
        ValueError,
        TypeError,
        UnicodeDecodeError,
        zipfile.BadZipFile,
    ) as exc:
        raise EvidenceRetentionError("evidence archive structure is invalid") from exc


def _expected_raw_members(archive: zipfile.ZipFile, manifest: dict[str, Any]) -> set[str]:
    expected = {_RUN_MANIFEST_NAME}
    receipts = manifest.get("request_receipts")
    if not isinstance(receipts, list) or not receipts:
        raise EvidenceRetentionError("accepted update manifest has no raw receipts")
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise EvidenceRetentionError("accepted update manifest has a malformed raw receipt")
        dataset = str(receipt.get("provider_dataset") or "")
        request_id = str(receipt.get("request_id") or "")
        evidence_uri = str(receipt.get("raw_evidence_uri") or "")
        evidence_hash = str(receipt.get("raw_evidence_hash") or "")
        expected_uri = f"provider=amazingdata/dataset={dataset}/{request_id}.meta.json"
        if (
            not dataset
            or not request_id
            or evidence_uri != expected_uri
            or len(evidence_hash) != 64
        ):
            raise EvidenceRetentionError("accepted update raw receipt is incomplete")
        validate_logical_uri(expected_uri)
        meta_name = f"raw/{evidence_uri}"
        try:
            meta_bytes = archive.read(meta_name)
            raw_meta = json.loads(meta_bytes.decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvidenceRetentionError("archive raw metadata is missing or malformed") from exc
        if (
            _sha256(meta_bytes) != evidence_hash
            or not isinstance(raw_meta, dict)
            or raw_meta.get("request_id") != request_id
            or raw_meta.get("provider") != "amazingdata"
            or raw_meta.get("provider_dataset") != dataset
        ):
            raise EvidenceRetentionError("archive raw metadata differs from its accepted receipt")
        expected.add(meta_name)
        tables = raw_meta.get("tables")
        if not isinstance(tables, list):
            raise EvidenceRetentionError("archive raw metadata table list is malformed")
        for table in tables:
            if not isinstance(table, dict):
                raise EvidenceRetentionError("archive raw metadata table entry is malformed")
            filename = str(table.get("file") or "")
            _validate_member_name(filename)
            table_name = f"raw/provider=amazingdata/dataset={dataset}/{filename}"
            try:
                payload = archive.read(table_name)
            except KeyError as exc:
                raise EvidenceRetentionError("archive raw payload is missing") from exc
            if _sha256(payload) != str(table.get("content_hash") or ""):
                raise EvidenceRetentionError("archive raw payload differs from its metadata hash")
            expected.add(table_name)
    return expected


def _validate_secondary_root(data_root: Path, secondary_root: Path) -> None:
    if (
        data_root == secondary_root
        or data_root in secondary_root.parents
        or secondary_root in data_root.parents
    ):
        raise EvidenceRetentionError(
            "secondary backup root must be a distinct sibling or off-machine root"
        )


def _validate_member_name(name: str) -> str:
    if not name or "\\" in name:
        raise EvidenceRetentionError("archive member path is malformed")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise EvidenceRetentionError("archive member path escapes the archive")
    return name


def _add_archive_file(files: dict[str, bytes], name: str, content: bytes) -> None:
    _validate_member_name(name)
    existing = files.get(name)
    if existing is not None and existing != content:
        raise EvidenceRetentionError("archive member path collision")
    files[name] = content


def _read_sealed_file(path: Path, expected_sha256: str, label: str) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise EvidenceRetentionError(f"{label} is missing or unreadable") from exc
    if len(expected_sha256) != 64 or _sha256(content) != expected_sha256:
        raise EvidenceRetentionError(f"{label} checksum mismatch")
    return content


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

"""Deterministic raw-byte bundles for GT-H3B composite official evidence."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ashare_state.spike.golden_store import VALID_ARTIFACT_KINDS

BUNDLE_FORMAT = "GT-H3B-EVIDENCE-BUNDLE/v1"
MANIFEST_NAME = "manifest.json"


class EvidenceBundleError(ValueError):
    """An EVIDENCE_BUNDLE is malformed or does not match its declarations."""


@dataclass(frozen=True)
class EvidenceBundleEntry:
    source_ref: str
    artifact_kind: str
    member_name: str
    sha256: str
    size: int


def _source_ref(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise EvidenceBundleError("source_ref must be a non-empty string")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EvidenceBundleError(f"source_ref must be an HTTP(S) URL: {value!r}")
    return value


def _artifact_kind(value: object) -> str:
    if not isinstance(value, str) or value not in VALID_ARTIFACT_KINDS:
        raise EvidenceBundleError(f"invalid official artifact kind: {value!r}")
    if value == "EVIDENCE_BUNDLE":
        raise EvidenceBundleError("a bundle entry cannot itself be an EVIDENCE_BUNDLE")
    return value


def _member_name(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise EvidenceBundleError("bundle member name must be a non-empty string")
    if value == MANIFEST_NAME or value.startswith(("/", "\\")) or "\\" in value:
        raise EvidenceBundleError(f"invalid bundle member name: {value!r}")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise EvidenceBundleError(f"invalid bundle member name: {value!r}")
    return value


def _digest(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise EvidenceBundleError("bundle entry sha256 must be lowercase 64-hex")
    return value


def _expected_sources(
    values: Iterable[Mapping[str, object]],
) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []
    for index, source in enumerate(values, start=1):
        try:
            source_ref = _source_ref(source["source_ref"])
            kind = _artifact_kind(source["kind"])
        except (KeyError, TypeError) as exc:
            raise EvidenceBundleError(
                f"declared bundle source {index} is missing source_ref/kind"
            ) from exc
        normalized.append((source_ref, kind))
    if len(set(normalized)) != len(normalized):
        raise EvidenceBundleError("declared bundle sources contain duplicates")
    return tuple(normalized)


def read_evidence_bundle(
    path: Path,
    *,
    expected_sources: Iterable[Mapping[str, object]] | None = None,
) -> list[EvidenceBundleEntry]:
    """Validate a bundle and re-hash every raw source member.

    The ZIP is intentionally uncompressed so the same inputs produce the same
    bytes across supported Python platforms.  The manifest.json file is a
    clear source-ref/kind/hash/size inventory; every other member is an
    official raw response body or PDF/HTML byte stream.
    """
    if path.suffix.lower() != ".zip":
        raise EvidenceBundleError("EVIDENCE_BUNDLE must be a .zip file")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(infos) < 3:
                raise EvidenceBundleError(
                    "EVIDENCE_BUNDLE must contain manifest.json and at least two source members"
                )
            if names.count(MANIFEST_NAME) != 1:
                raise EvidenceBundleError("EVIDENCE_BUNDLE must contain one manifest.json")
            if len(names) != len(set(names)):
                raise EvidenceBundleError("EVIDENCE_BUNDLE contains duplicate member names")
            for info in infos:
                _member_name(info.filename)
                if info.is_dir() or info.filename.endswith("/"):
                    raise EvidenceBundleError("EVIDENCE_BUNDLE cannot contain directory members")
                if info.flag_bits & 0x1:
                    raise EvidenceBundleError("encrypted EVIDENCE_BUNDLE members are forbidden")
                mode = (info.external_attr >> 16) & 0o170000
                if mode not in {0, stat.S_IFREG}:
                    raise EvidenceBundleError(
                        f"EVIDENCE_BUNDLE member {info.filename!r} is not a regular file"
                    )
            raw_manifest = archive.read(MANIFEST_NAME)
            try:
                manifest = json.loads(raw_manifest.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvidenceBundleError("EVIDENCE_BUNDLE manifest is not valid UTF-8 JSON") from exc
            if not isinstance(manifest, dict) or manifest.get("format") != BUNDLE_FORMAT:
                raise EvidenceBundleError("unsupported EVIDENCE_BUNDLE format")
            raw_entries = manifest.get("entries")
            if not isinstance(raw_entries, list) or len(raw_entries) < 2:
                raise EvidenceBundleError("EVIDENCE_BUNDLE manifest requires at least two entries")
            source_names = set(names) - {MANIFEST_NAME}
            declared_names: set[str] = set()
            entries: list[EvidenceBundleEntry] = []
            for index, raw_entry in enumerate(raw_entries, start=1):
                if not isinstance(raw_entry, dict):
                    raise EvidenceBundleError(f"bundle manifest entry {index} must be an object")
                required = ("source_ref", "artifact_kind", "member_name", "sha256", "size")
                missing = [field for field in required if field not in raw_entry]
                if missing:
                    raise EvidenceBundleError(
                        f"bundle manifest entry {index} is missing {missing}"
                    )
                source_ref = _source_ref(raw_entry["source_ref"])
                artifact_kind = _artifact_kind(raw_entry["artifact_kind"])
                member_name = _member_name(raw_entry["member_name"])
                digest = _digest(raw_entry["sha256"])
                size = raw_entry["size"]
                if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                    raise EvidenceBundleError(
                        f"bundle manifest entry {index} size must be a non-negative integer"
                    )
                if member_name in declared_names:
                    raise EvidenceBundleError(
                        f"EVIDENCE_BUNDLE contains duplicate declared member {member_name!r}"
                    )
                if member_name not in source_names:
                    raise EvidenceBundleError(
                        f"bundle manifest entry {index} points to missing member {member_name!r}"
                    )
                declared_names.add(member_name)
                data = archive.read(member_name)
                actual_digest = hashlib.sha256(data).hexdigest()
                if len(data) != size or actual_digest != digest:
                    raise EvidenceBundleError(
                        f"bundle member {member_name!r} does not match its declared bytes"
                    )
                entries.append(
                    EvidenceBundleEntry(
                        source_ref=source_ref,
                        artifact_kind=artifact_kind,
                        member_name=member_name,
                        sha256=digest,
                        size=size,
                    )
                )
            if declared_names != source_names:
                raise EvidenceBundleError(
                    "EVIDENCE_BUNDLE contains members missing from or absent in manifest.json"
                )
    except EvidenceBundleError:
        raise
    except (KeyError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise EvidenceBundleError(f"cannot read EVIDENCE_BUNDLE {path}: {exc}") from exc

    if expected_sources is not None:
        expected = _expected_sources(expected_sources)
        actual = tuple((entry.source_ref, entry.artifact_kind) for entry in entries)
        if actual != expected:
            raise EvidenceBundleError(
                "EVIDENCE_BUNDLE source list does not match the review manifest declaration"
            )
    return entries


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def write_evidence_bundle(
    output: Path,
    sources: Iterable[Mapping[str, object]],
) -> None:
    """Create a deterministic, create-only bundle from official raw files."""
    source_list = list(sources)
    if len(source_list) < 2:
        raise EvidenceBundleError("EVIDENCE_BUNDLE requires at least two source files")
    entries: list[dict[str, object]] = []
    payloads: list[tuple[str, bytes]] = []
    seen_sources: set[tuple[str, str]] = set()
    for index, source in enumerate(source_list):
        try:
            source_ref = _source_ref(source["source_ref"])
            artifact_kind = _artifact_kind(source["kind"])
            source_path = Path(str(source["path"]))
        except (KeyError, TypeError) as exc:
            raise EvidenceBundleError(
                f"bundle source {index + 1} is missing path/source_ref/kind"
            ) from exc
        if not source_path.is_file():
            raise EvidenceBundleError(f"bundle source file does not exist: {source_path}")
        source_key = (source_ref, artifact_kind)
        if source_key in seen_sources:
            raise EvidenceBundleError(f"duplicate bundle source: {source_key}")
        seen_sources.add(source_key)
        data = source_path.read_bytes()
        suffix = source_path.suffix.lower() or ".bin"
        member_name = f"sources/{index:04d}{suffix}"
        digest = hashlib.sha256(data).hexdigest()
        entries.append(
            {
                "artifact_kind": artifact_kind,
                "member_name": member_name,
                "sha256": digest,
                "size": len(data),
                "source_ref": source_ref,
            }
        )
        payloads.append((member_name, data))
    manifest = {"entries": entries, "format": BUNDLE_FORMAT}
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(_zip_info(MANIFEST_NAME), manifest_bytes)
        for member_name, data in payloads:
            archive.writestr(_zip_info(member_name), data)
    payload = buffer.getvalue()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() == payload:
            return
        raise EvidenceBundleError(f"bundle {output} already exists with different bytes")
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)

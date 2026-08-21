"""Logical file URI rules (design ruling P0-4).

file_uri is a LOGICAL URI, not a Windows path:
- relative to data_root
- forward slashes only ('/')
- UTF-8, program-defined canonical casing
- no drive letters, no machine absolute paths, no '..'

Manifest comparisons use EXACT string equality. Two logical URIs differing
only by case are a BLOCK condition (case collision), because NTFS would treat
them as the same file while Linux would not - cross-platform identity must
not inherit Windows case-insensitivity.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath


class LogicalUriError(ValueError):
    """Base error for logical URI violations."""


class AbsolutePathError(LogicalUriError):
    """Physical path escapes data_root or is on another volume/root."""


class CaseCollisionError(LogicalUriError):
    """Two logical URIs differ only by case (design ruling P0-4 BLOCK)."""


_FORBIDDEN_SCHEME = "://"


def to_logical_uri(data_root: Path, physical: Path) -> str:
    """Convert a physical path under data_root into the canonical logical URI.

    Raises AbsolutePathError if the path is not under data_root (after
    resolving), or if it is an absolute path with a drive outside data_root.
    """
    data_root = Path(data_root).resolve()
    physical = Path(physical).resolve()
    try:
        relative = physical.relative_to(data_root)
    except ValueError as exc:
        msg = f"path {physical} is not under data_root {data_root}"
        raise AbsolutePathError(msg) from exc
    return relative.as_posix()


def validate_logical_uri(uri: str) -> str:
    """Validate a logical URI string and return it unchanged.

    Checks: non-empty, no scheme, POSIX-relative (no leading '/'), no '..',
    no drive letters, no backslashes.
    """
    if not uri:
        msg = "logical URI must not be empty"
        raise LogicalUriError(msg)
    if _FORBIDDEN_SCHEME in uri:
        msg = f"logical URI must not contain a scheme: {uri!r}"
        raise LogicalUriError(msg)
    if uri.startswith("/") or uri.startswith("\\"):
        msg = f"logical URI must be relative (no leading slash): {uri!r}"
        raise LogicalUriError(msg)
    if "\\" in uri:
        msg = f"logical URI must use forward slashes only: {uri!r}"
        raise LogicalUriError(msg)
    if len(uri) >= 2 and uri[1] == ":":
        msg = f"logical URI must not contain drive letters: {uri!r}"
        raise LogicalUriError(msg)
    pure = PurePosixPath(uri)
    if any(part == ".." for part in pure.parts):
        msg = f"logical URI must not contain '..': {uri!r}"
        raise LogicalUriError(msg)
    return uri


def physical_from_logical_uri(data_root: Path, uri: str) -> Path:
    """Resolve a logical URI to a physical path under data_root (OS-adaptive).

    This is the ONLY place where Windows case-insensitive filesystem
    resolution may happen; it never influences logical identity.
    """
    validate_logical_uri(uri)
    return Path(data_root) / Path(*PurePosixPath(uri).parts)


def assert_no_case_collisions(uris: list[str]) -> None:
    """BLOCK if any two logical URIs differ only by letter case."""
    seen: dict[str, str] = {}  # lowercased -> original
    for uri in uris:
        validate_logical_uri(uri)
        folded = uri.casefold()
        if folded in seen and seen[folded] != uri:
            msg = (
                f"case collision between logical URIs {seen[folded]!r} and {uri!r}; "
                "manifest identity uses exact comparison - rename one component"
            )
            raise CaseCollisionError(msg)
        seen.setdefault(folded, uri)

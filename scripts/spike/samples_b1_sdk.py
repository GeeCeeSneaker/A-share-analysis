"""B1 smoke probe: verify AmazingData SDK import surface (NO login, NO network).

Runs entirely offline: imports the package, lists public API surface, checks
the login signature and BaseData/InfoData/MultiDataData class availability.
Any login/credential use is explicitly out of scope here.
"""

from __future__ import annotations

import importlib.metadata
import json
import sys
from pathlib import Path

RESULTS = Path("data/spike/results")
RESULTS.mkdir(parents=True, exist_ok=True)


def main() -> None:
    report: dict[str, object] = {
        "phase": "B1",
        "python_version": sys.version,
        "platform": sys.platform,
    }

    try:
        # N813: `import AmazingData as ad` is the official manual idiom.
        import AmazingData as ad  # noqa: N813
    except Exception as exc:  # noqa: BLE001
        report["import_ok"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
        (RESULTS / "b1_sdk_env.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        print("IMPORT FAILED:", report["error"])
        raise SystemExit(2) from exc

    try:
        version = importlib.metadata.version("AmazingData")
    except importlib.metadata.PackageNotFoundError:
        version = "UNKNOWN"

    public = [n for n in dir(ad) if not n.startswith("_")]
    classes = [n for n in public if n[0].isupper()]
    report.update(
        {
            "import_ok": True,
            "module_file": str(getattr(ad, "__file__", None)),
            "version": version,
            "public_names": public,
            "classes": classes,
            "has_login": hasattr(ad, "login"),
            "has_logout": hasattr(ad, "logout"),
            "has_basedata": hasattr(ad, "BaseData"),
            "has_infodata": hasattr(ad, "InfoData"),
            "has_multidata": hasattr(ad, "MultiDataData"),
        }
    )

    # method inventory of the three data classes (offline introspection only)
    for cls_name in ("BaseData", "InfoData", "MultiDataData"):
        cls = getattr(ad, cls_name, None)
        if cls is not None:
            methods = [
                n for n in dir(cls) if not n.startswith("_") and callable(getattr(cls, n, None))
            ]
            report[f"{cls_name}_methods"] = methods

    out = RESULTS / "b1_sdk_env.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"import OK, version={version}, report -> {out}")
    print("classes:", report["classes"])


if __name__ == "__main__":
    main()

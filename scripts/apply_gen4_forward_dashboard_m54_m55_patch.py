from __future__ import annotations

import argparse
import json
from pathlib import Path


class PatchError(RuntimeError):
    pass


def patch_main(text: str) -> tuple[str, list[str]]:
    changes: list[str] = []

    if 'const Gen4Forward = lazy' not in text:
        anchor = '''const LiveScanner = lazy(() =>
  import("./pages/LiveScanner.jsx")
);
'''
        addition = '''const Gen4Forward = lazy(() =>
  import("./pages/Gen4Forward.jsx")
);

'''
        if anchor not in text:
            raise PatchError("Anchor lazy route non trovato in frontend/src/main.jsx")
        text = text.replace(anchor, addition + anchor, 1)
        changes.append("main.lazy_import")

    if 'path="/gen4-forward"' not in text:
        anchor = '''            <Route
              path="/live-trading"
              element={<LiveTrading />}
            />

'''
        addition = '''            <Route
              path="/gen4-forward"
              element={<Gen4Forward />}
            />

'''
        if anchor not in text:
            raise PatchError("Anchor route non trovato in frontend/src/main.jsx")
        text = text.replace(anchor, anchor + addition, 1)
        changes.append("main.route")

    return text, changes


def patch_navbar(text: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    if 'path: "/gen4-forward"' not in text:
        anchor = '''  {
    label: "Copy Trading",
    path: "/live-trading",
    liveTrading: true,
  },
'''
        addition = '''  {
    label: "Gen 4 Forward",
    path: "/gen4-forward",
  },
'''
        if anchor not in text:
            raise PatchError("Anchor navigazione non trovato in Navbar.jsx")
        text = text.replace(anchor, addition + anchor, 1)
        changes.append("navbar.item")
    return text, changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.project_root.resolve()
    targets = {
        "frontend/src/main.jsx": patch_main,
        "frontend/src/components/Navbar.jsx": patch_navbar,
    }

    report: dict[str, object] = {
        "project_root": str(root),
        "check_only": bool(args.check),
        "changes": [],
        "files": {},
    }

    for relative, patcher in targets.items():
        path = root / relative
        if not path.is_file():
            raise PatchError(f"File richiesto mancante: {relative}")
        original = path.read_text(encoding="utf-8-sig")
        updated, changes = patcher(original)
        report["changes"].extend(changes)  # type: ignore[union-attr]
        report["files"][relative] = {  # type: ignore[index]
            "changed": updated != original,
            "markers": changes,
        }
        if not args.check and updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    print("M54_M55_SEMANTIC_PATCH=OK")
    print(f"CHECK_ONLY={args.check}")
    print(f"CHANGES={','.join(report['changes']) or 'NONE'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

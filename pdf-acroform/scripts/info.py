"""Inspect a PDF — return a JSON-friendly summary.

Run:
    python inspect.py /path/to/file.pdf            # whole doc
    python inspect.py /path/to/file.pdf --fields   # only form fields
    python inspect.py /path/to/file.pdf --fonts    # only fonts
    python inspect.py /path/to/file.pdf --pages 1-3 # only those pages

Imports `_common` by relative path so it works from anywhere.
"""

from __future__ import annotations

import argparse
import sys
import os

# allow `import _common` when invoked from any cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import open_pdf, all_widgets, widget_summary, list_system_cjk_fonts  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Inspect a PDF (fields, fonts, pages).")
    ap.add_argument("pdf")
    ap.add_argument("--fields",  action="store_true", help="show only form fields")
    ap.add_argument("--fonts",   action="store_true", help="show only fonts")
    ap.add_argument("--pages",   help="page range like 1-3 or 1 (default: all)", default=None)
    ap.add_argument("--cjk",     action="store_true", help="also list system CJK fonts")
    ap.add_argument("--json",    action="store_true", help="always emit JSON")
    args = ap.parse_args()

    doc = open_pdf(args.pdf)

    want_all = not (args.fields or args.fonts)

    out: dict = {
        "ok": True,
        "path": args.pdf,
        "page_count": len(doc),
        "metadata": dict(doc.metadata),
        "is_form_pdf": bool(doc.is_form_pdf),
        "fields": [],
        "fonts": [],
        "system_cjk_fonts": [],
    }

    # fields
    if want_all or args.fields:
        for page_idx, w in all_widgets(doc):
            pg = page_idx + 1
            if args.pages:
                pgs = _parse_range(args.pages)
                if pg not in pgs:
                    continue
            s = widget_summary(w)
            s["page"] = pg
            out["fields"].append(s)

    # fonts
    if want_all or args.fonts:
        seen: set[tuple] = set()
        for pi in range(len(doc)):
            pg = pi + 1
            if args.pages and pg not in _parse_range(args.pages):
                continue
            for entry in doc.get_page_fonts(pi):
                # (xref, ext, type, basefont, name, encoding[, ...])
                basefont, ftype, ext = entry[3], entry[2], entry[1]
                key = (basefont, ftype, ext)
                if key in seen:
                    continue
                seen.add(key)
                out["fonts"].append({
                    "basefont": basefont,
                    "type":     ftype,
                    "ext":      ext,
                    "first_page": pg,
                })

    if args.cjk:
        out["system_cjk_fonts"] = list_system_cjk_fonts()

    import json
    print(json.dumps(out, ensure_ascii=False, indent=2))


def _parse_range(spec: str) -> set[int]:
    """Parse '1-3,5,7-9' into {1,2,3,5,7,8,9}."""
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


if __name__ == "__main__":
    main()

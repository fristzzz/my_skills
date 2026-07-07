"""Text/image overlay for non-form PDFs.

Use case: the source PDF does NOT have AcroForm fields — they are
just blank lines or static text. To "fill" them, render text (or an
image) on top at given coordinates.

CLI:
    python overlay.py text  in.pdf out.pdf --config overlay.json
    python overlay.py image in.pdf out.pdf --config images.json

overlay.json shape:
    {"items": [
      {"page": 1, "rect": [x0,y0,x1,y1], "text": "陈政羽", "font": "STHeiti",
       "fontsize": 11, "color": [0.05,0.1,0.3], "align": "left|center|right",
       "wrap": false}
    ]}

images.json shape:
    {"items": [
      {"page": 1, "rect": [x0,y0,x1,y1], "path": "/abs/or/rel/path/to.png"}
    ]}

Coordinates use PDF units (points), origin top-left for `rect` arguments
(this script flips Y so you can reason in top-left coords).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import open_pdf, save_pdf, resolve_font, emit, die  # noqa: E402

import fitz


def _font_alias_in_page(page, alias: str | None) -> str | None:
    if not alias:
        return None
    fp = resolve_font(alias)
    if not fp:
        return None
    name = "Ovl"
    try:
        page.insert_font(fontname=name, fontfile=fp)
        return name
    except Exception:
        name = f"Ovl_{abs(hash(fp)) % 100000}"
        try:
            page.insert_font(fontname=name, fontfile=fp)
            return name
        except Exception:
            return None


def cmd_text(args) -> None:
    cfg = _load_cfg(args)
    items = cfg.get("items") or []
    if not items:
        die("config.items is empty")

    doc = open_pdf(args.input)
    placed = []
    for it in items:
        page_idx = int(it.get("page", 1)) - 1
        if page_idx < 0 or page_idx >= len(doc):
            die(f"page out of range: {it.get('page')}")
        page = doc[page_idx]
        rect = fitz.Rect(*it["rect"])
        # PyMuPDF inserts in top-left Y; rect top is already top — use it as-is.
        # But commonly people pass "rect" thinking of "where the text lands" —
        # we'll honor what's given (top, left, right, bottom).

        fontname = _font_alias_in_page(page, it.get("font") or "hei")
        fontsize = float(it.get("fontsize", 11))
        color = tuple(float(c) for c in (it.get("color") or [0, 0, 0]))
        text = str(it.get("text", ""))
        align = (it.get("align") or "left").lower()

        # Word-wrap inside rect height if `wrap: true`
        wrap = bool(it.get("wrap", False))
        if wrap:
            text = _wrap(text, rect.width, fontname, fontsize, page)

        # Use insert_textbox so we get alignment + multi-line for free
        try:
            rc = page.insert_textbox(
                rect, text,
                fontname=fontname or "Helvetica",
                fontsize=fontsize,
                color=color,
                align=({"left":  fitz.TEXT_ALIGN_LEFT,
                        "center": fitz.TEXT_ALIGN_CENTER,
                        "right":  fitz.TEXT_ALIGN_RIGHT,
                        "justify":fitz.TEXT_ALIGN_JUSTIFY}[align]),
            )
            placed.append({"page": page_idx + 1, "rect": list(rect),
                           "text": text, "chars_remaining": rc})
        except Exception as e:
            placed.append({"page": page_idx + 1, "error": str(e), "text": text})

    save_pdf(doc, args.output)
    emit({"ok": True, "output": args.output, "placed": placed})


def _wrap(text: str, width: float, fontname: str, fontsize: float, page) -> str:
    """Naive break-by-character wrap that fits in `width`."""
    # PyMuPDF's get_textlength accepts a fontname + fontsize already registered on page.
    lines, current = [], ""
    for ch in text:
        candidate = current + ch
        try:
            w = page.get_textlength(candidate, fontname=fontname, fontsize=fontsize)
        except Exception:
            w = fontsize * len(candidate) * 0.6
        if w > width and current:
            lines.append(current)
            current = ch
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)


def cmd_image(args) -> None:
    cfg = _load_cfg(args)
    items = cfg.get("items") or []
    if not items:
        die("config.items is empty")

    doc = open_pdf(args.input)
    placed = []
    for it in items:
        page_idx = int(it.get("page", 1)) - 1
        page = doc[page_idx]
        img_path = it["path"]
        if not Path(img_path).expanduser().exists():
            die(f"image missing: {img_path}")
        rect = fitz.Rect(*it["rect"])
        try:
            page.insert_image(rect, filename=str(Path(img_path).expanduser()),
                              keep_proportion=bool(it.get("keep_proportion", True)))
            placed.append({"page": page_idx + 1, "rect": list(rect), "path": img_path})
        except Exception as e:
            placed.append({"page": page_idx + 1, "path": img_path, "error": str(e)})

    save_pdf(doc, args.output)
    emit({"ok": True, "output": args.output, "placed": placed})


def _load_cfg(args) -> dict:
    p = getattr(args, "config", None)
    if not p:
        return {}
    if p == "-":
        return json.loads(sys.stdin.read())
    return json.loads(Path(p).read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Text/image overlay on non-form PDFs.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_txt = sub.add_parser("text")
    p_txt.add_argument("input")
    p_txt.add_argument("output")
    p_txt.add_argument("--config")

    p_img = sub.add_parser("image")
    p_img.add_argument("input")
    p_img.add_argument("output")
    p_img.add_argument("--config")

    args = ap.parse_args()
    (cmd_text if args.cmd == "text" else cmd_image)(args)


if __name__ == "__main__":
    main()

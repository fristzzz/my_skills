"""Generate a new fillable PDF from a JSON layout.

This is the "create forms" path — for use cases where the user wants to author
a brand-new template in Python rather than Typst. Useful for one-off pipelines;
for maintained templates, prefer Typst.

CLI:
    python build_pdf.py template.json out.pdf

template.json shape:
    {
      "page_size": "A4",                        # "A4", "Letter", or [w, h]
      "pages": [
        {
          "blocks": [
            {"type": "text",  "x": 200, "y": 60, "fontsize": 18,
             "text": "Tapdata 顾问协议", "font": "SourceHan", "weight": "bold"},
            {"type": "field", "name": "乙方身份证号", "x": 140, "y": 342,
             "width": 264, "height": 12,
             "fontsize": 10, "font": "STHeiti", "value": ""},
            {"type": "rule",  "x0": 140, "y0": 354, "x1": 404, "y1": 354,
             "thickness": 0.5},
            {"type": "image", "x": 460, "y": 60, "w": 80, "h": 80,
             "path": "logo.png"}
          ]
        }
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import resolve_font, emit, die, save_pdf  # noqa: E402

import fitz


_PAGE_SIZES = {
    "A4":     fitz.paper_size("A4"),
    "A5":     fitz.paper_size("A5"),
    "A3":     fitz.paper_size("A3"),
    "Letter": fitz.paper_size("Letter"),
    "Legal":  fitz.paper_size("Legal"),
}


def _fontname_for(page, alias: str | None, default="Helvetica") -> str:
    if not alias:
        return default
    fp = resolve_font(alias)
    if not fp:
        return default
    name = "Bld"
    try:
        page.insert_font(fontname=name, fontfile=fp)
        return name
    except Exception:
        name = f"Bld_{abs(hash(fp)) % 100000}"
        try:
            page.insert_font(fontname=name, fontfile=fp)
            return name
        except Exception:
            return default


def render(template: dict, out_path: str) -> dict:
    if "page_size" in template:
        ps = template["page_size"]
        if isinstance(ps, str):
            page_w, page_h = _PAGE_SIZES.get(ps, fitz.paper_size("A4"))
        else:
            page_w, page_h = float(ps[0]), float(ps[1])
    else:
        page_w, page_h = fitz.paper_size("A4")

    doc = fitz.open()
    pages = template.get("pages") or []
    summary = {"fields_created": 0, "text": 0, "rules": 0, "images": 0, "pages": 0}

    for page_spec in pages or [{}]:
        page = doc.new_page(width=page_w, height=page_h)
        blocks = page_spec.get("blocks") or []

        # Pass 1: text + rules + images (visual)
        for blk in blocks:
            t = blk.get("type")
            if t == "text":
                font = _fontname_for(page, blk.get("font"))
                page.insert_text(
                    (float(blk["x"]), float(blk["y"])),
                    str(blk["text"]),
                    fontname=font,
                    fontsize=float(blk.get("fontsize", 11)),
                    color=tuple(float(c) for c in (blk.get("color") or [0, 0, 0])),
                )
                summary["text"] += 1
            elif t == "rule":
                page.draw_line(
                    (float(blk["x0"]), float(blk["y0"])),
                    (float(blk["x1"]), float(blk["y1"])),
                    color=tuple(float(c) for c in (blk.get("color") or [0, 0, 0])),
                    width=float(blk.get("thickness", 0.5)),
                )
                summary["rules"] += 1
            elif t == "image":
                p = str(Path(blk["path"]).expanduser())
                if not Path(p).exists():
                    die(f"image missing: {p}")
                x, y, w, h = (float(blk["x"]), float(blk["y"]),
                              float(blk["w"]), float(blk["h"]))
                page.insert_image(fitz.Rect(x, y, x + w, y + h), filename=p)
                summary["images"] += 1
            # `field` blocks are added in pass 2 so other visual cues are in place

        # Pass 2: AcroForm widgets
        for blk in blocks:
            if blk.get("type") != "field":
                continue
            x = float(blk["x"]); y = float(blk["y"])
            w = float(blk.get("width",  200)); h = float(blk.get("height", 12))
            wgt = fitz.Widget()
            wgt.field_name = str(blk["name"])
            wgt.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            wgt.field_value = str(blk.get("value", ""))
            wgt.rect = fitz.Rect(x, y, x + w, y + h)

            fontname = _fontname_for(page, blk.get("font"))
            try: wgt.text_font = fontname
            except Exception: pass
            if "fontsize" in blk:
                try: wgt.text_fontsize = float(blk["fontsize"])
                except Exception: pass
            if "color" in blk:
                try: wgt.text_color = tuple(float(c) for c in blk["color"])
                except Exception: pass
            if "border" in blk:
                b = blk["border"]
                if isinstance(b, dict):
                    try:
                        wgt.border_width = float(b.get("width", 0.5))
                        if b.get("dashes"):
                            wgt.border_dashes = list(b["dashes"])
                    except Exception:
                        pass
            try:
                page.add_widget(wgt)
                summary["fields_created"] += 1
            except Exception as e:
                emit({"ok": False, "warning": f"add_widget failed: {blk.get('name')!r} {e}"})

        summary["pages"] += 1

    save_pdf(doc, out_path)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a new fillable PDF from JSON.")
    ap.add_argument("template")
    ap.add_argument("output")
    args = ap.parse_args()
    tpl = json.loads(Path(args.template).read_text(encoding="utf-8"))
    summary = render(tpl, args.output)
    emit({"ok": True, "output": args.output, **summary})


if __name__ == "__main__":
    main()

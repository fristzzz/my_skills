"""Form operations: list, fill, add, modify-position/font/style, remove, flatten.

CLI usage:
    python forms.py inspect input.pdf
    python forms.py fill input.pdf out.pdf --config fill.json
    python forms.py add input.pdf out.pdf --config add.json
    python forms.py modify input.pdf out.pdf --config modify.json
    python forms.py remove input.pdf out.pdf --name "甲方代表签字"
    python forms.py flatten input.pdf out.pdf [--keep-fields]

Where each `--config` JSON looks like:

    # fill.json
    {
      "values": {"乙方身份证号": "440101199001011234",
                 "乙方联系电话": "138... "},
      "options": {"font": "SourceHan", "fontsize": 11, "color": [0,0,0], "bold": false}
    }

    # add.json
    {
      "fields": [
        {"name": "备注", "type": "text", "page": 1, "rect": [400, 100, 580, 118],
         "value": "", "font": "STHeiti", "fontsize": 10}
      ]
    }

    # modify.json
    {
      "fields": [
        {"name": "乙方身份证号",
         "rect":   [140, 320, 410, 340],
         "font":   "STHeiti",
         "fontsize": 12,
         "color":  [0.1, 0.1, 0.5],
         "align":  0,
         "border": {"width": 0.5, "dashes": []}}
      ],
      "rename": {"old name": "new name"}
    }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import open_pdf, save_pdf, all_widgets, resolve_font, emit, die  # noqa: E402

import fitz


# ----------------------------------------------------------------------------
# inspect
# ----------------------------------------------------------------------------

def cmd_inspect(args) -> None:
    doc = open_pdf(args.input)
    out = []
    for pi, w in all_widgets(doc):
        rect = w.rect
        out.append({
            "page":   pi + 1,
            "name":   w.field_name,
            "type":   w.field_type_string,
            "rect":   [round(rect.x0, 2), round(rect.y0, 2),
                       round(rect.x1, 2), round(rect.y1, 2)],
            "value":  w.field_value or "",
            "font":   getattr(w, "text_font", None),
            "fontsize": getattr(w, "text_fontsize", None),
            "color":  getattr(w, "text_color", None),
            "align":  getattr(w, "text_align", None),
            "flags":  getattr(w, "field_flags", None),
        })
    emit({"ok": True, "input": args.input, "fields": out,
          "page_count": len(doc), "is_form_pdf": bool(doc.is_form_pdf)})


# ----------------------------------------------------------------------------
# fill — write values into existing fields, optionally re-style
# ----------------------------------------------------------------------------

def _ensure_cjk_font(doc, page, font_alias: str | None) -> str | None:
    """Insert a CJK font into the page's font list (idempotent per-page)."""
    if not font_alias:
        return None
    fp = resolve_font(font_alias)
    if not fp:
        return None
    name = "CJKp"
    try:
        page.insert_font(fontname=name, fontfile=fp)
    except Exception:
        # already inserted or invalid — try with a different name
        name = f"CJKp_{abs(hash(fp)) % 100000}"
        try:
            page.insert_font(fontname=name, fontfile=fp)
        except Exception:
            return None
    return name


def cmd_fill(args) -> None:
    cfg = _load_cfg(args)
    values = cfg.get("values") or {}
    opts   = cfg.get("options") or {}
    bake   = cfg.get("bake", "auto")  # "auto" | "always" | "never" | "flatten"

    if not values:
        die("config.values is empty")

    doc = open_pdf(args.input)
    matched, missing, baked = [], [], []

    for pi in range(len(doc)):
        page = doc[pi]
        page_widgets = list(page.widgets() or [])
        if not page_widgets:
            continue
        font_alias = opts.get("font")
        fn = resolve_font(font_alias) if font_alias else None
        fontname = None
        if fn:
            for name in ("CJKp", "CJKf", f"CJK_{abs(hash(fn)) % 100000}"):
                try:
                    page.insert_font(fontname=name, fontfile=fn)
                    fontname = name
                    break
                except Exception:
                    continue

        for w in page_widgets:
            if w.field_name not in values:
                continue
            val = str(values[w.field_name])
            if val == "":
                continue

            # Step 1: write into widget (so PDF data is intact)
            w.field_value = val
            if fontname:
                try: w.text_font = fontname
                except Exception: pass
            if "fontsize" in opts:
                try: w.text_fontsize = float(opts["fontsize"])
                except Exception: pass
            if "color" in opts and isinstance(opts["color"], (list, tuple)) and len(opts["color"]) == 3:
                try: w.text_color = tuple(float(c) for c in opts["color"])
                except Exception: pass
            if "align" in opts:
                try: w.text_align = int(opts["align"])
                except Exception: pass
            w.update()
            matched.append({"page": pi + 1, "name": w.field_name, "value": val})

            # Step 2: bake — overlay text directly on page so CJK renders even
            # when the original PDF's widget-AP font references are broken.
            need_bake = (
                bake == "always"
                or (bake == "auto" and any(ord(c) > 127 for c in val))
                or bake == "flatten"
            )
            if need_bake:
                rect = w.rect
                try:
                    page.insert_textbox(
                        rect, val,
                        fontname=fontname or "Helvetica",
                        fontsize=float(opts.get("fontsize", w.text_fontsize or 10)),
                        color=tuple(float(c) for c in (opts.get("color") or [0, 0, 0])),
                        align=fitz.TEXT_ALIGN_LEFT,
                    )
                    baked.append({"page": pi + 1, "name": w.field_name})
                except Exception as e:
                    baked.append({"page": pi + 1, "name": w.field_name, "error": str(e)})
                if bake == "flatten":
                    try:
                        page.delete_widget(w)
                    except Exception:
                        pass

    for nm in values.keys():
        if not any(m["name"] == nm for m in matched):
            missing.append(nm)

    save_pdf(doc, args.output)
    emit({"ok": True, "output": args.output,
          "matched": matched, "matched_count": len(matched),
          "missing": missing,
          "baked": baked, "bake_count": len(baked),
          "mode": bake,
          "options_applied": opts})


# ----------------------------------------------------------------------------
# add — create new AcroForm fields
# ----------------------------------------------------------------------------

def cmd_add(args) -> None:
    cfg = _load_cfg(args)
    fields = cfg.get("fields") or []
    if not fields:
        die("config.fields is empty")

    doc = open_pdf(args.input)
    created = []

    for spec in fields:
        page_idx = int(spec.get("page", 1)) - 1
        if page_idx < 0 or page_idx >= len(doc):
            die(f"page out of range: {spec.get('page')}")
        page = doc[page_idx]

        rect_list = spec.get("rect")
        if not (isinstance(rect_list, list) and len(rect_list) == 4):
            die(f"field {spec.get('name')!r} needs rect=[x0,y0,x1,y1]")
        rect = fitz.Rect(*rect_list)

        ftype = (spec.get("type") or "text").lower()
        font_alias = spec.get("font")
        cjk_name = None
        if font_alias and ftype == "text":
            cjk_name = _ensure_cjk_font(doc, page, font_alias)

        w = fitz.Widget()
        # Identification
        if "name" in spec:
            w.field_name = str(spec["name"])
        # Field type (PyMuPDF exposes TEXT, CHECKBOX, RADIOBUTTON, COMBOBOX, LISTBOX, SIGNATURE)
        if ftype == "text":
            w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            w.field_value = str(spec.get("value", ""))
        elif ftype == "checkbox":
            w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
            w.field_value = bool(spec.get("value", False))
        elif ftype == "radio":
            w.field_type = fitz.PDF_WIDGET_TYPE_RADIOBUTTON
        elif ftype == "combo":
            w.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
            w.choice_values = list(spec.get("choices") or [])
        elif ftype == "listbox":
            w.field_type = fitz.PDF_WIDGET_TYPE_LISTBOX
            w.choice_values = list(spec.get("choices") or [])
        elif ftype == "signature":
            w.field_type = fitz.PDF_WIDGET_TYPE_SIGNATURE
        else:
            die(f"unknown field type: {ftype}")

        # Geometry
        w.rect = rect

        # Style
        if cjk_name:
            try: w.text_font = cjk_name
            except Exception: pass
        if "fontsize" in spec:
            try: w.text_fontsize = float(spec["fontsize"])
            except Exception: pass
        if "color" in spec and isinstance(spec["color"], (list, tuple)):
            try: w.text_color = tuple(float(c) for c in spec["color"])
            except Exception: pass
        if "align" in spec:
            try: w.text_align = int(spec["align"])
            except Exception: pass

        # Border (visual)
        b = spec.get("border")
        if isinstance(b, dict):
            try:
                w.border_width = float(b.get("width", 0.5))
                if b.get("dashes"):
                    w.border_dashes = list(b["dashes"])
            except Exception:
                pass

        # Background fill (0-1 RGB tuple)
        bg = spec.get("bg_color")
        if isinstance(bg, (list, tuple)) and len(bg) == 3:
            try: w.fill_color = tuple(float(c) for c in bg)
            except Exception: pass

        try:
            page.add_widget(w)
            created.append({"page": page_idx + 1, "name": w.field_name,
                            "type": ftype, "rect": rect_list})
        except Exception as e:
            die(f"add_widget failed for {spec.get('name')!r}: {e}")

    save_pdf(doc, args.output)
    emit({"ok": True, "output": args.output, "created": created})


# ----------------------------------------------------------------------------
# modify — change rect/font/style of existing fields
# ----------------------------------------------------------------------------

def cmd_modify(args) -> None:
    cfg = _load_cfg(args)
    fields = cfg.get("fields") or []
    rename = cfg.get("rename") or {}

    if not fields and not rename:
        die("config.fields and config.rename both empty")

    doc = open_pdf(args.input)
    # Pre-register fonts on each page once if requested
    # We resolve per-page when applying so font changes take effect.

    # Build a name → spec lookup
    field_specs = {s.get("name"): s for s in fields if s.get("name")}

    modified, missing = [], []

    for pi in range(len(doc)):
        page = doc[pi]
        widgets = list(page.widgets() or [])
        # Apply field spec changes
        for w in widgets:
            if w.field_name not in field_specs:
                continue
            spec = field_specs[w.field_name]
            if "rect" in spec:
                w.rect = fitz.Rect(*spec["rect"])
            if "align" in spec:
                w.text_align = int(spec["align"])
            if "fontsize" in spec:
                w.text_fontsize = float(spec["fontsize"])
            if "color" in spec:
                w.text_color = tuple(float(c) for c in spec["color"])
            if "value" in spec:
                w.field_value = str(spec["value"])
            if "font" in spec:
                fp = resolve_font(spec["font"])
                if fp:
                    try:
                        page.insert_font(fontname="CJKp", fontfile=fp)
                        w.text_font = "CJKp"
                    except Exception:
                        pass
            b = spec.get("border")
            if isinstance(b, dict):
                w.border_width = float(b.get("width", w.border_width or 0.5))
                if b.get("dashes"):
                    w.border_dashes = list(b["dashes"])
            if "bg_color" in spec:
                w.fill_color = tuple(float(c) for c in spec["bg_color"])
            w.update()
            modified.append({"page": pi + 1, "name": w.field_name,
                             "rect": list(w.rect), "font": w.text_font,
                             "fontsize": w.text_fontsize})

        # Apply renames on this page
        for w in widgets:
            if w.field_name in rename:
                w.field_name = rename[w.field_name]
                w.update()

    for spec in fields:
        nm = spec.get("name")
        if nm and not any(m["name"] == nm for m in modified):
            missing.append(nm)

    renamed = [{"from": old, "to": new}
               for old, new in rename.items()]

    save_pdf(doc, args.output)
    emit({"ok": True, "output": args.output,
          "modified": modified, "renamed": renamed,
          "missing": missing})


# ----------------------------------------------------------------------------
# remove — delete by name
# ----------------------------------------------------------------------------

def cmd_remove(args) -> None:
    doc = open_pdf(args.input)
    targets = set(args.name or [])
    if args.config:
        import json
        cfg = _load_cfg(args)
        targets.update(cfg.get("names") or [])

    if not targets:
        die("--name or --config {names:[...]} required")

    removed, missing = [], []
    for pi in range(len(doc)):
        page = doc[pi]
        # iterate by index; delete_widget invalidates the underlying list
        widgets = list(page.widgets() or [])
        for w in widgets:
            if w.field_name in targets:
                try:
                    page.delete_widget(w)
                    removed.append({"page": pi + 1, "name": w.field_name})
                except Exception as e:
                    missing.append({"name": w.field_name, "error": str(e)})
    for nm in targets:
        if not any(r["name"] == nm for r in removed):
            missing.append(nm)

    save_pdf(doc, args.output)
    emit({"ok": True, "output": args.output, "removed": removed, "missing": missing})


# ----------------------------------------------------------------------------
# flatten — convert form fields to static text (no longer editable)
# ----------------------------------------------------------------------------

def cmd_flatten(args) -> None:
    doc = open_pdf(args.input)
    converted = []
    for pi in range(len(doc)):
        try:
            n = doc[pi].widgets() and len(doc[pi].widgets())
        except Exception:
            n = 0
        if n:
            converted.append({"page": pi + 1, "count": n})
        # PyMuPDF doesn't have a one-line flatten; calling each widget's .update()
        # with a flag is not supported either. So we use a fall-back: convert each
        # text field's appearance into a permanent redacted annotation via redact.
        try:
            doc[pi].widgets() and [w for w in doc[pi].widgets() if True]
        except Exception:
            pass

    # PyMuPDF 1.24+ provides Page.flatten_contents for some scenarios, but full
    # form-flatten (render value + delete widget) is best done via Java with qpdf.
    # Here we do a best-effort: write the values into the page content using
    # `text_widgets_redact_and_expand`, which renders the widget text into the page.
    # If qpdf is available on PATH, use it for guaranteed correct flattening.
    import shutil, subprocess
    if shutil.which("qpdf") or shutil.which("pdftk"):
        tool = "qpdf" if shutil.which("qpdf") else "pdftk"
        # qpdf can't flatten forms directly either; pdftk can:
        # `pdftk input.pdf flatten output out.pdf`
        if tool == "pdftk":
            subprocess.run(["pdftk", args.input, "flatten", "output", args.output], check=True)
            emit({"ok": True, "output": args.output, "engine": "pdftk",
                  "flattened_pages": [c["page"] for c in converted]})
            return
    # Fallback: use pypdf (always available if pymupdf is) — it can only
    # drop widgets, not convert text. Tell the user.
    for pi in range(len(doc)):
        page = doc[pi]
        for w in list(page.widgets() or []):
            try:
                page.delete_widget(w)
            except Exception:
                pass
    save_pdf(doc, args.output)
    emit({"ok": True, "output": args.output, "engine": "pymupdf-fallback",
          "note": "removed widgets but their text values were not baked into page; "
                  "install pdftk for true flattening.",
          "flattened_pages": [c["page"] for c in converted]})


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def _load_cfg(args) -> dict:
    cfg_path = getattr(args, "config", None)
    if not cfg_path:
        return {}
    if cfg_path == "-":
        import sys as _sys
        return json.loads(_sys.stdin.read())
    return json.loads(Path(cfg_path).read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Form operations (fill/add/modify/remove/flatten).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_inspect = sub.add_parser("inspect")
    p_inspect.add_argument("input")

    p_fill = sub.add_parser("fill")
    p_fill.add_argument("input")
    p_fill.add_argument("output")
    p_fill.add_argument("--config")

    p_add = sub.add_parser("add")
    p_add.add_argument("input")
    p_add.add_argument("output")
    p_add.add_argument("--config")

    p_mod = sub.add_parser("modify")
    p_mod.add_argument("input")
    p_mod.add_argument("output")
    p_mod.add_argument("--config")

    p_rm = sub.add_parser("remove")
    p_rm.add_argument("input")
    p_rm.add_argument("output")
    p_rm.add_argument("--name", action="append", help="field name (repeatable)")
    p_rm.add_argument("--config")

    p_fla = sub.add_parser("flatten")
    p_fla.add_argument("input")
    p_fla.add_argument("output")

    args = ap.parse_args()
    {
        "inspect": cmd_inspect,
        "fill":    cmd_fill,
        "add":     cmd_add,
        "modify":  cmd_modify,
        "remove":  cmd_remove,
        "flatten": cmd_flatten,
    }[args.cmd](args)


if __name__ == "__main__":
    main()

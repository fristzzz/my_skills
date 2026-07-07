"""Shared helpers for the pdf-toolkit scripts.

Lives at <skill>/scripts/_common.py and is importable by sibling scripts via:

    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import ...

Keep this file lean: only stuff reused by 2+ scripts. Anything one-shot
belongs inline in that script.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import fitz  # PyMuPDF


# ----------------------------------------------------------------------------
# Console: print compact JSON so the LLM can parse output safely
# ----------------------------------------------------------------------------

def emit(payload: Any) -> None:
    """Print a JSON payload to stdout (always compact, UTF-8)."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                     if not isinstance(payload, str) else payload)
    sys.stdout.write("\n")
    sys.stdout.flush()


def die(msg: str, code: int = 1) -> None:
    emit({"ok": False, "error": msg})
    sys.exit(code)


# ----------------------------------------------------------------------------
# File loading / saving
# ----------------------------------------------------------------------------

def open_pdf(path: str | os.PathLike) -> fitz.Document:
    p = Path(path).expanduser()
    if not p.exists():
        die(f"PDF not found: {p}")
    return fitz.open(p)


def save_pdf(doc: fitz.Document, path: str | os.PathLike, *,
             garbage: int = 4, deflate: bool = True,
             deflate_images: bool = True, deflate_fonts: bool = True) -> None:
    """Save with sane defaults: garbage collect, deflate streams, deflate images/fonts."""
    out = str(Path(path).expanduser())
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    doc.save(out, garbage=garbage, deflate=deflate,
             deflate_images=deflate_images, deflate_fonts=deflate_fonts)


# ----------------------------------------------------------------------------
# CLI config helpers — accept JSON via --config or stdin
# ----------------------------------------------------------------------------

def load_config(args) -> dict:
    """args is the argparse namespace; looks for args.config (path) or stdin JSON."""
    cfg_path = getattr(args, "config", None)
    if cfg_path and cfg_path != "-":
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    if cfg_path == "-" or not sys.stdin.isatty():
        raw = sys.stdin.read()
        if raw.strip():
            return json.loads(raw)
    return {}


def merge_kwargs(cfg: dict, **defaults) -> dict:
    """Apply defaults + overrides from a config dict (skips nulls)."""
    out = dict(defaults)
    if cfg:
        out.update({k: v for k, v in cfg.items() if v is not None})
    return out


# ----------------------------------------------------------------------------
# Font resolution — find CJK fonts on macOS / Linux / Windows
# ----------------------------------------------------------------------------

# User-friendly font aliases → search order across common paths
_FONT_HINTS = {
    "auto":     [],  # meaning "pick first available CJK cap-able font"
    "hei":      ["STHeiti Medium.ttc", "SimHei.ttf", "NotoSansCJKsc-Regular.otf", "wqy-microhei.ttc"],
    "song":     ["SimSun.ttf", "NSimSun.ttf", "STSong.ttf", "SourceHanSerif-VF.otf.ttc", "NotoSerifCJKsc-Regular.otf"],
    "kai":      ["STKaiti.ttf", "KaiTi.ttf", "STKaiti.ttc"],
    "fang":     ["PingFang.ttc", "PingFangSC-Regular.otf"],
    "yahei":    ["Microsoft_YaHei.ttf", "msyh.ttc", "Microsoft YaHei.ttf"],
    "sourcehan":["SourceHanSans-VF.otf.ttc", "SourceHanSerif-VF.otf.ttc"],
    "noto":     ["NotoSansCJKsc-Regular.otf", "NotoSerifCJKsc-Regular.otf"],
    "helvetica":["Helvetica.ttf"],
}

_SEARCH_ROOTS = [
    "/System/Library/Fonts",
    "/Library/Fonts",
    Path.home() / "Library" / "Fonts",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "/opt/homebrew/share/fonts",
    "C:/Windows/Fonts",
]

def search_font(candidates: Iterable[str]) -> str | None:
    """Walk macOS / Linux font dirs and return the first existing match."""
    for root in _SEARCH_ROOTS:
        root = Path(root).expanduser()
        if not root.exists():
            continue
        # try both at root and one level down (Supplemental/, WPS Compatible/, etc.)
        for sub in ("", "Supplemental", "WPS Compatible", "PublicOffice", "truetype", "opentype"):
            base = root / sub if sub else root
            for c in candidates:
                p = base / c
                if p.exists():
                    return str(p)
                # case-insensitive fallback
                if base.is_dir():
                    for actual in base.iterdir():
                        if actual.name.lower() == c.lower():
                            return str(actual)
    return None


def resolve_font(name_or_path: str | None) -> str | None:
    """Accept:
       - explicit path (contains a separator OR ends in .ttf/.otf/.ttc)
       - bare filename like 'SimSun.ttf'
       - alias: 'hei', 'song', 'kai', 'fang', 'yahei', 'sourcehan', 'noto', 'helvetica', 'auto'
       - PDF font basefont like 'Heiti' / 'Helvetica-Bold'
       - None  (returns None, caller decides what to do)
    Returns absolute path or None.
    """
    if not name_or_path:
        return None
    s = str(name_or_path).strip()
    # explicit path
    if ("/" in s or "\\" in s) and Path(s).expanduser().exists():
        return str(Path(s).expanduser())
    if s.lower().endswith((".ttf", ".otf", ".ttc")):
        # bare filename lookup
        hit = search_font([s])
        if hit:
            return hit
    # alias
    key = re.sub(r"[^a-z0-9]", "", s.lower())
    aliases = {"hei": "hei", "song": "song", "kai": "kai", "fang": "fang",
               "yahei": "yahei", "msyh": "yahei", "sourcehan": "sourcehan",
               "noto": "noto", "auto": "auto", "helvetica": "helvetica",
               "hei2": "hei"}
    bucket = _FONT_HINTS.get(aliases.get(key, ""), None)
    if bucket is not None:
        hit = search_font(bucket)
        if hit:
            return hit
    # last resort: PDF basefont-like
    basefont_match = search_font([s, f"{s}.ttf", f"{s}.otf", f"{s}.ttc",
                                  f"{s}-Regular.ttf", f"{s.replace('-', '')}.ttf",
                                  "STHeiti Medium.ttc"])
    return basefont_match


def list_system_cjk_fonts() -> list[dict]:
    """Return a JSON-friendly list of CJK-capable system fonts (best-effort)."""
    out = []
    for c in _FONT_HINTS["song"] + _FONT_HINTS["hei"] + _FONT_HINTS["kai"] \
            + _FONT_HINTS["fang"] + _FONT_HINTS["yahei"] + _FONT_HINTS["sourcehan"]:
        p = search_font([c])
        if p:
            out.append({"alias": c, "path": p})
    # dedupe by path
    seen, unique = set(), []
    for x in out:
        if x["path"] in seen:
            continue
        seen.add(x["path"])
        unique.append(x)
    return unique


# ----------------------------------------------------------------------------
# PyMuPDF widget property helpers — these are tolerant across versions
# ----------------------------------------------------------------------------

def all_widgets(doc: fitz.Document) -> list[tuple[int, fitz.Widget]]:
    """Yield (page_index, widget) tuples for every widget in the document."""
    out: list[tuple[int, fitz.Widget]] = []
    for pi, page in enumerate(doc):
        try:
            ws = page.widgets() or []
        except Exception:
            ws = []
        for w in ws:
            out.append((pi, w))
    return out


def widget_summary(w: fitz.Widget) -> dict:
    """Tolerant read of widget state — works across PyMuPDF versions."""
    def _g(name, default=None):
        try:
            v = getattr(w, name)
            return v() if callable(v) else v
        except Exception:
            return default
    return {
        "name":     _g("field_name"),
        "type":     _g("field_type_string"),
        "rect":     [round(x, 2) for x in (_g("rect", fitz.Rect()).rect if hasattr(_g("rect", None), "rect") else _g("rect", []))],
        "value":    _g("field_value"),
        "font":     _g("text_font"),
        "fontsize": _g("text_fontsize"),
        "color":    _g("text_color"),
        "align":    _g("text_align"),
    }

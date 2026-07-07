"""Basic PDF operations: merge, split, rotate, watermark, pages, metadata, encrypt.

CLI:
    python ops.py merge        inputs.json out.pdf
    python ops.py split        in.pdf out_dir --ranges "1-3,5"   # "all" or "1,3-5"
    python ops.py rotate       in.pdf out.pdf --pages 1-3 --degrees 90
    python ops.py watermark    in.pdf out.pdf --config wm.json
    python ops.py pages        in.pdf [delete|insert|reorder] --config pages.json
    python ops.py metadata     in.pdf [--config meta.json]
    python ops.py encrypt      in.pdf out.pdf --user pwd [--owner opwd]
    python ops.py decrypt      in.pdf out.pdf
    python ops.py extract      in.pdf out_dir   # text + images

Configs:

    inputs.json — {"inputs": ["a.pdf", "b.pdf", ...]}
    wm.json     — {"items": [{"page": "all"|int, "text": "...", "image": "...", ...}]}
    pages.json  — for delete:  {"remove": [2, 4]}
                  for insert:  {"insert_after": 3, "from_pdf": "b.pdf", "pages": "1-2"}
                  for reorder: {"new_order": [3,1,2,4,5]}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import open_pdf, save_pdf, emit, die  # noqa: E402

import fitz


# ----------------------------------------------------------------------------
# merge
# ----------------------------------------------------------------------------

def cmd_merge(args) -> None:
    cfg = _load_cfg(args)
    inputs = cfg.get("inputs") or []
    if not inputs:
        die("inputs.json needs `inputs` array")
    out_doc = fitz.open()
    merged = []
    for p in inputs:
        if not Path(p).exists():
            die(f"missing input: {p}")
        d = fitz.open(p)
        merged.append({"path": p, "pages": len(d)})
        out_doc.insert_pdf(d)
    save_pdf(out_doc, args.output)
    emit({"ok": True, "output": args.output, "merged": merged,
          "total_pages": len(out_doc)})


# ----------------------------------------------------------------------------
# split — by ranges or one-per-page
# ----------------------------------------------------------------------------

def cmd_split(args) -> None:
    cfg_path = getattr(args, "config", None)
    ranges = args.ranges
    if cfg_path:
        cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        ranges = cfg.get("ranges", ranges)
    if ranges == "all":
        # one PDF per page
        d = open_pdf(args.input)
        out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
        stem = Path(args.input).stem
        files = []
        for i, page in enumerate(d, start=1):
            sub = fitz.open()
            sub.insert_pdf(d, from_page=i-1, to_page=i-1)
            out_path = out / f"{stem}__page{i:03d}.pdf"
            sub.save(str(out_path), garbage=4, deflate=True)
            files.append(str(out_path))
        emit({"ok": True, "mode": "all", "files": files, "count": len(files)})
        return
    ranges = ranges or "1"
    splits = _parse_ranges(ranges, len(open_pdf(args.input)))
    d = open_pdf(args.input)
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    stem = Path(args.input).stem
    files = []
    for i, (s, e) in enumerate(splits, start=1):
        sub = fitz.open()
        sub.insert_pdf(d, from_page=s-1, to_page=e-1)
        name = f"{stem}__p{s:03d}-{e:03d}.pdf" if s != e else f"{stem}__p{s:03d}.pdf"
        out_path = out / name
        sub.save(str(out_path), garbage=4, deflate=True)
        files.append(str(out_path))
    emit({"ok": True, "ranges": ranges, "files": files})


def _parse_ranges(spec: str, page_count: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a), int(b)
        else:
            a = b = int(part)
        out.append((max(1, a), min(page_count, b)))
    return out


# ----------------------------------------------------------------------------
# rotate
# ----------------------------------------------------------------------------

def cmd_rotate(args) -> None:
    d = open_pdf(args.input)
    pages = list(_parse_ranges(args.pages or "all", len(d)))
    rotated = []
    for s, e in pages:
        for i in range(s - 1, e):
            try:
                current = d[i].rotation
            except Exception:
                current = 0
            d[i].set_rotation((current + args.degrees) % 360)
            rotated.append(i + 1)
    save_pdf(d, args.output)
    emit({"ok": True, "output": args.output, "rotated": rotated,
          "degrees": args.degrees})


# ----------------------------------------------------------------------------
# watermark — text or image on every page or a specific page
# ----------------------------------------------------------------------------

def cmd_watermark(args) -> None:
    cfg = _load_cfg(args)
    items = cfg.get("items") or []
    if not items:
        die("watermark config needs `items` array")
    d = open_pdf(args.input)
    placed = []
    for it in items:
        target_pages: list[int]
        if it.get("page") in (None, "all"):
            target_pages = list(range(len(d)))
        else:
            target_pages = [int(it["page"]) - 1]
        if "image" in it:
            ipath = str(Path(it["image"]).expanduser())
            for pi in target_pages:
                rect = fitz.Rect(*_resolve_rect(it, d[pi]))
                d[pi].insert_image(rect, filename=ipath,
                                   keep_proportion=bool(it.get("keep_proportion", True)))
                placed.append({"page": pi + 1, "image": ipath})
        if "text" in it:
            from _common import resolve_font  # local import — circular safety
            fp = resolve_font(it.get("font") or "hei")
            for pi in target_pages:
                page = d[pi]
                fontname = "WM"
                if fp:
                    try:
                        page.insert_font(fontname=fontname, fontfile=fp)
                    except Exception:
                        fontname = f"WM_{abs(hash(fp)) % 100000}"
                        try: page.insert_font(fontname=fontname, fontfile=fp)
                        except Exception: fontname = "Helvetica"
                rect = fitz.Rect(*_resolve_rect(it, page))
                page.insert_textbox(
                    rect, str(it["text"]),
                    fontname=fontname,
                    fontsize=float(it.get("fontsize", 36)),
                    color=tuple(float(c) for c in (it.get("color") or [0.8, 0.1, 0.1])),
                    rotate=int(it.get("rotate", -30)),
                )
                placed.append({"page": pi + 1, "text": it["text"]})
    save_pdf(d, args.output)
    emit({"ok": True, "output": args.output, "placed": placed})


def _resolve_rect(it: dict, page) -> list[float]:
    """Accept rect=[x0,y0,x1,y1] or anchor/corners or auto=full-page center."""
    if "rect" in it:
        return list(it["rect"])
    # shorthand: full page centered with margins
    r = page.rect
    m = it.get("margin", 36)
    return [r.x0 + m, r.y0 + m, r.x1 - m, r.y1 - m]


# ----------------------------------------------------------------------------
# pages — delete / insert / reorder
# ----------------------------------------------------------------------------

def cmd_pages(args) -> None:
    action = args.action
    cfg = _load_cfg(args)
    d = open_pdf(args.input)
    before = len(d)

    if action == "delete":
        rm = set(int(x) - 1 for x in (cfg.get("remove") or []))
        keep = [i for i in range(len(d)) if i not in rm]
        new = fitz.open()
        for i in keep:
            new.insert_pdf(d, from_page=i, to_page=i)
        save_pdf(new, args.output)
        emit({"ok": True, "output": args.output, "before": before,
              "after": len(new), "removed": sorted(p + 1 for p in rm)})

    elif action == "insert":
        idx = int(cfg.get("insert_after", 0)) - 1  # insert after page N
        from_pdf = cfg.get("from_pdf")
        if not from_pdf:
            die("pages.insert needs from_pdf")
        src = fitz.open(from_pdf)
        if "pages" in cfg:
            sub_ranges = _parse_ranges(str(cfg["pages"]), len(src))
        else:
            sub_ranges = [(1, len(src))]
        new = fitz.open()
        # copy pages [0..idx] from d, then src sub_ranges, then rest of d
        first_chunk_end = idx
        if first_chunk_end >= 0:
            new.insert_pdf(d, from_page=0, to_page=first_chunk_end)
        for s, e in sub_ranges:
            new.insert_pdf(src, from_page=s - 1, to_page=e - 1)
        if idx + 1 < len(d):
            new.insert_pdf(d, from_page=idx + 1, to_page=len(d) - 1)
        save_pdf(new, args.output)
        emit({"ok": True, "output": args.output, "before": before,
              "after": len(new)})

    elif action == "reorder":
        order = cfg.get("new_order")
        if not order:
            die("pages.reorder needs new_order (1-indexed)")
        # Build new doc by reading in order
        new = fitz.open()
        for n in order:
            new.insert_pdf(d, from_page=n - 1, to_page=n - 1)
        save_pdf(new, args.output)
        emit({"ok": True, "output": args.output, "new_order": order,
              "page_count": len(new)})

    else:
        die(f"unknown pages action: {action}")


# ----------------------------------------------------------------------------
# metadata
# ----------------------------------------------------------------------------

def cmd_metadata(args) -> None:
    d = open_pdf(args.input)
    if args.config:
        cfg = _load_cfg(args)
        for k, v in cfg.items():
            try:
                d.set_metadata({k: v})
            except Exception:
                pass
        save_pdf(d, args.output or args.input)
        emit({"ok": True, "applied": cfg, "output": args.output or args.input})
    else:
        emit({"ok": True, "input": args.input, "metadata": dict(d.metadata)})


# ----------------------------------------------------------------------------
# encrypt / decrypt
# ----------------------------------------------------------------------------

def cmd_encrypt(args) -> None:
    d = open_pdf(args.input)
    perms = fitz.PDF_PERM_DEFAULT
    # restrict printing/copying if requested
    if args.no_copy: perms &= ~fitz.PDF_PERM_COPY
    if args.no_print: perms &= ~fitz.PDF_PERM_PRINT
    owner_pwd = args.owner or args.user
    out = str(Path(args.output).expanduser())
    # PyMuPDF security model
    d.save(out, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=owner_pwd,
           user_pw=args.user, permissions=perms)
    emit({"ok": True, "output": out, "user_pwd_set": bool(args.user),
          "owner_pwd_set": bool(owner_pwd), "perms": int(perms)})


def cmd_decrypt(args) -> None:
    d = fitz.open(args.input)
    if d.is_encrypted:
        if not d.authenticate(args.password or ""):
            die("invalid password")
    d.save(args.output, encryption=fitz.PDF_ENCRYPT_KEEP)
    emit({"ok": True, "output": args.output, "encrypted_input": bool(d.is_encrypted)})


# ----------------------------------------------------------------------------
# extract — text + images, page by page
# ----------------------------------------------------------------------------

def cmd_extract(args) -> None:
    d = open_pdf(args.input)
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    stem = Path(args.input).stem

    written = {"text": [], "images": [], "tables_json": []}
    for pi, page in enumerate(d, start=1):
        txt = page.get_text("text")
        if txt.strip():
            p = out / f"{stem}__p{pi:03d}.txt"
            p.write_text(txt, encoding="utf-8")
            written["text"].append(str(p))
        for ii, img in enumerate(page.get_images(full=True), start=1):
            xref = img[0]
            try:
                pix = fitz.Pixmap(d, xref)
                if pix.n - pix.alpha > 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                ext = "png"
                ip = out / f"{stem}__p{pi:03d}_img{ii:02d}.{ext}"
                pix.save(str(ip))
                written["images"].append(str(ip))
            except Exception as e:
                written["images"].append({"page": pi, "xref": xref, "error": str(e)})
    emit({"ok": True, **written, "page_count": len(d)})


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def _load_cfg(args) -> dict:
    p = getattr(args, "config", None)
    if not p:
        return {}
    if p == "-":
        return json.loads(sys.stdin.read())
    return json.loads(Path(p).read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Basic PDF operations.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("merge")
    s.add_argument("config"); s.add_argument("output")

    s = sub.add_parser("split")
    s.add_argument("input"); s.add_argument("out_dir")
    s.add_argument("--ranges", default="all")
    s.add_argument("--config")

    s = sub.add_parser("rotate")
    s.add_argument("input"); s.add_argument("output")
    s.add_argument("--pages", default="all")
    s.add_argument("--degrees", type=int, required=True)

    s = sub.add_parser("watermark")
    s.add_argument("input"); s.add_argument("output"); s.add_argument("--config")

    s = sub.add_parser("pages")
    s.add_argument("input"); s.add_argument("action", choices=["delete", "insert", "reorder"])
    s.add_argument("output"); s.add_argument("--config")

    s = sub.add_parser("metadata")
    s.add_argument("input"); s.add_argument("output", nargs="?")
    s.add_argument("--config")

    s = sub.add_parser("encrypt")
    s.add_argument("input"); s.add_argument("output")
    s.add_argument("--user", required=True); s.add_argument("--owner")
    s.add_argument("--no-copy", action="store_true"); s.add_argument("--no-print", action="store_true")

    s = sub.add_parser("decrypt")
    s.add_argument("input"); s.add_argument("output"); s.add_argument("--password")

    s = sub.add_parser("extract")
    s.add_argument("input"); s.add_argument("out_dir")

    args = ap.parse_args()
    {
        "merge":     cmd_merge,
        "split":     cmd_split,
        "rotate":    cmd_rotate,
        "watermark": cmd_watermark,
        "pages":     cmd_pages,
        "metadata":  cmd_metadata,
        "encrypt":   cmd_encrypt,
        "decrypt":   cmd_decrypt,
        "extract":   cmd_extract,
    }[args.cmd](args)


if __name__ == "__main__":
    main()

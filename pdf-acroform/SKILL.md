---
name: pdf-acroform
description: |
  Create, modify, fill, and operate on PDF forms and documents locally. USE
  THIS SKILL whenever the user wants to do anything to a PDF file, including:
  fill in form fields (AcroForm), add new form fields, change field position
  / style / font / color / border, generate a fillable PDF from scratch, batch-fill
  a template across many records, overlay text/images onto a non-editable PDF
  (the kind that just has blank lines), merge / split / rotate / reorder pages,
  add a text or image watermark, encrypt or decrypt, read or set metadata
  (title/author/...), extract text and images, or build a "fill-PDF" pipeline.
  Especially useful for Chinese / CJK contracts and forms (劳动合同 / 顾问协议 /
  申请表 / NDA / 发票 etc.) where AcroForm field names are Chinese. If a PDF
  file path is mentioned and the action is "do X to it", use this skill — do
  not improvise with raw shell calls.
license: MIT
metadata:
  primary-interface: bash + python (PyMuPDF / pypdf / reportlab)
  author: pdf-toolkit
compatibility: |
  Python 3.10+ with PyMuPDF (fitz), pypdf, reportlab, pdfplumber.
  For Chinese fonts: macOS ships STHeiti; Source Han Sans/Serif is the best
  free fallback. Optional: qpdf / pdftk for true form-flatten.
---

# PDF Toolkit

A small, opinionated set of Python scripts that cover the everyday things you
actually want to do with a PDF: forms, overlay, merge/split/rotate, watermark,
metadata, encrypt, extract. No browser, no API key, no cloud.

**Companion skill:** for *reading* a PDF (text extraction, OCR, screenshots),
use the existing **`parse-document`** skill. This skill focuses on *writing*
and *operating on* PDFs.

---

## When to reach for what

The decision tree:

1. **Does the PDF already have fillable AcroForm fields?**
   - **Yes** → `forms.py` (fill / add / modify / remove / flatten)
   - **No, but I see blank lines where text should go** → `overlay.py`
2. **User wants to author a NEW fillable PDF from scratch** →
   `build_pdf.py` (see [Authoring from scratch](#authoring-from-scratch))
3. **User wants page-level ops or utility** (merge / split / rotate /
   watermark / metadata / encrypt / extract) → `ops.py`
4. **First time touching this file — what does it contain?** → `info.py`

If you only know the user's intent (e.g. "fill this PDF"), run
`info.py` first. It costs ~50 ms and tells you whether to use
`forms.py` (has AcroForm) or `overlay.py` (does not).

---

## Quick start (60 seconds)

```bash
SKILL=~/.pi/agent/skills/pdf-toolkit/scripts

# 1) see what we are dealing with
python $SKILL/info.py /path/to/file.pdf

# 2a) it has fields: fill them
python $SKILL/forms.py fill input.pdf filled.pdf --config fill.json

# 2b) it has no fields, just blank lines: overlay text at coords
python $SKILL/overlay.py text input.pdf filled.pdf --config overlay.json

# 3) generate a *new* fillable PDF from a JSON layout
python $SKILL/build_pdf.py template.json out.pdf
```

The scripts emit one-line JSON on stdout. Errors are also JSON.

---

## Forms (`forms.py`)

Sub-commands: `inspect | fill | add | modify | remove | flatten`.

### Inspect

```bash
python forms.py inspect contract.pdf
# → {"ok": true, "fields": [{"page": 1, "name": "乙方身份证号", "rect": [...],
#                            "value": "", "font": "...", "fontsize": 11, ...}, ...]}
```

### Fill existing fields

`fill.json`:
```json
{
  "values": {
    "乙方身份证号":      "440101199001011234",
    "乙方联系电话":      "13800138000",
    "乙方住所":          "深圳市南山区...",
    "乙方电子邮箱":      "jam@example.com"
  },
  "options": {"font": "SourceHan", "fontsize": 11, "color": [0.05, 0.1, 0.3]},
  "bake": "auto"
}
```

```bash
python forms.py fill contract.pdf contract_filled.pdf --config fill.json
```

`bake` controls how the value reaches the page:

| `bake` value | Behaviour |
|---|---|
| `"auto"` (default) | set widget value normally; if value has non-ASCII, also overlay text directly on page so CJK / accented Latin renders correctly even when the widget's AP font reference is broken |
| `"always"` | always overlay (use when you know CJK will not render via widget AP) |
| `"never"` | never overlay (pure widget mode — fast, but visual rendering depends on the PDF's font setup) |
| `"flatten"` | overlay text then delete the widget — produces a non-editable, fully baked PDF |

`font` accepts: `hei`, `song`, `kai`, `fang`, `yahei`, `sourcehan`, `noto`,
or an absolute path. The script scans the system for a match and registers it
on each affected page.

### Add new fields

`add.json`:
```json
{
  "fields": [
    {"name": "备注",  "type": "text",  "page": 1,
     "rect": [400, 100, 580, 118], "value": "免契税",
     "font": "STHeiti", "fontsize": 10},

    {"name": "agree", "type": "checkbox", "page": 11,
     "rect": [100, 700, 112, 712], "value": false},

    {"name": "title", "type": "combo", "page": 1,
     "rect": [120, 60, 320, 78],
     "choices": ["先生", "女士", "公司"], "value": "先生"}
  ]
}
```

Supported `type` values: `text`, `checkbox`, `radio`, `combo`, `listbox`,
`signature`.

### Modify existing fields (position / font / style)

```json
{
  "fields": [
    {"name": "乙方身份证号",
     "rect":   [140, 320, 410, 340],
     "fontsize": 12,
     "color":  [0.7, 0.05, 0.05],
     "align":  0,
     "border": {"width": 0.5, "dashes": [2, 2]}},
    {"name": "乙方联系电话",
     "bg_color": [0.97, 0.97, 1.0]}
  ],
  "rename": {"old_name": "new_name"}
}
```

You can rename, move, change `fontsize`, `color` (RGB 0–1), `align`, add
borders (with optional dash pattern), and change background fill.

**`font` name vs visual font face**: PyMuPDF only accepts the four standard
PDF base fonts for `widget.text_font` — `Helv` (Helvetica), `TiRo` (Times
Roman), `Cour` (Courier), `Sym` (Symbol). Any other name is silently
coerced back to `Helv`. This means changing the *font face* (e.g. SimSun →
KaiTi) on an existing field requires `bake: "always"` or `bake: "flatten"`
via `fill`. Accept `fontsize`, `color`, `align`, `bg_color`, `border`
changes immediately; rely on `fill --bake always` to actually rebuild the
visual font face.

### Remove / flatten

```bash
python forms.py remove  contract.pdf contract_no_audit.pdf --name "审计字段1" --name "审计字段2"
python forms.py flatten contract.pdf contract_static.pdf
```

`flatten` converts fields to non-editable text. Best-effort: if
`pdftk` is installed it is used; otherwise the script removes the
field objects but text appearance may not be baked — verify visually.

---

## Overlay (`overlay.py`) — when the PDF is NOT a form

Many "fillable" PDFs in the wild are not real AcroForm documents —
they are plain PDFs with blank lines or labelled boxes drawn as part
of the layout. To "fill" these, you render text (or an image) at
specific coordinates.

`overlay.json`:
```json
{
  "items": [
    {"page": 1, "rect": [165, 343, 405, 355], "text": "440101199001011234",
     "font": "STHeiti", "fontsize": 10, "color": [0.05, 0.1, 0.3]},
    {"page": 1, "rect": [165, 359, 405, 371], "text": "深圳市南山区...",
     "font": "STHeiti", "fontsize": 10},

    {"page": 1, "rect": [148, 474, 442, 486], "text": "陈政羽", "align": "center",
     "font": "STHeiti", "fontsize": 14, "color": [0, 0, 0.7]},

    {"page": 1, "rect": [165, 343, 405, 355], "image": "/abs/signatures/jam.png",
     "keep_proportion": true}
  ]
}
```

`rect` is `[x0, y0, x1, y1]` in PDF user-space (72 dpi), **with y = 0 at the
top** (the script flips internally so you can think top-left). To find the
right coordinates, take a screenshot of the relevant page with the
`parse-document` skill (`document_screenshot`) and measure.

---

## Operations (`ops.py`)

| Action | Command |
|---|---|
| Merge N PDFs | `ops.py merge inputs.json out.pdf` |
| Split into ranges | `ops.py split in.pdf out_dir --ranges "1-3,5"` |
| Split one per page | `ops.py split in.pdf out_dir --ranges all` |
| Rotate pages | `ops.py rotate in.pdf out.pdf --pages 1-3 --degrees 90` |
| Watermark | `ops.py watermark in.pdf out.pdf --config wm.json` |
| Delete pages | `ops.py pages in.pdf delete out.pdf --config p.json` |
| Insert pages | `ops.py pages in.pdf insert out.pdf --config p.json` |
| Reorder pages | `ops.py pages in.pdf reorder out.pdf --config p.json` |
| Read meta | `ops.py metadata in.pdf` |
| Set meta | `ops.py metadata in.pdf out.pdf --config meta.json` |
| Encrypt (AES-256) | `ops.py encrypt in.pdf out.pdf --user pw` |
| Decrypt | `ops.py decrypt in.pdf out.pdf --password pw` |
| Extract text+images | `ops.py extract in.pdf out_dir` |

`watermark` can be text or image, on a specific page or all pages,
with rotation (e.g. `-30°` for diagonal "DRAFT" stamps).

---

## Batch-filling a template across many records

The most common real-world use. Pseudocode:

```python
import json, subprocess, pathlib
SKILL = pathlib.Path.home() / ".pi/agent/skills/pdf-toolkit/scripts"

records = json.loads(Path("records.json").read_text())  # list of dicts
for i, r in enumerate(records):
    cfg = {"values": r, "options": {"font": "SourceHan", "fontsize": 11}}
    Path(f"cfg_{i}.json").write_text(json.dumps(cfg, ensure_ascii=False))
    subprocess.check_call([
        "python", str(SKILL / "forms.py"), "fill",
        "template.pdf", f"out_{i:04d}.pdf",
        "--config", f"cfg_{i}.json",
    ])
```

For a JSON schema describing the field values, just iterate over a CSV
and turn each row into the `values` dict.

---

## Authoring from scratch

For generating a *new* fillable PDF (e.g. from a JSON layout):

```json
{
  "page_size": "A4",                  // "A4" | "Letter" | [w, h] points
  "pages": [
    {
      "blocks": [
        {"type": "text",  "x": 200, "y": 60, "fontsize": 18,
         "text": "Tapdata 顾问协议", "font": "SourceHan", "weight": "bold"},
        {"type": "field", "name": "乙方身份证号", "x": 140, "y": 342,
         "width": 264, "fontsize": 10, "font": "STHeiti"},
        {"type": "rule",  "x0": 140, "y0": 354, "x1": 404, "y1": 354,
         "thickness": 0.5},
        {"type": "image", "x": 460, "y": 60, "w": 80, "h": 80,
         "path": "logo.png"}
      ]
    }
  ]
}
```

If the user wants to author new templates, also mention **Typst** (already
shipped as `typst-writing-document` skill in pi) — Typst with its `form`
syntax is *the* fastest way to make fillable PDFs in 2025+, and any template
written in Typst is far easier to maintain than a `build_pdf.py` JSON.
Prefer Typst unless the user explicitly wants pure-Python.

---

## Font resolution

CJK is the hard part. The scripts try macOS / Linux / Windows system font
paths in this order:

| Alias | Looks for |
|---|---|
| `hei` / `STHeiti` | STHeiti, SimHei, NotoSansCJK, wqy |
| `song` / `SimSun` | SimSun, NSimSun, STSong, SourceHanSerif, NotoSerifCJK |
| `kai` / `KaiTi` | STKaiti, KaiTi |
| `fang` / `PingFang` | PingFang.ttc, PingFangSC |
| `yahei` / `MS YaHei` | Microsoft_YaHei |
| `sourcehan` | SourceHanSans / -Serif (.otf.ttc) |
| `noto` | NotoSans/Serif CJK |
| `helvetica` / Latin | Helvetica.ttf |

To see what's available:
```bash
python info.py any.pdf --cjk
```

If a font is missing, install one (e.g. `brew install --cask font-source-han-sans`)
or pass an explicit absolute path to `--font`.

---

## Quick recipe: filling a 顾问协议 from a JSON record

Concrete end-to-end for the typical HR scenario:

```bash
SKILL=~/.pi/agent/skills/pdf-toolkit/scripts
PDF="/Users/.../顾问协议_template.pdf"

# Step 1: see the fields
python $SKILL/forms.py inspect "$PDF" | python -m json.tool | head -40

# Step 2: write fill.json
cat > fill.json <<'EOF'
{
  "values": {
    "乙方身份证号": "440101199001011234",
    "乙方住所":     "深圳市南山区...",
    "乙方联系电话": "13800138000",
    "乙方电子邮箱": "jam@example.com"
  },
  "options": {"font": "SourceHan", "fontsize": 11}
}
EOF

# Step 3: produce the filled PDF + verify visually
python $SKILL/forms.py fill "$PDF" filled.pdf --config fill.json
```

---

## Demonstrating on a real Chinese contract

For the user's 陈政羽外部（兼职）顾问协议.pdf (typst-generated, 11 pages, 22
AcroForm text fields):

```bash
SKILL=~/.pi/agent/skills/pdf-toolkit/scripts
PDF="/path/to/陈政羽外部（兼职）顾问协议.pdf"

# 1) inspect — there are 4 Text fields on page 1
python $SKILL/info.py "$PDF" --pages 1 --cjk
# → name=乙方身份证号 ... font=Helv size=10.5

# 2) fill — overlay auto-bakes only the CJK-containing value
python $SKILL/forms.py fill "$PDF" out.pdf --config fill.json

# 3) modify — change color, fontsize, bg_color, border of specific fields
python $SKILL/forms.py modify out.pdf styled.pdf --config modify.json

# 4) verify visually — pdftocairo (NOT PyMuPDF screenshot — see below)
pdftocairo -png -f 1 -l 1 -r 100 out.pdf preview
```

**Important verification caveat:** the `parse-document` skill's
`document_screenshot` uses PyMuPDF rendering, which does not regenerate
broken AcroForm appearance streams (a Typst-specific quirk). Use poppler's
`pdftocairo` (`brew install poppler`) for visual verification — it's the
ground truth. Chinese glyphs that look blank via `document_screenshot`
will be correct in the actual file.

## What this skill does NOT do

- **OCR** of scanned PDFs → use `pi_ocr` or the `parse-document` skill
- **Reading/extracting data** from a filled PDF → `parse-document`
- **Editing scanned text** (image PDFs) → OCR first to overlay
- **Real PKCS#7 digital signatures** with certificates → `pyhanko` (not bundled;
  install on demand)
- **Interactive fill in a UI** → open the produced PDF in Preview / Adobe /
  any browser

If the user wants a one-stop pipeline ("read this scanned PDF, fill the
template, save") chain this skill with `pi_ocr` / `parse-document`.

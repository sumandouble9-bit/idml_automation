# 📘 IDML Automation — Book Production Pipeline

An end-to-end automation pipeline that takes raw Adobe InDesign manuscripts (`.idml`) and matching EPUB packages, and produces press-ready, typographically normalized book IDMLs and print PDFs. Dual-language (🇬🇧 English / 🇪🇸 Spanish), fully headless (COM-driven InDesign), and designed for batch runs over an entire catalog.

---

## 📑 Table of Contents

1. [🚀 What this pipeline does](#-what-this-pipeline-does)
2. [🧭 High-level flow](#-high-level-flow)
3. [🗂️ Repository layout](#️-repository-layout)
4. [🧩 Module-by-module summary](#-module-by-module-summary)
5. [🛠️ Prerequisites](#️-prerequisites)
6. [📦 Installation](#-installation)
7. [▶️ Running the pipeline](#️-running-the-pipeline)
8. [🧰 Common troubleshooting](#-common-troubleshooting)

---

## 🚀 What this pipeline does

Given one book's input (an IDML manuscript + its EPUB), the pipeline will:

- 🎯 Normalize trim size, margins, bleeds, and master spreads
- ✍️ Rebuild typography (fonts, leading, hyphenation, justification, chapter styles)
- 📖 Rebuild Title / Copyright / TOC / Author pages from EPUB metadata
- 🖼️ Extract EPUB images + captions and inject them inline at the right paragraph
- 📐 Resize and re-center images so no graphic clips its frame
- 📏 Resolve overset text by adding pages and shrinking oversize anchored graphics
- 🧮 Fit tables to the margin box, remove borders, balance column widths, split long tables
- 📄 Flow chapters so each one starts on a fresh page
- ⬇️ Push the last line of a column down to the baseline (no short last pages)
- 🖨️ Export the final book as a two-page spread print PDF and a clean IDML

All of it runs in one command on one book, or batched over every book in `idml_input_files/`.

---

## 🧭 High-level flow

```
  idml_input_files/*.idml  +  epub_input_files/*.epub
            │
            ▼
   ┌─────────────────────────────────────────────┐
   │  STEP 1 — Formatting (per language, EN/ES)  │  🎨
   │   • Title / Copyright / TOC / Author pages   │
   │   • Typography rebuild, heading splitting    │
   │   • Font embedding, EPUB enrichment          │
   └─────────────────────────────────────────────┘
            │
            ▼
   ┌─────────────────────────────────────────────┐
   │  STEP 2 — Normalization                     │  📐
   │   • 5.5 × 8.5 in trim, margins, bleeds       │
   │   • Master spreads, page geometry            │
   └─────────────────────────────────────────────┘
            │
            ▼
   ┌─────────────────────────────────────────────┐
   │  STEP 3 — Injection (InDesign COM)          │  🖼️
   │   • Extract EPUB images + captions           │
   │   • Inject into placeholders                 │
   │   • Overset reflow (add pages, shrink imgs)  │
   │   • Table fit + center sweep + borders       │
   │   • Logo relink + front-matter flow          │
   └─────────────────────────────────────────────┘
            │
            ▼
   ┌─────────────────────────────────────────────┐
   │  STEP 3d / 3e / 3f — Post-passes             │  🧹
   │   3d  Chapter double-break fix              │
   │   3e  Table column balance                   │
   │   3f  Paragraph spacing normalization        │
   └─────────────────────────────────────────────┘
            │
            ▼
   ┌─────────────────────────────────────────────┐
   │  STEP 4 — Export                             │  🖨️
   │   • Final IDML written                       │
   │   • Print PDF exported (two-page spread)     │
   └─────────────────────────────────────────────┘
            │
            ▼
   final_output_files/idml_files/*.idml
   Output/pdf_files/*.pdf
```

---

## 🗂️ Repository layout

```
idml_automation/
├── run_book_pipeline.py          # 🎬 main CLI entry point
├── requirements.txt              # 📦 pinned Python deps
├── book_workflow/                # ⚙️ orchestration (stages, discovery, config)
├── injection/                    # 🖼️ EPUB → IDML image & caption injection
├── table/                        # 📐 table fit / overset / column balance
├── resize_images/                # 🔍 image resize & cascade centering
├── bottom_align_text/            # ⬇️ vertical bottom-align pass
├── Scripts/                      # 🖨️ PDF export
├── test_cases/                   # 🧪 regression scripts
├── idml_input_files/             # 📥 source IDMLs
├── epub_input_files/             # 📥 matching EPUB packages
├── Output/
│   ├── Formatted/                  # step 1 output
│   ├── page_resize_output/         # step 2 output
│   └── pdf_files/                  # step 4 PDFs
└── final_output_files/idml_files/  # 📤 final IDML deliverables
```

---

## 🧩 Module-by-module summary

### ⚙️ `book_workflow/` — orchestration core

The brain of the pipeline. Each run instantiates **`BookWorkflow`**, which discovers books and dispatches them through the stages.

| File | Role |
|---|---|
| `workflow.py` | `BookWorkflow` class — wires all stages, parses CLI args, runs selected step |
| `book_discovery.py` | Scans `idml_input_files/` for IDMLs; applies `--book`, `--lang`, `--limit` filters |
| `paths.py` | `WorkflowPaths` — single source of truth for every input/output directory |
| `models/book.py` | `Book` dataclass (ISBN, language, source IDML, source EPUB) |
| `config/languages.py` | Per-language style maps (English vs Spanish) |

### 🎨 `book_workflow/formatting/` — page design & typography

Each sub-package rebuilds one kind of page from EPUB metadata and typographic rules. Runs during **Step 1**.

| Sub-package | Role |
|---|---|
| `title/` | 📖 Title page layout (title, subtitle, author, publisher logo) |
| `copyright/` | 📜 Copyright page (ISBN, year, imprint — dynamic from Google Sheet metadata) |
| `table_of_contents/` | 📑 TOC generation with dot-leaders and clean numbering |
| `author/` | 👤 About-the-author page |
| `document_setup/` | 📐 Master spreads, trim, margins, bleeds |
| `typography/` | ✍️ Font embedding, leading, justification, chapter headings, EPUB enrichment |

### 🧱 `book_workflow/core/` — reusable formatting primitives

Called from the formatting and injection stages. Each file is a focused transform.

| File | What it does |
|---|---|
| `isbn_manager.py` | 🏷️ Loads ISBN metadata from Google Sheet, caches to `isbn_metadata_cache.json` |
| `font_manager.py` | 🔤 Verifies `Fonts.xml` and embeds fonts |
| `chapter_heading_format.py` | 📝 Splits "CHAPTER I The Journey" into numeral + title on two lines |
| `chapter_break_format.py` | 📄 Ensures each chapter starts on a fresh page; fixes trailing/spacer breaks |
| `chapter_spacing_*.py` | 📏 Top-of-chapter spacing resequencing (14.5pt gap, keep-with-next) |
| `chapter_top_spacing.py` | ⬆️ Rigid chapter top alignment post-injection |
| `frontmatter_flow.py` | 📑 Keeps front-matter stories (Title, Copyright) from leaking into body flow |
| `epub_class_format.py` | 🏷️ Maps EPUB CSS classes → IDML character/paragraph styles |
| `epub_style_enricher.py` | 🎀 Re-applies bold/italic/underline runs from EPUB to IDML |
| `epub_script_positions.py` | ⁰ Cleans false superscripts (EPUB footnote markers that should NOT be sup) |
| `collapse_soft_breaks.py` | ↵ Collapses `U+2028` line-separators into normal breaks |
| `heading_classifier.py` | 🧠 Classifies ambiguous headings using text + style evidence |
| `justify_stretch_format.py` | ↔️ Prevents extreme word-spacing on short last lines |
| `paragraph_spacing_normalizer.py` | 📐 Unifies paragraph space-before/after across styles |
| `split_compound_verse_prose.py` | 📜 Separates verse stanzas that collapsed into one PSR |
| `inline_image_leading.py` | 🖼️ Sets inline-leading on anchored body images |
| `toc_synchronizer.py` | 🔗 Rewires TOC entries to the live InDesign layout |
| `caption_dedup.py` | 🧹 Removes duplicate captions left above/below images |
| `center_from_epub.py` | 🎯 Centers paragraphs that are centered in the EPUB |
| `idml_utils.py` | 🛠️ IDML zip pack/unpack + XML helpers |
| `indesign_app.py` | 🔌 COM Dispatch wrapper |

### 🧱 `book_workflow/stages/` — pipeline stages

Each stage is a thin class with a `run(books, force=...)` method.

| Stage | File | Purpose |
|---|---|---|
| **1. Formatting** | `formatting_stage.py` | 🎨 Runs typography + page formatters, writes `Output/Formatted/` |
| **2. Normalization** | `normalization_stage.py` | 📐 Sets trim 5.5×8.5 in, margins, bleeds, masters; writes `Output/page_resize_output/` |
| **va. VerticalAlign** | `vertical_align_stage.py` | ⬇️ Vertical-bottom-align pass (optional, run separately) |
| **3. Injection** | `injection_stage.py` | 🖼️ Drives InDesign over COM for EPUB injection + table/image fit |
| **4. Export** | `export_stage.py` | 🖨️ Quality audit + PDF export + final IDML |

### 🖼️ `injection/` — EPUB → IDML image & caption injection

The heaviest stage. Runs **inside InDesign** via `win32com` and ExtendScript (`DoScript`).

| File | Role |
|---|---|
| `inject_with_epub_captions.py` | 🧭 Main injector: opens IDML in InDesign, places images, runs reflow, calls table-fit |
| `injection_scripts.py` | 📜 ExtendScript blocks: `resolve_overset_js`, `center_all_js`, `page_count_js`, vertical justification, etc. |
| `injection_helpers.py` | 🔌 `connect_indesign`, `restart_indesign`, RPC-error detection, image preparation |
| `epub_tools.py` | 📦 Extracts images & captions from the EPUB zip |
| `epub_caption_apply.py` | 📝 Places EPUB captions below their images |
| `image_layout_format.py` | 🎯 Re-fits and centers image frames inside margins |
| `logo_inject.py` | 🏷️ Replaces the publisher logo frame on the title page |
| `resolve_overset.py` | ⚠️ Programmatic overset detection and reporting |
| `audit_*.py` | 🔍 Standalone audit scripts (EPUB / InDesign / text) |

### 📐 `table/` — table fit / balance / cell overset

| File | Role |
|---|---|
| `table_fit_format.py` | 🧮 `fix_tables_in_doc(app)` — runs 13 sub-passes: enforce font size, collapse empty rows, compact cells, break poem tables, align autogrow cells, left-align cells, make rows breakable, fit image-tables to margin, center narrow tables, remove borders, vertical fix, flow overset tail |
| `table_scripts.py` | 📜 ExtendScript bodies for each table sub-pass |
| `table_scripts_extra.py` | 📜 Additional helper scripts (border sweep, cell centering) |
| `table_column_balancer.py` | ⚖️ Content-aware column width balancing (step 3e) |

### 🔍 `resize_images/` — image placement & scaling

| File | Role |
|---|---|
| `sequential_cascade_resize.py` | 📉 Scales down oversize images and re-centers them in the frame (`fit(CENTER_CONTENT)` after every scale) |
| `measure_gap_shrink.py` | 📏 Measures vertical gaps so cascading shrink can target the worst offenders first |
| `measure_image_frame.py` | 📐 Reads image frame geometry for diagnostics |

### ⬇️ `bottom_align_text/` — vertical bottom alignment

| File | Role |
|---|---|
| `vertical_bottom_align.py` | ⬇️ Pulls the last paragraph of a column to the baseline so pages don't end short. Runs via `--step va`. |

### 🖨️ `Scripts/` — PDF export

| File | Role |
|---|---|
| `convert_to_pdf.py` | 📄 Opens the final IDML in InDesign and exports a two-page-spread print PDF to `Output/pdf_files/` |

### 🧪 `test_cases/` — regression & spot-check scripts

Standalone, one-off scripts to validate specific sub-behaviors (EPUB class mapping, paragraph style enforcement, etc.). Not part of the normal run.

---

## 🛠️ Prerequisites

- 🪟 **Windows 10 / 11** — the pipeline drives InDesign via COM
- 🎨 **Adobe InDesign 2024 or newer** — must be installed and launchable
- 🐍 **Python 3.10 (64-bit)**
- 📝 **Fonts** — Palatino Linotype, Gill Sans MT, and any book-specific fonts in `Fonts/`
- 🔑 **Google Sheet access** for ISBN metadata (optional — falls back to `isbn_metadata_cache.json`)

---

## 📦 Installation

```bash
git clone https://github.com/sumandouble9-bit/idml_automation.git
cd idml_automation
```

```bash
python -m venv venv
```

```bash
venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

Pinned packages in `requirements.txt`:

- 📊 `numpy==2.5.4`
- 📊 `pandas==3.1.0`
- 🖼️ `pillow==12.3.0`
- 📄 `pymupdf==1.28.2` (PDF verification)
- 🕒 `python-dateutil==3.0.0`
- 🪟 `pywin32==312` (InDesign COM bridge)
- 🔢 `six==1.17.0`
- 🕒 `tzdata==2026.6`

Drop source files in place:

- 📥 IDMLs → `idml_input_files/`
- 📥 EPUBs → `epub_input_files/` (filename must contain the book ID / ISBN)
- 🏷️ Logo → `input_files/logo/LEAF-BOUND-trimmed.png` (or set `LOGO_PATH` env var)

---

## ▶️ Running the pipeline

### 🎬 Full pipeline (all stages) on every book

```bash
python run_book_pipeline.py
```

### 🎯 One book, full pipeline

```bash
python run_book_pipeline.py --book 18722
```

### 🧩 A specific step only

```bash
python run_book_pipeline.py --book 18722 --step 3
```

Steps (`--step`):

| Value | Stage |
|---|---|
| `all` (default) | 🔄 1 → 2 → 3 → 3d → 3e → 3f → 4 |
| `va` | ⬇️ Vertical-bottom-align pass (run separately) |
| `1` | 🎨 Typography + page formatting |
| `2` | 📐 Document setup / trim normalization |
| `3` | 🖼️ Image + caption injection (opens InDesign) |
| `3d` | 📄 Chapter double-break fix |
| `3e` | ⚖️ Table column balancing |
| `3f` | 📐 Paragraph spacing normalization |
| `4` | 🖨️ Export final IDML + PDF |

### 🇬🇧 🇪🇸 Filter by language

```bash
python run_book_pipeline.py --lang en
```

```bash
python run_book_pipeline.py --lang es
```

### 🔁 Force re-process

```bash
python run_book_pipeline.py --book 18722 --force
```

### 🔢 Limit batch size (useful for smoke tests)

```bash
python run_book_pipeline.py --limit 2
```

### ⬇️ Vertical bottom-align before the main pipeline

```bash
python vertical_bottom_align.py
```

```bash
python run_book_pipeline.py
```

---

## 🧰 Common troubleshooting

### 🪟 Pipeline hangs at `connect_indesign()`
InDesign has a modal dialog open (Document Recovery, "previous session closed unexpectedly", or an unsaved document). Open InDesign manually, dismiss the dialog, close the document, then re-run. If needed, kill `InDesign.exe` in Task Manager and delete `%AppData%\Adobe\InDesign\…\Recovery\`.

### ⚠️ `RPC server is unavailable` after a long reflow
InDesign crashed during a heavy pass (usually on pathologically dense books — many tables + large unresolvable overset). The pipeline auto-retries up to 3× (`restart_indesign`). If every retry crashes, the input book has more content than can fit the trim size; fix the EPUB/IDML source.

### 🏷️ Chapter heading appears mid-page instead of a new page
See `chapter_break_format.py`. Each chapter heading should carry `StartParagraph="NextPage"`. Spacer paragraphs with `StartParagraph="NextPage"` + `KeepWithNext` on the following heading can collapse — the fix puts the break on the heading itself.

### 🖼️ Image invisible on the page
See `resize_images/sequential_cascade_resize.py`. After a scale, call `fit(CENTER_CONTENT)` to re-center the content inside the frame — otherwise the image sits offset and the frame crops it.

### 📄 Table cells show red "+" (cell overset)
Open the IDML in InDesign, click "Clear Overrides" on the table paragraph, save. In the pipeline, `_fix_tables_and_breakable` and `_align_autogrow_cells` in `table_fit_format.py` handle most cases automatically.

### 🧪 Verify a PDF without rerunning the pipeline

```bash
python check_captions_all.py
```

```bash
python measure_page_gaps.py
```

---

🤖 Built & maintained by Double9 Publishing · generated with assistance from Claude Code

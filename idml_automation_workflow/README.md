# Automated EPUB-to-IDML Formatting & Image-Injection Pipeline

End-to-end batch pipeline that takes raw IDML books and produces print-ready,
reference-matched IDMLs and PDFs. It formats each book to a reference IDML layout
("same to same") while preserving book-specific content (titles, authors, ISBNs,
chapters, text), injects the book's EPUB images with captions, fills short text
pages, and audits/exports the result.

Everything runs from **one command**: `python run_pipeline.py`.

---

## Workflow (what runs, in order)

| Step | Stage | Script | Reads | Writes |
|:---:|:---|:---|:---|:---|
| 1 | **Normalize** document setup (trim / margins / bleed) | `normalize_docs.py` | `input_files/` | `page_resize_output/` |
| 2 | **Format** to reference layout (typography, pages, headings, styles) | `Scripts/pipeline.py` | `page_resize_output/` | `formate_document/` |
| 2b | Typography **post-process** each formatted file (uniform Palatino 9.65 pt, clean footers) | `Scripts/core/typography_postprocessor.py` | `formate_document/` | *(in place)* |
| 3 | **Inject** EPUB images + captions | `image_inject/inject_with_epub_captions.py` | `formate_document/` + `epub_input_files/` | `final_output_files/idml_files/` |
| 3a | Typography **post-process** each injected file (restore `body_text`, fix footers) | `Scripts/core/typography_postprocessor.py` | `final_output_files/idml_files/` | *(in place)* |
| 3b | **Fill text bottom-gaps** (reflow body text up at original spacing; TOC untouched) | `fix_text_bottom_gap.py` | `final_output_files/idml_files/` | *(overwrites in place)* |
| 4 | **Audit + export PDFs** (overset / margin / missing-text checks) | `image_inject/audit_epub.py` | `final_output_files/idml_files/` | `final_output_files/pdf_files/` (+ `rejected_files/`) |

Formatting (step 2) runs entirely on the IDML XML. Steps 3, 3b, and 4 drive
Adobe InDesign via COM, so **InDesign must be installed and running** for those.

---

## How to run

From the `idml_automation_workflow/` folder:

```powershell
# Process every book found in input_files/
python run_pipeline.py

# Process a single book (by file basename, with or without .idml)
python run_pipeline.py 9789361422768
```

### Standalone utilities (optional, run on their own)

```powershell
# Measure the bottom gap on every page + image sizes/placement, per book
# -> final_output_files/page_gaps_report.txt
python measure_page_gaps.py
python measure_page_gaps.py 9789361422768      # one book

# Reflow-fill short text pages only (same step the pipeline runs as 3b)
# -> overwrites final_output_files/idml_files/, logs in final_output_files/
python fix_text_bottom_gap.py
```

---

## Input / Output folders

Inputs live beside the workflow folder (under `D:\IDML-Creation\`); all outputs are
created inside `idml_automation_workflow/`.

| Folder | Role |
|:---|:---|
| `../input_files/` | **Input** — raw IDML books to process (step 1 input) |
| `../epub_input_files/` | **Input** — matching EPUBs supplying images + captions (step 3) |
| `Reference/` | **Input** — reference layout IDML (the `…MIS…` / Les Misérables template is auto-selected) |
| `Fonts/` | **Input** — font files bundled into each document |
| `page_resize_output/` | Output of step 1 (normalized IDMLs) |
| `formate_document/` | Output of step 2 (reference-formatted IDMLs) |
| `final_output_files/idml_files/` | Output of step 3 / 3b (injected + gap-filled IDMLs) |
| `final_output_files/pdf_files/` | Output of step 4 (PDFs of books that passed audit) |
| `final_output_files/rejected_files/{idml_files,pdf_files}/` | Books that failed audit, with a `*.audit.txt` reason file |
| `final_output_files/*_report.txt` | Audit / gap reports (`audit_log.txt`, `books_summary_report.txt`, `page_gaps_report.txt`) |

Folder names are matched by book basename throughout, so `input_files/9789361422768.idml`,
`epub_input_files/9789361422768.epub`, and the outputs all line up.

---

## Directory architecture

```text
idml_automation_workflow/
├── run_pipeline.py                 # SINGLE entry point (steps 1 -> 4)
├── fix_text_bottom_gap.py          # step 3b: reflow-fill short text pages
├── measure_page_gaps.py            # standalone: per-page gap + image report
├── Reference/                      # reference layout IDML(s)
├── Fonts/                          # bundled font files
├── page_resize_output/             # step 1 output
├── formate_document/               # step 2 output
├── final_output_files/                # step 3/3b/4 output (idml_files, pdf_files, rejected_files, reports)
├── image_inject/                   # InDesign-driven injection + audit scripts
│   ├── inject_with_epub_captions.py
│   ├── epub_caption_apply.py / epub_tools.py / logo_inject.py
│   ├── fix_image_layout.py / fix_table_fit.py
│   └── audit_epub.py
└── Scripts/                        # formatting stage (pure-XML)
    ├── pipeline.py                 # formatting entry point (called by step 2)
    ├── core/
    │   ├── idml_utils.py           # shared XML / ZIP / font / story helpers
    │   ├── font_manager.py         # font resolution & bundling
    │   └── typography_postprocessor.py  # uniform typography + footer cleanup
    ├── pages/
    │   ├── normalize_document_setup.py  # body-page normalization (margins/geometry/frames)
    │   ├── document_setup.py       # Task 1: trim, bleed, margins (frontmatter)
    │   ├── title_page.py           # Tasks 2, 9, 10
    │   ├── copyright_page.py       # Task 3
    │   ├── toc_page.py             # Task 4
    │   ├── author_page.py          # Task 5
    │   ├── typography_and_styles.py# Tasks 6-8, 11-19
    │   └── run_all_3_batch.py      # standalone batch wrapper for the formatting stage
    └── Tests/
        └── test_idml_pipeline.py   # verification suite (RUN_TESTS.bat)
```

---

## Formatting task matrix (step 2)

The formatting stage implements the following, matched to the reference layout:

| Task # | Description | Module |
|:---:|:---|:---|
| **1** | Book size, page margins, bleed; page/frame geometry | `document_setup.py` + `normalize_document_setup.py` |
| **2** | Title page formatting & positioning | `title_page.py` |
| **3** | Copyright page (dynamic ISBN/year, Double 9 Books) | `copyright_page.py` |
| **4** | TOC page (dot leaders, clean numbering, EPUB-junk removal) | `toc_page.py` |
| **5** | About the Author page | `author_page.py` |
| **6** | Body text font & size (Palatino Linotype 9.65 pt) | `typography_and_styles.py` |
| **7-8** | Restore bold / italic where applied | `typography_and_styles.py` |
| **9-10** | Title-page sizes & separate "by" credit | `title_page.py` |
| **11** | Split run-on chapter number + title lines | `typography_and_styles.py` |
| **12** | H1 / H2 / H3 heading styles & positions | `typography_and_styles.py` |
| **13-14** | Restore superscript / subscript | `typography_and_styles.py` |
| **15-17** | Merge duplicate bold/italic/underline/all-caps styles & verify | `typography_and_styles.py` |
| **18-19** | Index & footnote formatting / spacing | `typography_and_styles.py` |

---

## Tests

```powershell
python .\Scripts\Tests\test_idml_pipeline.py    # or RUN_TESTS.bat
```


---

## Spanish Publishing Pipeline (`Scripts/spanish/`)

A dedicated 4-stage pipeline tuned specifically for Spanish titles:
1. **Title Page:** Preserves the Spanish author credit format (`Por` rendered in *italic* font).
2. **Copyright Page:** Formats Spanish legal disclosures with year and double-dash ISBN formatting.
3. **Table of Contents (TOC):** Formats *Contenido* headers, dots leader tab stops, right-aligned page numbers, and page-break isolation.
4. **Author Page:** Detects *Sobre la autoría*, positions content cleanly, and ensures an empty separator page before body chapters begin.
5. **Headings & Body Typography:** Enforces 16pt Gill Sans MT headings with 1-space sinkage and Palatino Linotype 9.65pt body text.

### How to Run Spanish Pipeline

```powershell
# From idml_automation_workflow/:
# 1-Click Batch:
RUN_SPANISH_PIPELINE.bat

# Or via Python (all books):
python run_spanish_pipeline.py

# Single book:
python run_spanish_pipeline.py 9788166131264
```

---

## Step-by-Step Execution (For Any Book)

Each stage can also be executed step-by-step with automatic language detection:

| Step | Purpose | Command | 1-Click Batch |
|:---:|:---|:---|:---|
| **Step 1** | **Typography & Layout Formatting** | `python step1_format.py` | `RUN_STEP1_FORMAT.bat` |
| **Step 2** | **Document Setup Normalization (5.5x8.5 in)** | `python step2_normalize.py` | `RUN_STEP2_NORMALIZE.bat` |
| **Step 3** | **EPUB Image & Caption Injection** | `python step3_inject_images.py` | `RUN_STEP3_INJECT.bat` |
| **Step 4** | **High-Quality Print PDF Export** | `python step4_export_pdf.py` | `RUN_STEP4_PDF.bat` |


---

## Dual-Language Support & Routing (English & Spanish)

The pipeline seamlessly processes both **English** and **Spanish** books side-by-side using unified input folders:
- **`input_files/`**: Place all raw `.idml` manuscripts (both English and Spanish).
- **`epub_input_files/`**: Place all corresponding `.epub` asset files (both English and Spanish).

### 1. Automatic Language Detection
When running `step1_format.py`, the engine automatically identifies each book's language without requiring manual flags:
- **Filename Heuristics:** Checks for `_es`, `spanish`, `_en`, `english` in the file name.
- **Content Story Sampling:** Analyzes the first 15 XML story files for native language markers:
  - *Spanish Markers:* `capítulo`, `contenido`, `sobre la autoría`, `prólogo`, `parte primera`, `derechos de autor`, `por `
  - *English Markers:* `chapter`, `contents`, `about the author`, `preface`, `part one`, `copyright`, `published by`, `by `
- Books with predominantly Spanish markers are routed to `Scripts/spanish/pipeline_es.py`.
- Books with predominantly English markers are routed to `Scripts/pipeline.py`.

### 2. Typographical & Structural Differences Handled

| Component | Spanish Rules (`pipeline_es.py`) | English Rules (`pipeline.py`) |
|:---|:---|:---|
| **Title Page** | Author credit formatted with *italic* *"Por"*, clean subtitle sinkage | Author credit formatted with standard roman *"by"* credit |
| **Copyright Page** | Spanish legal text, translated publishing rights, formatted ISBN | Double 9 Books English publishing declaration & copyright notices |
| **Table of Contents** | Header styled as *"Contenido"*, right-aligned page numbers with dot leaders (`. . . .`), page break isolation | Header styled as *"Contents"*, dot leaders, EPUB markup cleanup |
| **Author Page** | Detects *"Sobre la autoría"*, guarantees blank separator page before body chapters | Detects *"About the Author"*, positions content according to reference |
| **Table Layout** | Special table-fit overset protection and cell height balancing | Cell width balancing and column autofit |
| **Body Typography** | Palatino Linotype 9.65pt, Gill Sans MT 16pt sinkage headings | Palatino Linotype 9.65pt, Gill Sans MT 16pt headings, run-on chapter splitting |

### 3. Manual Language Overrides (Flags)
You can optionally bypass automatic detection and force a specific language via CLI flags:

```powershell
# Force Spanish processing on all books:
python step1_format.py --lang es

# Force English processing on all books:
python step1_format.py --lang en

# Force specific language on a single book:
python step1_format.py 9788166131264 --lang es
python step1_format.py 9789361422768 --lang en
```

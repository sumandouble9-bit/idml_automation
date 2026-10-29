# IDML Automation Workflow Engine (`book_workflow`)

A modular, Object-Oriented automated publishing system for processing dual-language (English and Spanish) IDML manuscripts and EPUB packages into press-compliant print PDFs and standardized IDML books.

---

## Table of Contents
1. [Architecture & Design Principles](#architecture--design-principles)
   - [What is "Workflow" (Pipeline)?](#what-is-workflow-pipeline)
   - [Why `core` was Consolidated (Eliminating Duplication)](#why-core-was-consolidated-eliminating-duplication)
   - [OOP Model & Class Hierarchy](#oop-model--class-hierarchy)
2. [Workflow Stages](#workflow-stages)
3. [Recent Fixes & Typography Hardening](#recent-fixes--typography-hardening)
4. [CLI Usage Guide](#cli-usage-guide)
5. [Directory Structure](#directory-structure)
6. [Automated Quality Verification](#automated-quality-verification)

---

## Architecture & Design Principles

### What is "Workflow" (Pipeline)?
In book production, a **workflow** (or pipeline) is an automated sequence of specialized operations that transforms raw manuscript files into print-ready books. Rather than manually clicking through dozens of formatting dialogs in Adobe InDesign, the `book_workflow` engine coordinates the entire lifecycle across four distinct, auditable stages:
1. **Stage 1 (Formatting):** Ingests raw IDML and reference layouts, standardizing typography, frontmatter pages, and headings.
2. **Stage 2 (Normalization):** Standardizes page trim geometry (5.5 × 8.5 in), facing pages, margins (36/54 pt), and print bleeds (3 mm).
3. **Stage 3 (Asset Injection):** Ingests companion EPUB archives, extracting high-resolution images, binding captions, building side-by-side tables, and adjusting bottom gaps and chapter top margins.
4. **Stage 4 (Quality Audit & Export):** Runs automated integrity checks (missing text, overset frames, word spacing), drives InDesign COM to export print PDFs with two-page facing reader spreads, and synchronizes the IDML Table of Contents to actual PDF page numbers.

The previous internal name `pipeline_engine` was renamed to **`book_workflow`** to clearly communicate this domain model.

---

### Why `core` was Consolidated (Eliminating Duplication)
Previously, the repository contained two duplicate `core` directories:
- `Scripts/core/` (contained 18 typography, XML, font, and TOC synchronizer utilities).
- `pipeline_engine/core/` (contained only `indesign_app.py`).

This created confusing import paths and ambiguity over where publishing utilities resided. 

**All 19 core publishing modules have been merged into a single package:**
```text
idml_automation_workflow/book_workflow/core/
```
The duplicate `Scripts/core/` and `pipeline_engine/core/` folders have been removed.

---

### OOP Model & Class Hierarchy

The system is structured around clean Object-Oriented design patterns:

- **`Book` (`book_workflow.models.book.Book`)**: Represents a book entity, encapsulating its ISBN, detected language, asset paths (raw IDML, EPUB, intermediate IDMLs, final output IDML, and print PDF), and stage completion states.
- **`WorkflowPaths` (`book_workflow.paths.WorkflowPaths`)**: Encapsulates filesystem directory resolution and automatically mounts subpackages onto `sys.path`.
- **`WorkflowStage` (`book_workflow.stages.base_stage.WorkflowStage`)**: Abstract base class defining the contract for all processing stages:
  - `name`: Human-readable stage identifier.
  - `execute(book: Book) -> bool`: Executes the stage logic for the given book.
  - `can_skip(book: Book) -> bool`: Determines if cached intermediate outputs can be safely reused.
- **Stage Implementations:**
  - `DocumentFormattingStage`: Pure-XML IDML formatting.
  - `DocumentNormalizationStage`: Document geometry and spread normalization.
  - `AssetInjectionStage`: Image extraction, caption placement, and bottom gap filling.
  - `QualityAuditAndExportStage`: Preflight integrity gates and InDesign COM export.
- **`BookWorkflow` (`book_workflow.workflow.BookWorkflow`)**: Master orchestrator class that manages the stage registry, processes individual or batch book collections, and manages error recovery.
- **`InDesignApp` (`book_workflow.core.indesign_app.InDesignApp`)**: Context manager wrapping Adobe InDesign Windows COM automation (`__enter__` and `__exit__`), ensuring that document handles and application instances are cleanly closed without leaving orphan `InDesign.exe` processes.
- **Page Hierarchy (`book_workflow.formatting`)**: `BasePage` abstract class extended by `TitlePage`, `CopyrightPage`, `AuthorPage`, and `TableOfContentsPage`, with language-specific implementations (`TitlePageEN`, `TitlePageES`, etc.) using polymorphism.

---

## Workflow Stages

| Step | Stage Name | Class / Module | Purpose |
|:---:|:---|:---|:---|
| **1** | **Formatting** | `DocumentFormattingStage` | XML-level typography, Palatino 9.65pt body, Gill Sans MT 16pt headings, frontmatter layout. |
| **2** | **Normalization** | `DocumentNormalizationStage` | Trim size 5.5 × 8.5 in, facing pages, 36pt / 54pt margins, 3mm bleeds. |
| **3** | **Asset Injection** | `AssetInjectionStage` | EPUB figure extraction, caption binding, 2-column tables, LeafBound imprint logo. |
| **3b** | **Gap Filling** | `fix_text_bottom_gap.py` | Eliminates vertical white space gaps by micro-reflowing body lines to bottom margin. |
| **3c** | **Chapter Spacing** | `chapter_top_spacing.py` | Enforces rigid 14.5 pt top gap (`y0 = 86.04 pt`) and Recto (Page 7) chapter start. |
| **4** | **Audit & Export** | `QualityAuditAndExportStage` | Missing paragraph / overset / word spacing audit, InDesign COM PDF export (`maxB=558pt`), TOC page sync. |

---

## Recent Fixes & Typography Hardening

### 1. Word Spacing / Justification Fix on Signatures & Soft Breaks
- **Issue:** Letter signatures (e.g., `Signed:\u2028BLACHEVELLE...`) stretched across the entire width of the page with extreme gaps between letters and words.
- **Fix:** In `test_cases/fix_paragraph_styles.py`, `book_workflow/core/typography_postprocessor.py`, and `book_workflow/formatting/typography/typography_en.py`, right-aligned and centered paragraphs are strictly preserved from being converted to justified `body_text`. Paragraphs containing soft line breaks (`\u2028` or `\n`) are protected from `LeftJustified` or `FullyJustified` styles.

### 2. Heading Splitting on Chapters & Books with Years (e.g., `1817`)
- **Issue:** In *Les Misérables* (`9789370421240`), `BOOK THIRD—IN THE YEAR 1817` and `CHAPTER I—THE YEAR 1817` failed to split into two centered lines because `1817` was misidentified as a Table of Contents page number.
- **Fix:** In `book_workflow/core/chapter_heading_fix.py`, replaced the greedy `\s\d{1,4}\s*$` regex with strict leader and tab detection (`(\.\s*){2,}\s*\d+` or `\t\s*\d+\s*$`). Headings ending in years now correctly split onto two lines separated by `\u2028`.

---

## CLI Usage Guide

The single, unified command to run the complete publishing pipeline is **`run_book_pipeline.py`**:

```powershell
# Run a specific book end-to-end by ISBN or filename:
python run_book_pipeline.py 9789370421240

# Run all books through the complete workflow:
python run_book_pipeline.py

# Run a single stage only:
python run_book_pipeline.py 9789370421240 --step 1   # Stage 1: Formatting
python run_book_pipeline.py 9789370421240 --step 2   # Stage 2: Normalization
python run_book_pipeline.py 9789370421240 --step 3   # Stage 3: Asset Injection
python run_book_pipeline.py 9789370421240 --step 3b  # Stage 3b: Bottom Gap Reflow
python run_book_pipeline.py 9789370421240 --step 4   # Stage 4: PDF Export & Integrity Audit

# Filter by language:
python run_book_pipeline.py --lang es
python run_book_pipeline.py --lang en

# Force re-execution of completed stages:
python run_book_pipeline.py 9789370421240 --force
```

---

## Directory Structure

```text
idml_automation_workflow/
├── run_book_pipeline.py                 # Single Primary CLI runner (Book Production Workflow)
├── fix_text_bottom_gap.py               # Stage 3b gap reflow
├── measure_page_gaps.py                 # Page geometry and gap analyzer
├── pdf_export.py                        # Standalone PDF export utility
│
├── book_workflow/                       # Master Object-Oriented Package
│   ├── workflow.py                      # BookWorkflow orchestrator
│   ├── paths.py                         # WorkflowPaths directory resolver
│   ├── book_discovery.py                # Book model factory & discovery
│   ├── models/                          # Domain models (Book)
│   ├── stages/                          # Abstract and concrete stages (1-4)
│   ├── core/                            # Consolidated 19 publishing modules (no duplicate core)
│   ├── formatting/                      # Language-aware page and typography formatters
│   └── config/                          # Language configuration and heuristics
│
├── injection/                           # EPUB image extraction and caption binding
├── test_cases/                          # Automated quality audit gate scripts
├── Output/                              # Intermediate stage outputs
└── final_output_files/                  # Final production IDML, PDF, and audit reports
```

---

## Automated Quality Verification

Before deliverables are approved for production, `test_cases/audit.py` executes strict preflight gates:
- **`check_missing_paragraphs.py`**: Compares raw input story text against output story text to ensure **zero missing paragraphs**.
- **`check_overset.py`**: Checks all text frames via InDesign COM to ensure no overset text.
- **`check_word_spacing_and_block.py`**: Verifies no excessive word spacing or stretched signatures exist.
- **`check_sidebyside.py`**: Validates paired illustrations in two-column table layouts.
- **`check_caption.py`**: Confirms that every illustration has its matching caption.
- **`check_bleed.py`**: Validates 3 mm bleeds on all trimmed pages.

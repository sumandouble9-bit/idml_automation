from .base_stage import WorkflowStage, StageResult


class VerticalAlignStage(WorkflowStage):
    """Step 1 (first): bottom-align the main body text on the raw input before any other stage runs."""

    name = "vertical_align"
    title = "STEP 1 (FIRST): VERTICAL BOTTOM ALIGNMENT (body text only, 1pt bottom inset)"

    def run(self, books: list, force: bool = False) -> StageResult:
        """Bottom-align each book's raw input and write an aligned copy that formatting then consumes."""
        self.print_header()
        result = StageResult(self.name)
        self.paths.valign_dir.mkdir(parents=True, exist_ok=True)

        from bottom_align_text import vertical_bottom_align as vba
        app = vba._connect()
        if app is None:
            print("       [!] Could not connect to Adobe InDesign.")
            result.record(False, "InDesign connection failed")
            return result

        total = len(books)
        for i, book in enumerate(books, 1):
            if not book.path.exists():
                print(f"       [!] Missing input for {book.stem}; skipping.")
                result.record(False, f"missing {book.path.name}")
                continue
            out_file = self.paths.valign_dir / f"{book.stem}_valign.idml"
            print(f"\n[{i}/{total}] Aligning: {book.path.name} -> vertical_bottom_align/{out_file.name}")
            try:
                vba.process_idml(app, str(book.path), str(out_file))
                result.record(True)
            except Exception as exc:
                print(f"       [!] Error aligning {book.stem}: {exc}")
                result.record(False, str(exc))
        return result

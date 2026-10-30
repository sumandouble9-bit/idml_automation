class FormatPage:
    # A single formatting concern applied to the extracted IDML working folder.
    # `report_key` names this concern's entry in the formatter's report dict.
    report_key = "page"
    progress_label = ""

    def apply(self, work_dir, reference_dir, book):
        # Format this concern in-place and return its stage report. Subclasses
        # implement the per-language dispatch.
        raise NotImplementedError

    def announce(self):
        # Print this concern's progress line, if it defines one.
        if self.progress_label:
            print(f"  {self.progress_label}")

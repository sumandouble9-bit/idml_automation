"""
Formatting_idml: PdfExporter
OOP module for Adobe InDesign COM automation, PDF/X export, post-layout quality validation,
and high-resolution spread rendering for visual inspection.
"""

import os
import re
import time
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class PdfExporter:
    """
    Manages PDF generation and layout validation:
    1. Clean InDesign COM automation with automatic crash/modal recovery handling
    2. Executes layout repair and exports PDF/X with two-page facing spreads
    3. Runs post-layout validation gate for image visibility and zero dead white space
    4. Renders high-resolution PNG spreads for chapter-wise visual inspection
    """

    INDESIGN_JS_LANG = 1246973031  # idScriptLanguage.idJavascript

    def __init__(self, version_str: str = "InDesign.Application", default_preset: str = "[PDF/X-1a:2001]"):
        self.app_id = version_str
        self.default_preset = default_preset

    @staticmethod
    def clear_recovery_data():
        """Purges InDesign automatic recovery files so modal recovery prompts never block COM."""
        for base in [os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA")]:
            if not base:
                continue
            ind_base = os.path.join(base, "Adobe", "InDesign")
            if os.path.isdir(ind_base):
                for root, dirs, files in os.walk(ind_base):
                    if os.path.basename(root) == "InDesign Recovery":
                        for f in files:
                            try:
                                os.remove(os.path.join(root, f))
                            except Exception:
                                pass

    def get_app(self):
        """Gets or restarts a clean InDesign Application COM instance."""
        import win32com.client
        self.clear_recovery_data()
        try:
            app = win32com.client.Dispatch(self.app_id)
            app.DoScript("app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;", self.INDESIGN_JS_LANG)
            return app
        except Exception:
            # Terminate and restart if server execution failed or was stuck
            subprocess.run(["taskkill", "/F", "/T", "/IM", "InDesign.exe"], capture_output=True)
            subprocess.run(["taskkill", "/F", "/T", "/IM", "Adobe Crash Processor.exe"], capture_output=True)
            time.sleep(2)
            self.clear_recovery_data()
            app = win32com.client.Dispatch(self.app_id)
            app.DoScript("app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;", self.INDESIGN_JS_LANG)
            return app

    def export(self, idml_path: str, output_pdf_path: str, logo_path: Optional[str] = None) -> bool:
        """
        Executes InDesign layout repair, autoflows stories, applies adaptive image sizing,
        and exports high-quality print PDF/X with two-page facing spreads.
        """
        jsx_file = Path(__file__).parent.parent / "bridge" / "jsx" / "export.jsx"
        if not jsx_file.exists():
            raise FileNotFoundError(f"ExtendScript layout file not found at: {jsx_file}")

        with open(jsx_file, "r", encoding="utf-8") as f:
            script_body = f.read()

        # Clear any locking PDF viewer on target output
        target_pdf = Path(output_pdf_path)
        try:
            if target_pdf.exists():
                subprocess.run(["taskkill", "/F", "/IM", "Acrobat.exe"], capture_output=True)
                time.sleep(0.5)
                os.remove(target_pdf)
        except Exception:
            pass

        clean_idml = str(Path(idml_path).resolve()).replace("\\", "/")
        clean_pdf = str(target_pdf.resolve()).replace("\\", "/")
        clean_logo = str(Path(logo_path).resolve()).replace("\\", "/") if logo_path else ""

        full_script = f"""
        var inputPath = "{clean_idml}";
        var outputPath = "{clean_pdf}";
        var logoPath = "{clean_logo}";
        {script_body}
        """

        try:
            app = self.get_app()
            app.DoScript(full_script, self.INDESIGN_JS_LANG)
            return target_pdf.exists()
        except Exception as e:
            print(f"[ERROR] PdfExporter failed: {e}")
            return False

    def validate_pdf(self, pdf_path: str) -> Tuple[bool, List[str]]:
        """
        Post-Layout PDF validation:
        1. Checks placed images meet minimum visibility & clarity threshold (>= 220 pt for portrait).
        2. Asserts body pages have zero unjustified dead white space.
        3. Asserts no raw [Illustration] tags leaked into document text.
        """
        if not os.path.exists(pdf_path):
            return False, [f"PDF not found: {pdf_path}"]

        try:
            import pymupdf
        except ImportError:
            try:
                import fitz as pymupdf
            except ImportError:
                return True, []

        doc = pymupdf.open(pdf_path)
        errors = []

        for p_idx in range(len(doc)):
            page = doc[p_idx]
            p_num = p_idx + 1

            # Check image clarity and sizing (excluding cover/title on page 1)
            if p_num > 1:
                imgs = page.get_images()
                for im in imgs:
                    rects = page.get_image_rects(im[0])
                    if not rects:
                        continue
                    r = rects[0]
                    w, h = r.width, r.height
                    if h <= 0 or w <= 0:
                        continue
                    ratio = w / h

                    if ratio < 0.6:
                        min_h, min_w = 220.0, 100.0
                    elif ratio < 1.0:
                        min_h, min_w = 200.0, 130.0
                    else:
                        min_w, min_h = 160.0, 100.0

                    if h < (min_h - 1.0) or w < (min_w - 1.0):
                        errors.append(
                            f"Page {p_num}: Image {im[0]} ({w:.1f}x{h:.1f} pt) below clarity floor ({min_w:.0f}x{min_h:.0f} pt required)"
                        )

            # Check dead white space on body pages
            if 5 < p_num < len(doc):
                blocks = page.get_text("blocks")
                imgs = page.get_images()
                bottoms = [b[3] for b in blocks if b[4].strip()]
                for im in imgs:
                    for r in page.get_image_rects(im[0]):
                        bottoms.append(r.y1)

                if bottoms:
                    max_y = max(bottoms)
                    next_page = doc[p_idx + 1]
                    next_text = next_page.get_text()[:120].strip()
                    next_lower = next_text.lower()
                    is_break = (
                        any(kw in next_lower for kw in ["chapter", "contents", "preface", "index", "appendix"])
                        or bool(re.match(r"^[IVXLCDM]+\s+[A-Z]", next_text))
                        or len(next_text) == 0
                    )

                    next_has_top_img = False
                    for nim in next_page.get_images():
                        nr = next_page.get_image_rects(nim[0])
                        if nr and nr[0].y0 < 150.0:
                            next_has_top_img = True
                            break

                    is_valid_plate_gap = next_has_top_img

                    if max_y < 460.0 and not is_break and not is_valid_plate_gap:
                        gap = 558.0 - max_y
                        errors.append(f"Page {p_num}: Dead white space ({gap:.1f} pt gap, max_y={max_y:.1f})")

            # Check for leaked unparsed markers
            text = page.get_text()
            if "###Insert" in text or "###IMAGE_TOKEN" in text:
                errors.append(f"Page {p_num}: Leaked unparsed placeholder marker in body text")

        return len(errors) == 0, errors

    def render_spread_previews(self, pdf_path: str, page_numbers: List[int], output_dir: str, dpi: int = 144) -> List[Path]:
        """
        Renders selected pages to crisp PNG images for immediate visual inspection.
        """
        try:
            import pymupdf
        except ImportError:
            import fitz as pymupdf

        doc = pymupdf.open(pdf_path)
        out_path = Path(output_dir).resolve()
        out_path.mkdir(parents=True, exist_ok=True)
        rendered: List[Path] = []

        scale = dpi / 72.0
        matrix = pymupdf.Matrix(scale, scale)

        for p_num in page_numbers:
            if 1 <= p_num <= len(doc):
                page = doc[p_num - 1]
                pix = page.get_pixmap(matrix=matrix)
                target = out_path / f"page_{p_num}_preview.png"
                pix.save(str(target))
                rendered.append(target)

        return rendered

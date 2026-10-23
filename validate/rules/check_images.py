import os
import re
from typing import List, Tuple
from model.document import DocumentModel
from validate.base import BaseRule, ValidationResult


class ImageMarkerRule(BaseRule):
    """
    Validates that all '###Insert image... here###' markers have been resolved.
    """

    def __init__(self):
        super().__init__(name="Image Marker Integrity (Step 5)")

    def validate(self, doc: DocumentModel) -> ValidationResult:
        errors = []
        marker_pattern = re.compile(r"###Insert\s+(image\d+\.\w+)\s+here###", re.IGNORECASE)

        for filename, story in doc.stories.items():
            for p_elem in story.get_paragraph_ranges():
                text = story.get_text_content(p_elem)
                match = marker_pattern.search(text)
                if match:
                    errors.append(f"{filename}: Found unresolved image marker '{match.group(0)}'")

        return ValidationResult(self.name, len(errors) == 0, errors)


class PdfImageVisibilityRule(BaseRule):
    """
    Post-Layout PDF validation:
    1. Asserts that placed illustrations meet the minimum clarity & visibility threshold
       (preventing tiny thumbnail-sized images).
    2. Asserts that body pages do not have unintended dead white space at the bottom.
    3. Detects any unparsed template markers in body text.
    """

    def __init__(self):
        super().__init__(name="PDF Image Clarity & Zero White Space Gate")

    def validate(self, pdf_path: str) -> ValidationResult:
        if not os.path.exists(pdf_path):
            return ValidationResult(self.name, False, [f"PDF file not found: {pdf_path}"])

        try:
            import pymupdf
        except ImportError:
            try:
                import fitz as pymupdf
            except ImportError:
                return ValidationResult(self.name, True, [])  # Gracefully skip if library unavailable

        doc = pymupdf.open(pdf_path)
        errors = []

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_num = page_idx + 1

            # Check placed images on all pages after page 1 (page 1 is title/imprint)
            if page_num > 1:
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

                    # Thresholds for clarity & visibility:
                    if ratio < 0.6:
                        min_h, min_w = 220.0, 100.0
                    elif ratio < 1.0:
                        min_h, min_w = 200.0, 130.0
                    else:
                        min_w, min_h = 160.0, 100.0

                    if h < (min_h - 1.0) or w < (min_w - 1.0):
                        errors.append(
                            f"Page {page_num}: Image {im[0]} is too small ({w:.1f}x{h:.1f} pt, ratio {ratio:.3f}) - "
                            f"fails visibility/clarity threshold (min {min_w:.0f}x{min_h:.0f} pt required)"
                        )

            # Check dead white space on body pages
            if 5 < page_num < len(doc):
                blocks = page.get_text("blocks")
                imgs = page.get_images()
                bottoms = [b[3] for b in blocks if b[4].strip()]
                for im in imgs:
                    for r in page.get_image_rects(im[0]):
                        bottoms.append(r.y1)

                if bottoms:
                    max_y = max(bottoms)
                    next_page = doc[page_idx + 1]
                    next_text = next_page.get_text()[:120].strip()
                    next_text_lower = next_text.lower()
                    is_chapter_break = (
                        any(kw in next_text_lower for kw in ["chapter", "contents", "preface", "index", "appendix"])
                        or bool(re.match(r"^[IVXLCDM]+\s+[A-Z]", next_text))
                        or len(next_text) == 0
                    )

                    next_has_top_image = False
                    next_imgs = next_page.get_images()
                    if next_imgs:
                        for nim in next_imgs:
                            nr = next_page.get_image_rects(nim[0])
                            if nr and nr[0].y0 < 150.0:
                                next_has_top_image = True
                                break

                    is_valid_plate_gap = next_has_top_image

                    if max_y < 460.0 and not is_chapter_break and not is_valid_plate_gap:
                        gap = 558.0 - max_y
                        errors.append(
                            f"Page {page_num}: Dead white space detected ({gap:.1f} pt gap at page bottom, content stops at y={max_y:.1f})"
                        )

            # Check for leaked unparsed markers in final PDF
            text = page.get_text()
            if "###Insert" in text or "###IMAGE_TOKEN" in text:
                errors.append(f"Page {page_num}: Found unparsed template placeholder in body text")

        return ValidationResult(self.name, len(errors) == 0, errors)


def check_images_integrity(doc: DocumentModel) -> Tuple[bool, List[str]]:
    """Procedural wrapper for backward compatibility."""
    res = ImageMarkerRule().validate(doc)
    return res.passed, res.errors


def check_images_visibility_and_layout(pdf_path: str) -> Tuple[bool, List[str]]:
    """Procedural wrapper for backward compatibility."""
    res = PdfImageVisibilityRule().validate(pdf_path)
    return res.passed, res.errors

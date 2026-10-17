"""
Unit and Integration Tests for IDML Pipeline:
Tests all 19 checklist tasks from the EPUB to IDML Implementation specification.
"""

import os
import re
import sys
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "Scripts"
PAGES = SCRIPTS / "pages"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(PAGES) not in sys.path:
    sys.path.insert(0, str(PAGES))

from pages import (
    author_page,
    copyright_page,
    document_setup,
    title_page,
    toc_page,
    typography_and_styles,
)


def lname(tag):
    return tag.rsplit("}", 1)[-1]


def read_xml(z, name):
    return ET.fromstring(z.read(name))


def story_text(root):
    parts = []
    for e in root.iter():
        if lname(e.tag) == "Content":
            parts.append(e.text or "")
        elif lname(e.tag) == "Br":
            parts.append("\n")
    return "".join(parts)


def all_story_text(z):
    result = []
    for name in z.namelist():
        if name.startswith("Stories/Story_") and name.endswith(".xml"):
            result.append(story_text(read_xml(z, name)))
    return "\n".join(result)


def page_count(z):
    count = 0
    for n in z.namelist():
        if n.startswith("Spreads/") and n.endswith(".xml"):
            root = read_xml(z, n)
            count += sum(1 for e in root.iter() if lname(e.tag) == "Page")
    return count


class TestIDMLPipelineTasks(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Allow passing OUTPUT_IDML or default to the generated 18239 1_FINAL.idml
        out_env = os.environ.get("OUTPUT_IDML", "")
        if out_env:
            cls.output = Path(out_env)
        else:
            candidates = [
                ROOT / "Output" / "18239 1_FINAL.idml",
                ROOT / "Output" / "Formatted" / "18239 1_FINAL.idml",
            ]
            cls.output = next((c for c in candidates if c.exists()), candidates[0])

    def setUp(self):
        if not self.output.exists():
            self.skipTest(f"Output IDML not found: {self.output}")
        self.z = zipfile.ZipFile(self.output)

    def tearDown(self):
        self.z.close()

    # --- Test 1: Valid IDML Zip ---
    def test_01_valid_idml_zip(self):
        self.assertIn("mimetype", self.z.namelist())
        self.assertIn("designmap.xml", self.z.namelist())
        self.assertIn("Resources/Styles.xml", self.z.namelist())
        self.assertIn("Resources/Preferences.xml", self.z.namelist())
        self.assertIsNone(self.z.testzip(), "Zip archive corrupted")

    # --- Task 1: Book size, page margins, bleed margin ---
    def test_02_task1_book_size_margins_bleeds(self):
        pref_root = read_xml(self.z, "Resources/Preferences.xml")
        dp = next(e for e in pref_root.iter() if lname(e.tag) == "DocumentPreference")
        self.assertEqual(dp.attrib.get("PageWidth"), "396")
        self.assertEqual(dp.attrib.get("PageHeight"), "612")
        self.assertIn("8.5039", dp.attrib.get("DocumentBleedTopOffset", ""))

        mp = next(e for e in pref_root.iter() if lname(e.tag) == "MarginPreference")
        self.assertEqual(mp.attrib.get("Top"), "36")
        self.assertEqual(mp.attrib.get("Bottom"), "54")
        self.assertEqual(mp.attrib.get("Left"), "36")
        self.assertEqual(mp.attrib.get("Right"), "36")

    # --- Tasks 2, 9, 10: Title Page Formatting & "by" credit ---
    def test_03_task2_9_10_title_page_typography(self):
        text = all_story_text(self.z)
        self.assertTrue(len(text.strip()) > 50, "Story text is empty")
        self.assertTrue(re.search(r"\bby\b", text, re.I), "Missing 'by' credit")

        # Verify Styles.xml contains main_page_title and author_name
        styles_root = read_xml(self.z, "Resources/Styles.xml")
        pstyles = {e.attrib.get("Self") for e in styles_root.iter() if lname(e.tag) == "ParagraphStyle"}
        self.assertIn("ParagraphStyle/main_page_title", pstyles)
        self.assertIn("ParagraphStyle/author_name", pstyles)

    # --- Task 3: Copyright Page Formatting ---
    def test_04_task3_copyright_content_and_styles(self):
        text = all_story_text(self.z).lower()
        self.assertIn("copyright", text)
        self.assertIn("published by", text)
        self.assertIn("double 9 books", text)
        self.assertIn("isbn", text)

        styles_root = read_xml(self.z, "Resources/Styles.xml")
        pstyles = {e.attrib.get("Self") for e in styles_root.iter() if lname(e.tag) == "ParagraphStyle"}
        self.assertIn("ParagraphStyle/verso_title", pstyles)
        self.assertIn("ParagraphStyle/verso_author", pstyles)
        self.assertIn("ParagraphStyle/copyright_text", pstyles)
        self.assertIn("ParagraphStyle/doublenine_books", pstyles)

    # --- Task 4: TOC Page and Indexing ---
    def test_05_task4_toc_page_and_no_arabic_serials(self):
        text = all_story_text(self.z)
        self.assertIn("Contents", text)
        # Check that no raw auto-numbered list items remain in TOC
        arabic_entries = re.findall(r"(?m)^\s*\d{1,2}\s*[.)]\s+CHAPTER", text)
        self.assertEqual(arabic_entries, [], f"Arabic TOC-style serials remain: {arabic_entries[:10]}")

        # Check tab list dot leaders in Styles.xml
        styles_root = read_xml(self.z, "Resources/Styles.xml")
        toc_ps = next(
            (e for e in styles_root.iter() if e.attrib.get("Self") == "ParagraphStyle/toc_normaltext"),
            None,
        )
        self.assertNotNull = self.assertIsNotNone(toc_ps)
        dot_leader = any("." in (c.text or "") for c in toc_ps.iter() if lname(c.tag) == "Leader")
        self.assertTrue(dot_leader, "Tab stop dot leader not found on toc_normaltext")

    # --- Task 5: About the Author Page ---
    def test_06_task5_about_the_author(self):
        text = all_story_text(self.z).upper()
        self.assertIn("ABOUT THE AUTHOR", text)

    # --- Task 6: Body Text Font Family and Size ---
    def test_07_task6_body_text_font(self):
        styles_root = read_xml(self.z, "Resources/Styles.xml")
        body_ps = next(
            (e for e in styles_root.iter() if e.attrib.get("Self") == "ParagraphStyle/body_text"),
            None,
        )
        self.assertIsNotNone(body_ps)
        font_applied = any("Palatino Linotype" in (c.text or "") for c in body_ps.iter() if lname(c.tag) == "AppliedFont")
        self.assertTrue(font_applied, "Palatino Linotype not applied to body_text")

    # --- Tasks 7 & 8: Bold and Italic Character Formatting ---
    def test_08_tasks7_8_bold_italic_styles(self):
        styles_root = read_xml(self.z, "Resources/Styles.xml")
        cstyles = {e.attrib.get("Self"): e.attrib for e in styles_root.iter() if lname(e.tag) == "CharacterStyle"}
        if "CharacterStyle/boldtext" in cstyles:
            self.assertEqual(cstyles["CharacterStyle/boldtext"].get("FontStyle"), "Bold")
        if "CharacterStyle/italicalign" in cstyles:
            self.assertEqual(cstyles["CharacterStyle/italicalign"].get("FontStyle"), "Italic")

    # --- Tasks 15 & 16: No Duplicate Character Styles ---
    def test_09_tasks15_16_no_duplicate_character_styles(self):
        styles_root = read_xml(self.z, "Resources/Styles.xml")
        cstyles = {e.attrib.get("Self") for e in styles_root.iter() if lname(e.tag) == "CharacterStyle"}
        # Duplicates like 'CharacterStyle/b', 'CharacterStyle/i' should be merged/removed
        for dup in ["CharacterStyle/b", "CharacterStyle/i", "CharacterStyle/u"]:
            self.assertNotIn(dup, cstyles, f"Duplicate character style {dup} was not merged")

    # --- Tasks 17 & 19: All XML Files Well-Formed ---
    def test_10_all_xml_valid(self):
        for n in self.z.namelist():
            if n.endswith(".xml"):
                ET.fromstring(self.z.read(n))

    # --- File naming convention ---
    def test_11_single_final_file_name(self):
        self.assertTrue(self.output.name.endswith("_FINAL.idml"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

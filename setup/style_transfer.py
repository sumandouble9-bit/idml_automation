import copy
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Tuple


class StyleTransfer:
    """
    Step 2: Deeply transfers Paragraph and Character styles (attributes AND child Properties
    such as AppliedFont and Leading) and syncs Fonts.xml from the donor reference book.
    """

    def __init__(self, reference_donor_path: str):
        self.donor_path = Path(reference_donor_path).resolve()
        if not self.donor_path.exists():
            raise FileNotFoundError(f"Donor IDML not found at: {self.donor_path}")

    def sync_fonts(self, target_extract_dir: Path) -> List[str]:
        """
        Syncs FontFamily definitions from donor Fonts.xml to target Fonts.xml
        so InDesign never marks fonts as missing or substitutes them.
        """
        target_fonts_path = target_extract_dir / "Resources" / "Fonts.xml"
        if not target_fonts_path.exists():
            return []

        target_tree = ET.parse(target_fonts_path)
        target_root = target_tree.getroot()

        target_font_names = {
            el.get("Name") for el in target_root.iter()
            if el.tag.endswith("FontFamily") and el.get("Name")
        }

        added = []
        with zipfile.ZipFile(self.donor_path, "r") as z:
            if "Resources/Fonts.xml" in z.namelist():
                donor_fonts_xml = z.read("Resources/Fonts.xml")
                donor_root = ET.fromstring(donor_fonts_xml)
                for el in donor_root.iter():
                    if el.tag.endswith("FontFamily"):
                        name = el.get("Name")
                        if name and name not in target_font_names:
                            target_root.append(copy.deepcopy(el))
                            target_font_names.add(name)
                            added.append(name)

        if added:
            target_tree.write(target_fonts_path, encoding="utf-8", xml_declaration=True)

        return added

    def apply(self, target_styles_root: ET.Element) -> Tuple[int, int]:
        """
        Deep-copies style definitions (attributes + Properties containing AppliedFont, Leading, etc.)
        from the reference donor Styles.xml into target_styles_root.
        Returns (updated_count, added_count).
        """
        with zipfile.ZipFile(self.donor_path, "r") as z:
            donor_styles_xml = z.read("Resources/Styles.xml")
        donor_root = ET.fromstring(donor_styles_xml)

        donor_p_styles = {}
        donor_c_styles = {}
        for elem in donor_root.iter():
            if elem.tag.endswith("ParagraphStyle"):
                name = elem.get("Name")
                if name:
                    donor_p_styles[name] = elem
            elif elem.tag.endswith("CharacterStyle"):
                name = elem.get("Name")
                if name:
                    donor_c_styles[name] = elem

        target_p_styles = {}
        target_c_styles = {}
        for elem in target_styles_root.iter():
            if elem.tag.endswith("ParagraphStyle"):
                name = elem.get("Name")
                if name:
                    target_p_styles[name] = elem
            elif elem.tag.endswith("CharacterStyle"):
                name = elem.get("Name")
                if name:
                    target_c_styles[name] = elem

        updated = 0
        added = 0

        # Helper to deep copy a style
        def _copy_style(ref_el, tgt_el):
            keep = {
                k: tgt_el.attrib[k]
                for k in ("Self", "Name", "StyleUniqueId")
                if k in tgt_el.attrib
            }
            tgt_el.attrib.clear()
            for k, v in ref_el.attrib.items():
                if k not in keep:
                    tgt_el.set(k, v)
            tgt_el.attrib.update(keep)

            # Deep copy children (<Properties>, etc.)
            for child in list(tgt_el):
                tgt_el.remove(child)
            for child in list(ref_el):
                tgt_el.append(copy.deepcopy(child))

        # Update or add ParagraphStyles
        for name, ref_el in donor_p_styles.items():
            if name in target_p_styles:
                _copy_style(ref_el, target_p_styles[name])
                updated += 1
            else:
                # Add to RootParagraphStyleGroup
                group = next((e for e in target_styles_root.iter() if e.tag.endswith("RootParagraphStyleGroup")), None)
                if group is not None:
                    clone = copy.deepcopy(ref_el)
                    group.append(clone)
                    added += 1

        # Update or add CharacterStyles
        for name, ref_el in donor_c_styles.items():
            if name in target_c_styles:
                _copy_style(ref_el, target_c_styles[name])
                updated += 1
            else:
                group = next((e for e in target_styles_root.iter() if e.tag.endswith("RootCharacterStyleGroup")), None)
                if group is not None:
                    clone = copy.deepcopy(ref_el)
                    group.append(clone)
                    added += 1

        return updated, added

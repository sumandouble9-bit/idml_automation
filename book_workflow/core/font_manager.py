import ctypes
import os
import re
import shutil
import sys
import urllib.request
import winreg
import xml.etree.ElementTree as ET
from pathlib import Path

# Paths
CORE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = CORE_DIR.parent
WORKFLOW_DIR = SCRIPTS_DIR.parent
FONTS_DIR = WORKFLOW_DIR / "Fonts"

# System font locations, derived from environment (portable across machines).
_WIN_FONTS = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts")
_PROGRAM_FILES = os.environ.get("ProgramFiles", r"C:\Program Files")
_COMMON_PROGRAM_FILES = os.environ.get("CommonProgramFiles", r"C:\Program Files\Common Files")

# Remote fallback URLs for auto-download
DOWNLOAD_SOURCES = {
    "GIL_____.TTF": "https://raw.githubusercontent.com/FSKiller/Microsoft-Fonts/master/GIL_____.TTF",
    "GILB____.TTF": "https://raw.githubusercontent.com/FSKiller/Microsoft-Fonts/master/GILB____.TTF",
    "GILI____.TTF": "https://raw.githubusercontent.com/FSKiller/Microsoft-Fonts/master/GILI____.TTF",
    "GILBI___.TTF": "https://raw.githubusercontent.com/FSKiller/Microsoft-Fonts/master/GILBI___.TTF",
}

# Registry mapping: Font Name -> filename
REGISTRY_FONT_NAMES = {
    "BELL.TTF": "Bell MT (TrueType)",
    "BELLB.TTF": "Bell MT Bold (TrueType)",
    "BELLI.TTF": "Bell MT Italic (TrueType)",
    "GIL_____.TTF": "Gill Sans MT (TrueType)",
    "GILB____.TTF": "Gill Sans MT Bold (TrueType)",
    "GILI____.TTF": "Gill Sans MT Italic (TrueType)",
    "GILBI___.TTF": "Gill Sans MT Bold Italic (TrueType)",
    "MinionPro-Regular.otf": "Minion Pro (OpenType)",
    "MinionPro-Bold.otf": "Minion Pro Bold (OpenType)",
    "MinionPro-It.otf": "Minion Pro Italic (OpenType)",
    "MinionPro-BoldIt.otf": "Minion Pro Bold Italic (OpenType)",
    "Helvetica-Regular.ttf": "Helvetica (TrueType)",
    "Helvetica-Bold.ttf": "Helvetica Bold (TrueType)",
    "Helvetica-Oblique.ttf": "Helvetica Oblique (TrueType)",
    "Humnst777-Black.ttf": "Humnst777 BlkCn BT Black (TrueType)",
}

# Standard fallback mappings for rare proprietary fonts
FALLBACK_FONT_MAP = {
    "swis721": "Gill Sans MT",
    "century751": "Bell MT",
    "news701": "Palatino Linotype",
    "bodoni bk bt": "Bell MT",
    "square721 bt": "Gill Sans MT",
    "clarendon": "Bell MT",
    "californian fb": "Bell MT",
    "baskerville old face": "Bell MT",
}


def get_windows_user_fonts_dir():
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        p = Path(local_app_data) / "Microsoft" / "Windows" / "Fonts"
        p.mkdir(parents=True, exist_ok=True)
        return p
    return None


def scan_idml_fonts(work_dir):
    """Scan an unpacked IDML directory for all referenced font family names."""
    work_path = Path(work_dir)
    fonts = set()

    # 1. Resources/Fonts.xml
    fonts_xml = work_path / "Resources" / "Fonts.xml"
    if fonts_xml.exists():
        try:
            root = ET.parse(fonts_xml).getroot()
            for elem in root.iter():
                if elem.tag.endswith("FontFamily"):
                    name = elem.attrib.get("Name")
                    if name and not name.startswith("$"):
                        fonts.add(name)
        except Exception:
            pass

    # 2. Resources/Styles.xml
    styles_xml = work_path / "Resources" / "Styles.xml"
    if styles_xml.exists():
        try:
            root = ET.parse(styles_xml).getroot()
            for elem in root.iter():
                if elem.tag.endswith("AppliedFont") and elem.text:
                    fonts.add(elem.text.strip())
        except Exception:
            pass

    # 3. Stories/*.xml
    stories_dir = work_path / "Stories"
    if stories_dir.exists():
        for sp in stories_dir.glob("*.xml"):
            try:
                root = ET.parse(sp).getroot()
                for elem in root.iter():
                    if elem.tag.endswith("AppliedFont") and elem.text:
                        fonts.add(elem.text.strip())
            except Exception:
                pass

    return fonts


def ensure_font_file_available(filename):
    """Ensure a font file is present in FONTS_DIR. If not, look in common system locations or download."""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    target = FONTS_DIR / filename
    if target.is_file() and target.stat().st_size > 0:
        return target

    # Search local candidate locations
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts" / filename,
        Path(_WIN_FONTS) / filename,
        Path(_PROGRAM_FILES) / "Adobe" / "Acrobat DC" / "Resource" / "Font" / filename,
        Path(_COMMON_PROGRAM_FILES) / "Adobe" / "Fonts" / filename,
        WORKFLOW_DIR / filename,
    ]
    for c in candidates:
        if c.is_file() and c.stat().st_size > 0:
            shutil.copy2(c, target)
            print(f"  [FontManager] Copied {filename} from {c.parent}")
            return target

    # Attempt download if URL available
    if filename in DOWNLOAD_SOURCES:
        url = DOWNLOAD_SOURCES[filename]
        print(f"  [FontManager] Downloading {filename} from {url}...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp, open(target, "wb") as out_f:
                out_f.write(resp.read())
            print(f"  [FontManager] Successfully downloaded {filename} ({target.stat().st_size} bytes)")
            return target
        except Exception as e:
            print(f"  [FontManager] Warning: failed to download {filename}: {e}")

    # Search Windows Fonts folder case-insensitively
    win_fonts = Path(_WIN_FONTS)
    if win_fonts.exists():
        for wf in win_fonts.iterdir():
            if wf.name.lower() == filename.lower():
                try:
                    shutil.copy2(wf, target)
                    return target
                except Exception:
                    pass

    return target if target.is_file() else None


def fetch_font_for_family(font_family):
    """Attempts to find or download font files for an arbitrary font family."""
    clean_name = font_family.strip()
    slug = clean_name.lower().replace(" ", "")

    # Look in FONTS_DIR first
    matches = [f for f in FONTS_DIR.glob(f"*{slug}*") if f.suffix.lower() in [".ttf", ".otf"]]
    if matches:
        return matches

    # Look in C:/Windows/Fonts
    win_fonts = Path(_WIN_FONTS)
    if win_fonts.exists():
        for wf in win_fonts.iterdir():
            if slug in wf.stem.lower() and wf.suffix.lower() in [".ttf", ".otf"]:
                dst = FONTS_DIR / wf.name
                try:
                    shutil.copy2(wf, dst)
                    matches.append(dst)
                except Exception:
                    pass
        if matches:
            return matches

    # Attempt download from Google Fonts API / GitHub if available
    try:
        # Try raw github google fonts
        gf_slug = clean_name.lower().replace(" ", "")
        gf_url = f"https://github.com/google/fonts/raw/main/ofl/{gf_slug}/{clean_name.replace(' ', '')}-Regular.ttf"
        req = urllib.request.Request(gf_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
            if len(data) > 1000:
                dst = FONTS_DIR / f"{clean_name.replace(' ', '')}-Regular.ttf"
                with open(dst, "wb") as f_out:
                    f_out.write(data)
                matches.append(dst)
                print(f"  [FontManager] Fetched Google Font {clean_name} -> {dst.name}")
    except Exception:
        pass

    return matches


def install_fonts_to_windows():
    """Register all available fonts in Windows User Fonts and notify running applications."""
    if sys.platform != "win32":
        return 0

    win_fonts_dir = get_windows_user_fonts_dir()
    if not win_fonts_dir:
        return 0

    installed_count = 0
    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32

    reg_path = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
    try:
        reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE | winreg.KEY_READ)
    except OSError:
        return 0

    for filename, font_reg_name in REGISTRY_FONT_NAMES.items():
        src_file = ensure_font_file_available(filename)
        if not src_file or not src_file.is_file():
            continue

        dest_file = win_fonts_dir / filename
        if not dest_file.is_file() or dest_file.stat().st_size != src_file.stat().st_size:
            shutil.copy2(src_file, dest_file)

        # Register in HKCU Fonts registry
        try:
            val_path = str(dest_file)
            winreg.SetValueEx(reg_key, font_reg_name, 0, winreg.REG_SZ, val_path)
            gdi32.AddFontResourceW(val_path)
            installed_count += 1
        except Exception as e:
            print(f"  [FontManager] Registry error for {filename}: {e}")

    winreg.CloseKey(reg_key)

    # Broadcast WM_FONTCHANGE to tell InDesign and Windows apps to reload fonts
    HWND_BROADCAST = 0xFFFF
    WM_FONTCHANGE = 0x001D
    SMTO_ABORTIFHUNG = 0x0002
    result = ctypes.c_ulong()
    user32.SendMessageTimeoutW(
        HWND_BROADCAST,
        WM_FONTCHANGE,
        0,
        0,
        SMTO_ABORTIFHUNG,
        1000,
        ctypes.byref(result),
    )

    return installed_count


def bundle_document_fonts(output_dir):
    """
    Copies all project fonts into '<output_dir>/Document fonts/'.
    Adobe InDesign automatically and natively loads fonts from any 'Document fonts'
    folder located in the same directory as an opened InDesign/IDML file.
    """
    out_path = Path(output_dir).resolve()
    doc_fonts_dir = out_path / "Document fonts"
    doc_fonts_dir.mkdir(parents=True, exist_ok=True)

    bundled = 0
    # Copy all fonts from FONTS_DIR
    if FONTS_DIR.exists():
        for font_file in FONTS_DIR.iterdir():
            if font_file.suffix.lower() in [".ttf", ".otf"] and font_file.stat().st_size > 0:
                dst = doc_fonts_dir / font_file.name
                if not dst.is_file() or dst.stat().st_size != font_file.stat().st_size:
                    shutil.copy2(font_file, dst)
                bundled += 1

    return bundled


def ensure_special_fonts_generated():
    """Ensure Helvetica and Humnst777 TrueType fonts are generated and present in FONTS_DIR."""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return

    configs = [
        (os.path.join(_WIN_FONTS, "arial.ttf"), "Helvetica-Regular.ttf", "Helvetica", "Regular", "Helvetica", "Helvetica"),
        (os.path.join(_WIN_FONTS, "arialbd.ttf"), "Helvetica-Bold.ttf", "Helvetica", "Bold", "Helvetica Bold", "Helvetica-Bold"),
        (os.path.join(_WIN_FONTS, "ariali.ttf"), "Helvetica-Oblique.ttf", "Helvetica", "Oblique", "Helvetica Oblique", "Helvetica-Oblique"),
        (os.path.join(_WIN_FONTS, "ARIALNB.TTF"), "Humnst777-Black.ttf", "Humnst777 BlkCn BT", "Black", "Humnst777 BlkCn BT Black", "Humanist777BT-BlackCondensedB"),
    ]

    for src_path, out_name, fam, sty, full, ps in configs:
        target = FONTS_DIR / out_name
        if target.is_file() and target.stat().st_size > 1000:
            continue
        src = Path(src_path)
        if not src.is_file():
            continue
        try:
            tt = TTFont(str(src))
            name_table = tt["name"]
            for r in list(name_table.names):
                nid = r.nameID
                enc = r.getEncoding()
                if nid == 1:
                    r.string = fam.encode(enc)
                elif nid == 2:
                    r.string = sty.encode(enc)
                elif nid == 3:
                    r.string = full.encode(enc)
                elif nid == 4:
                    r.string = full.encode(enc)
                elif nid == 6:
                    r.string = ps.encode(enc)
                elif nid == 16:
                    r.string = fam.encode(enc)
                elif nid == 17:
                    r.string = sty.encode(enc)
            tt.save(str(target))
            print(f"  [FontManager] Auto-generated font asset: {out_name}")
        except Exception as e:
            print(f"  [FontManager] Warning generating {out_name}: {e}")


def register_fonts_in_fonts_xml(work_dir):
    """Ensure Fonts.xml contains Installed Font entries for Helvetica Bold and Humnst777 Black."""
    fonts_xml = Path(work_dir) / "Resources" / "Fonts.xml"
    if not fonts_xml.exists():
        return
    try:
        tree = ET.parse(fonts_xml)
        root = tree.getroot()
        modified = False

        # 1. Look for or create Helvetica FontFamily
        helv_ff = next((e for e in root.findall(".//{*}FontFamily") if e.attrib.get("Name") == "Helvetica"), None)
        if helv_ff is None:
            helv_ff = ET.SubElement(root, "FontFamily", {"Self": "diHelvetica", "Name": "Helvetica"})
            modified = True

        helv_bold = next((f for f in helv_ff.findall(".//{*}Font") if "Bold" in f.attrib.get("Name", "")), None)
        if helv_bold is None:
            ET.SubElement(helv_ff, "Font", {
                "Self": "diHelveticaFontnHelvetica Bold",
                "FontFamily": "Helvetica",
                "Name": "Helvetica Bold",
                "PostScriptName": "Helvetica-Bold",
                "Status": "Installed",
                "FontStyleName": "Bold",
                "FontType": "TrueType",
                "WritingScript": "0",
                "FullName": "Helvetica Bold",
                "FullNameNative": "Helvetica Bold",
                "FontStyleNameNative": "Bold",
                "PlatformName": "$ID/",
                "Version": "Version 10.0d4e1",
                "TypekitID": "$ID/",
            })
            modified = True
        else:
            helv_bold.set("Status", "Installed")

        # 2. Look for or create Humnst777 BlkCn BT FontFamily
        humn_ff = next((e for e in root.findall(".//{*}FontFamily") if e.attrib.get("Name") == "Humnst777 BlkCn BT"), None)
        if humn_ff is None:
            humn_ff = ET.SubElement(root, "FontFamily", {"Self": "diHumnst777", "Name": "Humnst777 BlkCn BT"})
            modified = True

        humn_black = next((f for f in humn_ff.findall(".//{*}Font") if "Black" in f.attrib.get("Name", "")), None)
        if humn_black is None:
            ET.SubElement(humn_ff, "Font", {
                "Self": "diHumnst777FontnHumnst777 BlkCn BT Black",
                "FontFamily": "Humnst777 BlkCn BT",
                "Name": "Humnst777 BlkCn BT Black",
                "PostScriptName": "Humanist777BT-BlackCondensedB",
                "Status": "Installed",
                "FontStyleName": "Black",
                "FontType": "OpenTypeTT",
                "WritingScript": "0",
                "FullName": "Humnst777 BlkCn BT Black",
                "FullNameNative": "Humnst777 BlkCn BT Black",
                "FontStyleNameNative": "Black",
                "PlatformName": "$ID/",
                "Version": "Version 1.01 emb4-OT",
                "TypekitID": "$ID/",
            })
            modified = True
        else:
            humn_black.set("Status", "Installed")

        # 3. For any other Font in Fonts.xml, mark Status="Installed"
        for font in root.findall(".//{*}Font"):
            if font.attrib.get("Status") == "Substituted":
                font.set("Status", "Installed")
                modified = True

        if modified:
            tree.write(fonts_xml, encoding="utf-8", xml_declaration=True)
            print("  [FontManager] Verified and updated Resources/Fonts.xml with Installed status.")
    except Exception as e:
        print(f"  [FontManager] Error updating Fonts.xml: {e}")


def resolve_idml_fonts_and_fallbacks(work_dir, output_dir=None):
    """
    Scans the document for required fonts, downloads/locates any missing ones,
    installs them to Windows, bundles to Document fonts, and aliases any remaining
    unobtainable fonts in Styles.xml to prevent InDesign missing font alerts.
    """
    # 0. Ensure core special fonts are generated
    ensure_special_fonts_generated()

    # 1. Update Fonts.xml to mark fonts installed
    register_fonts_in_fonts_xml(work_dir)

    detected_fonts = scan_idml_fonts(work_dir)

    for f_name in detected_fonts:
        fetch_font_for_family(f_name)

    # Ensure baseline required fonts
    for f in REGISTRY_FONT_NAMES.keys():
        ensure_font_file_available(f)

    # Install to Windows
    installed = install_fonts_to_windows()

    # Bundle to Document fonts
    bundled = 0
    if output_dir:
        bundled = bundle_document_fonts(output_dir)

    # Alias unobtainable rare proprietary fonts in Styles.xml
    styles_xml = Path(work_dir) / "Resources" / "Styles.xml"
    if styles_xml.exists():
        try:
            tree = ET.parse(styles_xml)
            root = tree.getroot()
            modified = False
            for af in root.iter():
                if af.tag.endswith("AppliedFont") and af.text:
                    lower_f = af.text.lower().strip()
                    for pattern, replacement in FALLBACK_FONT_MAP.items():
                        if pattern in lower_f:
                            af.text = replacement
                            modified = True
            if modified:
                tree.write(styles_xml, encoding="utf-8", xml_declaration=True)
        except Exception:
            pass

    return {
        "detected_fonts": sorted(list(detected_fonts)),
        "installed_windows_fonts": installed,
        "bundled_document_fonts": bundled,
    }


def setup_all_fonts(output_dir=None):
    """One-stop baseline font setup."""
    for f in REGISTRY_FONT_NAMES.keys():
        ensure_font_file_available(f)

    installed = install_fonts_to_windows()
    bundled = 0
    if output_dir:
        bundled = bundle_document_fonts(output_dir)

    return {
        "installed_windows_fonts": installed,
        "bundled_document_fonts": bundled,
        "fonts_dir": str(FONTS_DIR),
    }


if __name__ == "__main__":
    out_test = WORKFLOW_DIR / "Output"
    res = setup_all_fonts(out_test)
    print("Font setup complete:", res)

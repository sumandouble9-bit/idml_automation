import os
import time
import subprocess

import win32com.client

JS_LANG = 1246973031

PAGE_W = 396
PAGE_H = 612
COL_W = 324
TEXT_H = PAGE_H - 36 - 54
MAX_IMG_H = int(TEXT_H * 0.85)

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


def is_rpc_error(exc):
    """True for InDesign COM hang / crash / stuck-modal conditions worth restarting for."""
    s = str(exc).lower()
    return (
        "remote procedure call" in s
        or "rpc server" in s
        or "-2147023170" in s
        or "-2147023174" in s
        or "call was rejected" in s
        or "modal dialog or alert is active" in s
        or "30486" in s
    )


def clear_recovery_data():
    """Purge InDesign automatic recovery files so modal recovery prompts never block COM."""
    for base in [os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA")]:
        if not base:
            continue
        indesign_base = os.path.join(base, "Adobe", "InDesign")
        if os.path.isdir(indesign_base):
            for root, dirs, files in os.walk(indesign_base):
                if os.path.basename(root) == "InDesign Recovery":
                    for f in files:
                        try:
                            os.remove(os.path.join(root, f))
                        except Exception:
                            pass


def _set_never_interact(app):
    """Put the given InDesign Application into non-interactive scripting mode."""
    try:
        app.DoScript(
            "app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;",
            JS_LANG,
        )
    except Exception:
        pass


def connect_indesign(attempts=3):
    """Connect to a running/launchable InDesign via COM, killing a stuck instance once if needed."""
    clear_recovery_data()
    app = None
    for attempt in range(attempts):
        try:
            app = win32com.client.Dispatch('InDesign.Application')
            break
        except Exception:
            time.sleep(3)
            if attempt == 1:
                subprocess.run(["taskkill", "/F", "/IM", "InDesign.exe"], capture_output=True)
                time.sleep(3)
    if app is not None:
        _set_never_interact(app)
    return app


def restart_indesign(wait_seconds=6):
    """Force-kill InDesign, wait, then relaunch and return a fresh COM Application object."""
    print("  [restart] Killing InDesign.exe ...", flush=True)
    try:
        subprocess.run(["taskkill", "/F", "/IM", "InDesign.exe"], capture_output=True)
    except Exception:
        pass
    try:
        subprocess.run(["taskkill", "/F", "/IM", "Adobe Crash Processor.exe"], capture_output=True)
    except Exception:
        pass
    clear_recovery_data()
    time.sleep(wait_seconds)
    print("  [restart] Relaunching InDesign via COM ...", flush=True)
    for attempt in range(6):
        try:
            new_app = win32com.client.Dispatch('InDesign.Application')
            _set_never_interact(new_app)
            print("  [restart] InDesign is back.", flush=True)
            return new_app
        except Exception:
            time.sleep(5)
    raise RuntimeError("Could not restart InDesign after multiple attempts")


def prepare_image(src_path, temp_dir):
    """Resize an image when needed so it fits inside the column and height bounds."""
    if not _HAS_PIL:
        return src_path
    try:
        with Image.open(src_path) as im:
            w, h = im.size
            scale = 1.0
            if w > COL_W:
                scale = min(scale, COL_W / w)
            if h > MAX_IMG_H:
                scale = min(scale, MAX_IMG_H / h)
            if scale >= 1.0:
                return src_path
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            os.makedirs(temp_dir, exist_ok=True)
            out_path = os.path.join(temp_dir, os.path.basename(src_path))
            im2 = im.resize((new_w, new_h), Image.LANCZOS)
            if im2.mode not in ("RGB", "RGBA", "L", "CMYK"):
                im2 = im2.convert("RGB")
            im2.save(out_path, dpi=(72, 72))
            return out_path
    except Exception:
        return src_path


def source_sidebyside_pairs(source_idml):
    """Image-name pairs that share a multi-column table row in the source IDML (intended side-by-side)."""
    import zipfile as _zip
    import re as _re
    pairs = set()
    try:
        with _zip.ZipFile(source_idml) as z:
            for n in z.namelist():
                if not (n.startswith("Stories/") and n.endswith(".xml")):
                    continue
                xml = z.read(n).decode("utf-8", "replace")
                for tm in _re.finditer(r"<Table\b.*?</Table>", xml, _re.S):
                    names = []
                    for c in _re.findall(r"<Cell\b.*?</Cell>", tm.group(0), _re.S):
                        mm = _re.search(r"###Insert\s+(image\d+)", c, _re.I)
                        if mm:
                            names.append(mm.group(1).lower())
                    for i in range(len(names) - 1):
                        pairs.add(frozenset((names[i], names[i + 1])))
    except Exception:
        pass
    return pairs

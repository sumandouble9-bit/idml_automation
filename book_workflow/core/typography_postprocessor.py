import copy
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from typography_postprocessor_helpers import *
except ImportError:
    from .typography_postprocessor_helpers import *

try:
    from typography_postprocessor_styles import *
    from typography_postprocessor_stories import *
except ImportError:
    from .typography_postprocessor_styles import *
    from .typography_postprocessor_stories import *


def postprocess_idml(idml_path: Path) -> dict:
    """Post-processes an IDML package to ensure typography and footer consistency."""
    idml_path = Path(idml_path)
    if not idml_path.exists():
        return {"status": "error", "error": f"File not found: {idml_path}"}

    stats = {
        "styles_updated": 0,
        "body_paras_restored": 0,
        "footers_repaired": 0,
    }

    with tempfile.TemporaryDirectory(prefix="idml_typo_") as tmp_dir:
        tmp_dir = Path(tmp_dir)

        with zipfile.ZipFile(idml_path, "r") as z:
            z.extractall(tmp_dir)

        enforce_styles_xml(tmp_dir, stats)
        enforce_preferences(tmp_dir)

        stories_dir = tmp_dir / "Stories"
        toc_norms, toc_clean_norms = collect_toc_norms(tmp_dir)

        if stories_dir.is_dir():
            for sf in stories_dir.glob("*.xml"):
                process_story_file(sf, toc_norms, toc_clean_norms, stats)

        # -------------------------------------------------------------
        # 3. Re-pack IDML cleanly
        # -------------------------------------------------------------
        tmp_out = idml_path.with_suffix(".tmp.idml")
        with zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_DEFLATED) as z_out:
            for p in sorted(tmp_dir.rglob("*")):
                if p.is_file():
                    z_out.write(p, p.relative_to(tmp_dir).as_posix())
        tmp_out.replace(idml_path)

    try:
        from core.epub_class_format import apply_epub_classes as _aec
    except Exception:
        try:
            from epub_class_format import apply_epub_classes as _aec
        except Exception:
            _aec = None
    if _aec is not None:
        try:
            _aec(idml_path)
        except Exception:
            pass

    try:
        from core.collapse_soft_breaks import apply_collapse as _acsb
    except Exception:
        try:
            from collapse_soft_breaks import apply_collapse as _acsb
        except Exception:
            _acsb = None
    if _acsb is not None:
        try:
            _acsb(idml_path)
        except Exception:
            pass

    stats["status"] = "ok"
    return stats

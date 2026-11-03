import copy
import os
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from typography_postprocessor_es_helpers import *
except ImportError:
    from .typography_postprocessor_es_helpers import *

try:
    from typography_postprocessor_es_spreads import *
    from typography_postprocessor_es_stories import *
except ImportError:
    from .typography_postprocessor_es_spreads import *
    from .typography_postprocessor_es_stories import *


def postprocess_idml_es(idml_path: Path) -> dict:
    """Post-processes an IDML package to guarantee 100% Spanish typography uniformity."""
    idml_path = Path(idml_path)
    if not idml_path.exists():
        return {"status": "error", "error": f"File not found: {idml_path}"}

    stats = {
        "styles_updated": 0,
        "body_paras_restored": 0,
        "footers_repaired": 0,
        "runaway_sub_sup_cleaned": 0,
        "spread_frames_realigned": 0,
    }

    with tempfile.TemporaryDirectory(prefix="idml_typo_es_") as tmp_dir:
        tmp_dir = Path(tmp_dir)

        with zipfile.ZipFile(idml_path, "r") as z:
            z.extractall(tmp_dir)

        enforce_styles_xml_es(tmp_dir, stats)

        stories_dir = tmp_dir / "Stories"
        toc_norms, toc_clean_norms = collect_toc_norms_es(tmp_dir)

        if stories_dir.is_dir():
            for sf in stories_dir.glob("*.xml"):
                process_story_file_es(sf, toc_norms, toc_clean_norms, stats)

        realign_spreads_es(tmp_dir, stats)

        # -------------------------------------------------------------
        # 4. Re-pack IDML cleanly
        # -------------------------------------------------------------
        tmp_out = idml_path.with_suffix(".tmp.idml")
        with zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_DEFLATED) as zout:
            for root, dirs, files in os.walk(tmp_dir):
                for file in files:
                    full_p = Path(root) / file
                    rel_p = full_p.relative_to(tmp_dir)
                    zout.write(full_p, str(rel_p).replace("\\", "/"))

        shutil.move(str(tmp_out), str(idml_path))

    try:
        from core.center_from_epub import apply_center as _apply_center
    except Exception:
        try:
            from center_from_epub import apply_center as _apply_center
        except Exception:
            _apply_center = None
    if _apply_center is not None:
        try:
            _apply_center(idml_path)
        except Exception:
            pass

    return stats

"""
Spanish IDML pipeline entry point.

    python run_spanish_pipeline.py                 # process all Spanish books
    python run_spanish_pipeline.py 9788166131264   # process only this book
"""
import sys
from pathlib import Path

WF = Path(__file__).resolve().parent
SP_SCRIPT = WF / "Scripts" / "spanish" / "unified_pipeline_es.py"

if __name__ == "__main__":
    import runpy
    sys.argv[0] = str(SP_SCRIPT)
    runpy.run_path(str(SP_SCRIPT), run_name="__main__")

"""
bridge: InDesignRunner
Object-Oriented Windows COM Automation Bridge for Adobe InDesign.
Encapsulates application lifecycle management, automatic recovery purging,
process fault recovery, and ExtendScript JSX execution.
"""

import os
import time
import subprocess
from pathlib import Path
from typing import Any, Optional


class InDesignRunner:
    """
    Encapsulates COM automation with Adobe InDesign desktop engine.
    Ensures safe, unattended headless execution by handling modal recovery prompts,
    deadlocks, and PDF export.
    """

    INDESIGN_JS_LANG = 1246973031  # idScriptLanguage.idJavascript

    def __init__(self, version_str: str = "InDesign.Application"):
        self.app_id = version_str

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
        """Gets or restarts a clean, responsive InDesign Application COM instance."""
        import win32com.client
        self.clear_recovery_data()
        try:
            app = win32com.client.Dispatch(self.app_id)
            app.DoScript(
                "app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;",
                self.INDESIGN_JS_LANG
            )
            return app
        except Exception:
            # Terminate and restart if server execution failed or was stuck
            subprocess.run(["taskkill", "/F", "/T", "/IM", "InDesign.exe"], capture_output=True)
            subprocess.run(["taskkill", "/F", "/T", "/IM", "Adobe Crash Processor.exe"], capture_output=True)
            time.sleep(2)
            self.clear_recovery_data()
            app = win32com.client.Dispatch(self.app_id)
            app.DoScript(
                "app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;",
                self.INDESIGN_JS_LANG
            )
            return app

    def run_script(self, script_body: str) -> Any:
        """Executes raw ExtendScript code within the active InDesign instance."""
        app = self.get_app()
        return app.DoScript(script_body, self.INDESIGN_JS_LANG)

    def export_pdf(self, idml_path: str, output_pdf_path: str, logo_path: Optional[str] = None) -> bool:
        """
        Executes export.jsx with exact input and output paths to format layout and export PDF/X.
        """
        jsx_file = Path(__file__).parent / "jsx" / "export.jsx"
        if not jsx_file.exists():
            raise FileNotFoundError(f"ExtendScript layout file not found at: {jsx_file}")

        with open(jsx_file, "r", encoding="utf-8") as f:
            script_body = f.read()

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
            self.run_script(full_script)
            return target_pdf.exists()
        except Exception as e:
            print(f"[ERROR] InDesign export_pdf failed: {e}")
            return False

    def reflow_document(self, idml_path: str, output_idml_path: Optional[str] = None) -> bool:
        """
        Executes reflow.jsx to autoflow overset text into newly threaded pages.
        """
        out_idml = output_idml_path or idml_path
        jsx_file = Path(__file__).parent / "jsx" / "reflow.jsx"
        if not jsx_file.exists():
            raise FileNotFoundError(f"ExtendScript reflow file not found at: {jsx_file}")

        with open(jsx_file, "r", encoding="utf-8") as f:
            script_body = f.read()

        clean_in = str(Path(idml_path).resolve()).replace("\\", "/")
        clean_out = str(Path(out_idml).resolve()).replace("\\", "/")

        full_script = f"""
        var inputPath = "{clean_in}";
        var outputPath = "{clean_out}";
        {script_body}
        """

        try:
            self.run_script(full_script)
            return True
        except Exception as e:
            print(f"[ERROR] InDesign reflow_document failed: {e}")
            return False


# Semantic alias
InDesignBridge = InDesignRunner

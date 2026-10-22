import os
import time
import subprocess
from pathlib import Path
from typing import Optional


class InDesignRunner:
    """
    Step 6 & 8: Bridges Python pipeline with Adobe InDesign desktop engine
    using Windows COM automation to execute ExtendScript with automatic recovery
    data clearing and clean COM session management.
    """

    JS = 1246973031  # idScriptLanguage.idJavascript

    def __init__(self, version_str: str = "InDesign.Application"):
        self.app_id = version_str

    @staticmethod
    def clear_recovery_data():
        """Purge InDesign automatic recovery files so modal recovery prompts never block COM."""
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
            app.DoScript("app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;", self.JS)
            return app
        except Exception:
            # Terminate and restart if server execution failed
            subprocess.run(["taskkill", "/F", "/T", "/IM", "InDesign.exe"], capture_output=True)
            time.sleep(2)
            self.clear_recovery_data()
            app = win32com.client.Dispatch(self.app_id)
            app.DoScript("app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;", self.JS)
            return app

    def export_pdf(self, idml_path: str, output_pdf_path: str) -> bool:
        """
        Executes export.jsx with exact input and output paths to format layout and export PDF/X.
        """
        jsx_file = Path(__file__).parent / "jsx" / "export.jsx"
        with open(jsx_file, "r", encoding="utf-8") as f:
            script_body = f.read()

        # Clear any locking PDF viewer on target output
        try:
            if Path(output_pdf_path).exists():
                subprocess.run(["taskkill", "/F", "/IM", "Acrobat.exe"], capture_output=True)
                time.sleep(0.5)
                os.remove(output_pdf_path)
        except Exception:
            pass

        clean_idml = str(Path(idml_path).resolve()).replace("\\", "/")
        clean_pdf = str(Path(output_pdf_path).resolve()).replace("\\", "/")
        logo_file = Path(__file__).parent.parent / "logo" / "LEAF-BOUND-trimmed.png"
        clean_logo = str(logo_file.resolve()).replace("\\", "/")

        full_script = f"""
        var inputPath = "{clean_idml}";
        var outputPath = "{clean_pdf}";
        var logoPath = "{clean_logo}";
        {script_body}
        """

        try:
            app = self.get_app()
            app.DoScript(full_script, self.JS)
            return Path(output_pdf_path).exists()
        except Exception as e:
            print(f"[ERROR] InDesign export_pdf failed: {e}")
            return False

    def reflow_document(self, idml_path: str, output_idml_path: str = None) -> bool:
        """
        Executes reflow.jsx to autoflow overset text into newly threaded pages.
        """
        out_idml = output_idml_path or idml_path
        jsx_file = Path(__file__).parent / "jsx" / "reflow.jsx"
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
            app = self.get_app()
            app.DoScript(full_script, self.JS)
            return True
        except Exception as e:
            print(f"[ERROR] InDesign reflow_document failed: {e}")
            return False

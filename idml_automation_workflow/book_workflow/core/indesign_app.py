"""InDesignApp: one COM wrapper for every InDesign interaction.

Consolidates the connection, DoScript execution, non-interactive setup, recovery
clearing and crash/hang detection that were previously copy-pasted across the
injection and table-fit scripts. Behaviour (including the ExtendScript language
id and restart sequence) is preserved.
"""

import os
import subprocess
import time

try:
    import win32com.client
except Exception:  # pragma: no cover - import guarded so non-Windows can import the module
    win32com = None

# ExtendScript (JavaScript) language id passed to Application.DoScript.
JS_LANGUAGE = 1246973031

_RPC_MARKERS = (
    "remote procedure call",
    "rpc server",
    "-2147023170",
    "-2147023174",
    "call was rejected",
    "modal dialog or alert is active",
    "30486",
)


class InDesignApp:
    # Thin, reusable handle to a running InDesign instance driven over COM.
    def __init__(self, app=None):
        self._app = app

    @property
    def app(self):
        # The live COM Application object; connect lazily on first use.
        if self._app is None:
            self.connect()
        return self._app

    @staticmethod
    def is_rpc_error(exc):
        # True when an exception means InDesign hung, crashed or is blocked by a
        # modal alert and should be restarted before retrying.
        text = str(exc).lower()
        return any(marker in text for marker in _RPC_MARKERS)

    @staticmethod
    def clear_recovery_data():
        # Delete InDesign auto-recovery files so a recovery prompt can never block
        # COM calls on the next launch.
        for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA")):
            if not base:
                continue
            indesign_base = os.path.join(base, "Adobe", "InDesign")
            if not os.path.isdir(indesign_base):
                continue
            for root, _dirs, files in os.walk(indesign_base):
                if os.path.basename(root) == "InDesign Recovery":
                    for name in files:
                        try:
                            os.remove(os.path.join(root, name))
                        except Exception:
                            pass

    def connect(self, attempts=3):
        # Dispatch (or attach to) InDesign, retrying and force-killing a wedged
        # process between tries, then force non-interactive mode.
        if win32com is None:
            raise RuntimeError("win32com is unavailable; cannot connect to InDesign")
        self.clear_recovery_data()
        last_error = None
        for attempt in range(attempts):
            try:
                self._app = win32com.client.Dispatch("InDesign.Application")
                self.set_non_interactive()
                return self._app
            except Exception as exc:
                last_error = exc
                time.sleep(3)
                if attempt == attempts - 2:
                    subprocess.run(["taskkill", "/F", "/IM", "InDesign.exe"], capture_output=True)
                    time.sleep(3)
        raise RuntimeError(f"Could not connect to Adobe InDesign: {last_error}")

    def set_non_interactive(self):
        # Suppress every dialog/alert so unattended scripts never stall.
        try:
            self.do_script(
                "app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;"
            )
        except Exception:
            pass

    def restart(self, wait_seconds=6):
        # Force-kill InDesign and its crash processor, clear recovery data and
        # relaunch, returning the fresh Application object.
        for image in ("InDesign.exe", "Adobe Crash Processor.exe"):
            try:
                subprocess.run(["taskkill", "/F", "/IM", image], capture_output=True)
            except Exception:
                pass
        self.clear_recovery_data()
        time.sleep(wait_seconds)
        self._app = None
        for _attempt in range(6):
            try:
                return self.connect(attempts=1)
            except Exception:
                time.sleep(5)
        raise RuntimeError("Could not restart InDesign after multiple attempts")

    def do_script(self, js_source):
        # Run an ExtendScript snippet and return its result.
        return self.app.DoScript(js_source, JS_LANGUAGE)

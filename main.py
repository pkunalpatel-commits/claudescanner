import logging, os, traceback
from logging.handlers import RotatingFileHandler
from kivy.app import App
from kivy.base import ExceptionHandler, ExceptionManager
from kivy.core.window import Window

LOG = logging.getLogger("oi")


class _Handler(ExceptionHandler):
    """Log UI-event exceptions instead of letting them kill the app."""
    def handle_exception(self, inst):
        LOG.error("UI exception:\n%s", traceback.format_exc())
        return ExceptionManager.PASS


class OIApp(App):
    title = "Dhan OI Scanner"
    scanner = None

    def build(self):
        folder = self.user_data_dir; os.makedirs(folder, exist_ok=True)
        LOG.setLevel(logging.INFO)
        h = RotatingFileHandler(os.path.join(folder, "scanner.log"), maxBytes=1000000, backupCount=2)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s")); LOG.addHandler(h); LOG.addHandler(logging.StreamHandler())
        ExceptionManager.add_handler(_Handler())
        try:
            from database_manager import Database
            from dashboard import Dashboard
            from scanner_engine import Scanner
            from settings import Settings
            self.scanner = Scanner(Settings(folder), Database(folder), LOG)
            return Dashboard(self.scanner)
        except Exception:
            tb = traceback.format_exc(); LOG.error("Startup failed:\n%s", tb)
            from kivy.uix.label import Label
            from kivy.uix.scrollview import ScrollView
            lab = Label(text="STARTUP ERROR - screenshot this:\n\n" + tb, size_hint_y=None, font_size="11sp",
                        text_size=(Window.width - 20, None), halign="left", valign="top")
            lab.bind(texture_size=lambda i, s: setattr(i, "height", s[1]))
            sv = ScrollView(); sv.add_widget(lab); return sv

    def on_start(self):
        try:
            from android.permissions import request_permissions
            request_permissions(["android.permission.POST_NOTIFICATIONS"])
        except Exception: pass
        try:
            from android.runnable import run_on_ui_thread
            from jnius import autoclass

            @run_on_ui_thread
            def keep_on():
                autoclass("org.kivy.android.PythonActivity").mActivity.getWindow().addFlags(128)
            keep_on()
        except Exception: pass
        if self.scanner: self.scanner.start()

    def on_pause(self): return True
    def on_stop(self):
        if self.scanner: self.scanner.stop()


if __name__ == "__main__":
    OIApp().run()

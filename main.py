import logging, os
from logging.handlers import RotatingFileHandler
from kivy.app import App
from kivy.core.window import Window


class OIApp(App):
    title = "Dhan OI Scanner"

    def build(self):
        from database_manager import Database
        from dashboard import Dashboard
        from scanner_engine import Scanner
        from settings import Settings
        folder = self.user_data_dir; os.makedirs(folder, exist_ok=True)
        log = logging.getLogger("oi"); log.setLevel(logging.INFO)
        h = RotatingFileHandler(os.path.join(folder, "scanner.log"), maxBytes=1000000, backupCount=2)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s")); log.addHandler(h); log.addHandler(logging.StreamHandler())
        self.scanner = Scanner(Settings(folder), Database(folder), log)
        return Dashboard(self.scanner)

    def on_start(self):
        try:
            from android.permissions import request_permissions
            request_permissions(["android.permission.POST_NOTIFICATIONS"])
            from jnius import autoclass
            autoclass("org.kivy.android.PythonActivity").mActivity.getWindow().addFlags(128)  # keep screen on
        except Exception: pass
        self.scanner.start()

    def on_pause(self): return True
    def on_stop(self): self.scanner.stop()


if __name__ == "__main__":
    OIApp().run()

import sys
from pathlib import Path

# Support Python installations configured with a ``._pth`` file, where the
# directory containing this script is not automatically available to imports.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtWidgets import QApplication

from core.ui.main_window import App


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec())

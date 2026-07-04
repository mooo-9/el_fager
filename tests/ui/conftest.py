import pytest


@pytest.fixture(scope="session")
def qapp():
    # QWebEngineWidgets MUST be imported before QApplication is instantiated
    # (same side-effect import as main.py) or OverlayWindow's HUD page fails.
    from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

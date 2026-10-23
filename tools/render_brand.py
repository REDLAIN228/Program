"""Export the original SVG geometry to transparent PNG and multi-size Windows ICO."""
from pathlib import Path
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtCore import Qt
    from PIL import Image
    app = QApplication.instance() or QApplication([])
    assets = Path(__file__).resolve().parents[1]/"assets"
    for stem, size in (("redlain-icon", (512, 512)), ("redlain-monochrome", (512, 512)),
                       ("redlain-logo", (1520, 304))):
        renderer = QSvgRenderer(str(assets/(stem+".svg")))
        if not renderer.isValid(): raise RuntimeError("Invalid brand SVG")
        image = QImage(*size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        assert image.save(str(assets/(stem+".png")))
    with Image.open(assets/"redlain-icon.png") as icon:
        icon.save(assets/"redlain.ico", format="ICO", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    print("Exported transparent SVG/PNG/ICO brand assets")


if __name__ == "__main__": main()

from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from app.ui.common import Preview
from app.ui.floating import FloatingIcon


def test_priority_rectangle_uses_image_coordinates_after_zoom(qapp):
    view = Preview()
    view.resize(420, 320)
    view.show()
    view.set_image(Image.new("RGB", (200, 100), "white"))
    qapp.processEvents()
    view.zoom(1.25)
    selected = []
    view.region_selected.connect(selected.append)
    view.selection_mode = True
    a = view.mapFromScene(QPointF(60, 25))
    b = view.mapFromScene(QPointF(140, 75))
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
    QTest.mouseMove(view.viewport(), b)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
    assert len(selected) == 1
    x, y, width, height = selected[0]
    assert abs(x-.3) < .02 and abs(y-.25) < .02
    assert abs(width-.4) < .02 and abs(height-.5) < .02
    view.close()


def test_floating_widget_expands_and_dispatches_pause_stop_without_input(qapp):
    widget = FloatingIcon()
    pauses, stops = [], []
    widget.pause_requested.connect(lambda: pauses.append(True))
    widget.stop_requested.connect(lambda: stops.append(True))
    widget.show()
    qapp.processEvents()
    widget.update_status("DRAWING", .6, 75)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert widget.popup.isVisible()
    assert "60%" in widget.status_label.text() and "01:15" in widget.time_label.text()
    widget.pause_button.click()
    widget.stop_button.click()
    assert pauses == [True] and stops == [True]
    widget.hide()
    assert not widget.popup.isVisible()
    widget.close()

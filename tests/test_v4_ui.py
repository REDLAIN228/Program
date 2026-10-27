import time

from PySide6.QtWidgets import QWidget

from app.storage import Store
from app.ui.assistant import AssistantModel
from app.ui.motion import Animator, MotionSettings, WindowMotion
from app.ui.panel import MainWindow


def pump(qapp, seconds):
    until = time.monotonic()+seconds
    while time.monotonic() < until:
        qapp.processEvents()
        time.sleep(.003)


def window(tmp_path, monkeypatch):
    monkeypatch.setattr(MainWindow, "start_hotkeys", lambda self: None)
    panel = MainWindow(Store(tmp_path/"data"))
    panel.hotkeys_ready = True
    return panel


def close(panel):
    panel.close_resources()
    panel.icon.close()
    panel.hide()


def test_animator_keeps_one_animation_per_target_and_off_applies_end_state(qapp):
    saved = {}
    motion = MotionSettings({}, lambda key, value: saved.__setitem__(key, value))
    animator = Animator(motion)
    widget = QWidget()
    first = animator.animate(widget, b"windowOpacity", .2, 400)
    second = animator.animate(widget, b"windowOpacity", .9, 400)
    assert first is not second and animator.running(widget, b"windowOpacity")
    assert len(animator._running) == 1
    motion.set("level", "off")
    assert saved == {"ui_motion": "off"}
    finished = []
    assert animator.animate(widget, b"windowOpacity", .5, 400, finished=lambda: finished.append(True)) is None
    assert abs(widget.windowOpacity()-.5) < .01 and finished == [True]
    widget.deleteLater()


def test_rapid_conceal_reveal_never_leaves_a_transparent_or_hidden_window(qapp):
    motion = MotionSettings({"ui_motion": "full"})
    animator = Animator(motion)
    top = QWidget()
    top.show()
    move = WindowMotion(top, animator)
    for _ in range(20):
        move.conceal()
        move.reveal()
    pump(qapp, .5)
    assert top.isVisible() and top.windowOpacity() > .99
    move.conceal()
    pump(qapp, .4)
    assert not top.isVisible() and top.windowOpacity() == 1.
    top.show()
    move.hide_now()
    assert not top.isVisible()
    top.deleteLater()


def test_assistant_model_follows_real_states_without_phantom_progress():
    model = AssistantModel()
    assert model.app_state("PROCESSING") and model.state == "planning"
    model.app_state("DRAWING")
    model.engine_event({"type": "cursor", "index": 3, "stage": 2, "position": [.25, 1.4]}, (240, 54, 82), "03 Base Colors")
    assert model.cursor == (.25, 1.) and model.color == (240, 54, 82) and model.stage == "03 Base Colors"
    model.app_state("PAUSED")
    events = model.events
    assert model.state == "paused" and model.cursor == (.25, 1.)  # Frozen, not advanced.
    model.app_state("FINISHED")
    assert not model.app_state("IDLE") and model.state == "finished"  # Completion moment is timed by the widget.
    model.app_state("ERROR", "Холст перекрыт")
    assert model.state == "error" and model.message == "Холст перекрыт" and model.events == events


def test_run_blockers_explain_why_run_is_disabled(qapp, tmp_path, monkeypatch):
    panel = window(tmp_path, monkeypatch)
    try:
        reasons = panel.shell.run_blockers()
        assert reasons[0] == "Импортируйте изображение" and any("профиль" in r for r in reasons)
        panel.hotkeys_ready = False
        assert any("F9" in r for r in panel.shell.run_blockers())
        panel.show()
        panel.shell.refresh()
        assert not panel.run_button.isEnabled() and panel.shell.reason.text().startswith("RUN недоступен")
        assert not panel.icon.isVisible()  # No always-on-top launcher over the open panel.
    finally:
        close(panel)


def test_sections_merge_old_navigation_names(qapp, tmp_path, monkeypatch):
    panel = window(tmp_path, monkeypatch)
    try:
        for old, page in (("Live Drawing", "draw"), ("Projects", "projects"), ("Settings", "settings"),
                          ("Dashboard", "projects"), ("Workspace", "draw")):
            panel.navigate_v3(old)
            assert panel.shell.page_names[panel.shell.pages.currentIndex()] == page
        visible = [b.text() for k, b in panel.shell.nav_buttons.items() if not b.isHidden()]
        assert visible == ["Рисование", "Проекты", "Настройки"]  # Discover is an opt-in extension.
        assert not hasattr(panel, "dashboard_page")
    finally:
        close(panel)


def test_decorations_stop_during_external_input_and_hide_before_input(qapp, tmp_path, monkeypatch):
    panel = window(tmp_path, monkeypatch)
    try:
        panel.show()
        panel.activateWindow()
        pump(qapp, .2)
        shell = panel.shell
        assert shell.root.running() and shell.assistant.view.running()
        panel.set_state("DRAWING")
        assert shell.motion.external_input
        assert not shell.root.running() and not shell.assistant.view.running()
        panel.set_state("PAUSED")
        assert not shell.motion.external_input
        shell.motion.set("low_power", True)
        assert shell.root._timer.interval() == 100 and shell.assistant.view._timer.interval() == 66
        panel._ensure_hidden()
        assert not panel.isVisible()
        assert not shell.root.running()
    finally:
        close(panel)

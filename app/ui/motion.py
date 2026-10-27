"""One place for every UI animation decision.

Rules enforced here rather than at each call site:
- one running animation per (object, property); a new request takes over from
  the current value, so rapid toggles never leave a half-transparent window;
- "Минимум анимаций" shortens transitions, "Без анимаций" applies end states
  immediately, and decorative frames (background, assistant) stop while the
  engine owns external input or the window is hidden;
- no sleeps and no per-call timers: Qt animations are driven by Qt's own
  animation timer and are parented to the animated object.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, Signal

MOTION_LEVELS = ("full", "minimal", "off")
MOTION_LABELS = {"full": "Полные анимации", "minimal": "Минимум анимаций", "off": "Без анимаций"}


def system_prefers_reduced_motion() -> bool:
    """Windows "Show animations in Windows" (SPI_GETCLIENTAREAANIMATION)."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        enabled = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return not enabled.value
    except (OSError, AttributeError):
        pass
    return False


class MotionSettings(QObject):
    changed = Signal()

    def __init__(self, settings: dict, save=lambda *_: None):
        super().__init__()
        self._save = save
        default = "minimal" if system_prefers_reduced_motion() else "full"
        level = settings.get("ui_motion", default)
        self.level = level if level in MOTION_LEVELS else default
        self.background = bool(settings.get("ui_background", True))
        self.assistant = bool(settings.get("ui_assistant", True))
        self.low_power = bool(settings.get("ui_low_power", False))
        self.external_input = False  # True while the engine may send input.

    def set(self, key, value):
        if getattr(self, key) == value:
            return
        setattr(self, key, value)
        self._save({"level": "ui_motion", "background": "ui_background", "assistant": "ui_assistant",
                    "low_power": "ui_low_power"}[key], value)
        self.changed.emit()

    def set_external_input(self, active: bool):
        if self.external_input != active:
            self.external_input = active
            self.changed.emit()

    def duration(self, ms: int) -> int:
        if self.level == "off":
            return 0
        if self.level == "minimal" or self.low_power:
            return min(ms, 90)
        return ms

    @property
    def decorative(self) -> bool:
        """Continuous decorative frames are allowed right now."""
        return self.level == "full" and not self.external_input

    @property
    def frame_interval(self) -> int:
        return 66 if self.low_power else 33  # 15 or 30 fps cap.


class Animator(QObject):
    """Owns at most one animation per (target, property)."""

    def __init__(self, motion: MotionSettings, parent=None):
        super().__init__(parent)
        self.motion = motion
        self._running: dict[tuple[int, bytes], QPropertyAnimation] = {}

    def stop(self, target, prop: bytes):
        animation = self._running.pop((id(target), prop), None)
        if animation is not None:
            animation.stop()
            animation.deleteLater()

    def animate(self, target, prop: bytes, end, ms=180, *, start=None,
                easing=QEasingCurve.Type.OutCubic, finished=None):
        self.stop(target, prop)
        duration = self.motion.duration(ms)
        if duration <= 0:
            target.setProperty(prop.decode(), end)
            if finished:
                finished()
            return None
        animation = QPropertyAnimation(target, prop, target)
        animation.setDuration(duration)
        animation.setEasingCurve(easing)
        if start is not None:
            animation.setStartValue(start)
        animation.setEndValue(end)
        key = (id(target), prop)

        def done():
            if self._running.get(key) is animation:
                self._running.pop(key, None)
                animation.deleteLater()
                if finished:
                    finished()
        animation.finished.connect(done)
        self._running[key] = animation
        animation.start()
        return animation

    def running(self, target, prop: bytes) -> bool:
        return (id(target), prop) in self._running


class WindowMotion:
    """Fade a top-level window in/out without ever leaving it half-visible.

    hide_now() exists for the drawing hand-off: input safety beats animation,
    so the caller can always force the final hidden state synchronously.
    """

    def __init__(self, window, animator: Animator):
        self.window, self.animator = window, animator

    def reveal(self):
        w = self.window
        hiding = self.animator.running(w, b"windowOpacity")
        self.animator.stop(w, b"windowOpacity")
        if not w.isVisible() or hiding:
            if not w.isVisible():
                w.setWindowOpacity(0. if self.animator.motion.duration(160) else 1.)
            if w.isMinimized():
                w.showNormal()
            else:
                w.show()
        w.raise_()
        w.activateWindow()
        self.animator.animate(w, b"windowOpacity", 1., 160, start=w.windowOpacity())

    def conceal(self, then=None):
        w = self.window
        if not w.isVisible():
            self.animator.stop(w, b"windowOpacity")
            w.setWindowOpacity(1.)
            if then:
                then()
            return

        def finish():
            w.hide()
            w.setWindowOpacity(1.)
            if then:
                then()
        self.animator.animate(w, b"windowOpacity", 0., 140, start=w.windowOpacity(), finished=finish)

    def hide_now(self):
        self.animator.stop(self.window, b"windowOpacity")
        self.window.hide()
        self.window.setWindowOpacity(1.)

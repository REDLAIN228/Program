"""Numeric controls for the screenshot preset with an overlapping RGB popup."""
from app.automation import SafetyError
from app.models import Rect


class PopupController:
    def __init__(self, executor):
        self.x = executor
        self.controls = executor.profile.popup_controls
        self._known_state = None

    def _sample(self, point):
        x = self.x
        state = x._guard()
        screen = point[0]+state.client.x, point[1]+state.client.y
        if not x.backend.point_belongs_to_target(*screen):
            raise SafetyError("RGB-палитра перекрыта другим окном")
        return x.backend.sample(*screen)

    def shown(self):
        return all(max(abs(a-b) for a, b in zip(self._sample(s.point), s.rgb)) <= 22
                   for s in self.controls.visible_anchors)

    def ensure(self, opened, plan):
        current = self.shown()
        if current == opened and self._known_state == opened:
            return  # Fresh anchors confirm the unchanged state without another wait.
        for gesture in range(2):
            # Recheck before retrying: a delayed first click may already have
            # changed the state, and a blind second toggle would undo it.
            if self.shown() != opened:
                self.x._click(self.controls.toggle, plan)
            stable = 0
            for attempt in range(10):
                stable = stable+1 if self.shown() == opened else 0
                if stable == 2:
                    self._known_state = opened
                    return
                self.x._wait(max(.05, plan.timing.game_delay/2))
        self.x._control_failure("popup", opened, self.shown(),
                                "Не удалось подтвердить открытие/закрытие RGB-палитры. Штрих отменён.")

    def edit(self, point, number, plan):
        writer = getattr(self.x.backend, "replace_number", None)
        if writer is None:
            raise SafetyError("Для нового профиля нужен ввод чисел с клавиатуры Windows")
        self.x._click(point, plan)
        writer(number, self.x._guard, self.x._wait)
        self.x._wait(plan.timing.control_settle)

    def color_matches(self, rgb, plan):
        stable = 0
        for attempt in range(6):
            if not self.shown():
                raise SafetyError("RGB-палитра закрылась до проверки цвета. Штрих отменён.")
            actual = self._sample(self.controls.indicator)
            self.x._observed_color = actual
            stable = stable+1 if max(abs(a-b) for a, b in zip(actual, rgb)) <= self.x.profile.color_tolerance else 0
            if stable == 2:
                return True
            self.x._wait(max(.05, plan.timing.game_delay/2))
        return False

    def set_color(self, rgb, plan):
        self.ensure(True, plan)
        actual = self._sample(self.controls.indicator)
        if tuple(actual) != tuple(rgb):
            for attempt in range(2):
                actual = self._sample(self.controls.indicator)
                for index, (point, number) in enumerate(zip(self.controls.rgb_fields, rgb)):
                    if not self.shown():
                        raise SafetyError("RGB-палитра закрылась перед вводом. Штрих отменён.")
                    if actual[index] != number:
                        self.edit(point, number, plan)
                if self.color_matches(rgb, plan):
                    break
            else:
                self.x._control_failure("color", rgb, self.x._observed_color,
                                        "Введённый RGB не подтвердился по образцу цвета. Штрих отменён.")
        elif not self.color_matches(rgb, plan):
            self.x._control_failure("color", rgb, self.x._observed_color,
                                    "Образец RGB не стабилизировался. Штрих отменён.")
        self.ensure(False, plan)
        self.x._color = rgb

    def read_width(self, plan):
        reader = getattr(self.x.backend, "read_numeric_size", None)
        if reader is None:
            raise SafetyError("Нет чтения чёрного числа «Размер кисти» для нового профиля")
        state = self.x._guard()
        r = self.controls.brush_readout
        region = Rect(r.x+state.client.x, r.y+state.client.y, r.width, r.height)
        previous = None
        for attempt in range(10):
            self.x._guard()
            if not all(self.x.backend.point_belongs_to_target(px, py) for px, py in
                       [(region.x, region.y), (region.x+r.width-1, region.y+r.height-1)]):
                raise SafetyError("Число размера кисти перекрыто другим окном")
            actual = reader(region)
            if actual is not None and 1 <= actual <= 999 and actual == previous:
                return actual
            previous = actual
            self.x._wait(max(.1, plan.timing.game_delay/2))
        self.x._brush_failure("числовой ввод", previous, "Не удалось прочитать размер в новом интерфейсе.")

    def set_width(self, width, plan):
        self.ensure(False, plan)
        for attempt in range(3):
            actual = self.read_width(plan)
            if actual == width:
                self.x._width = width
                return
            self.edit(self.controls.brush_field, width, plan)
        actual = self.read_width(plan)
        if actual != width:
            self.x._brush_failure(width, actual, "Числовое поле не приняло размер.")
        self.x._width = width

    def prepare(self, color, width, plan):
        self.ensure(False, plan)
        changed = self.x._color != color or self.x._width != width or not self.x._tool_selected
        if self.x._color != color:
            self.set_color(color, plan)
        if changed:
            self.set_width(width, plan)
            # Digits must not leave the game in an eraser/eyedropper shortcut.
            self.x._click(self.x.profile.brush_tool, plan)
            self.x._tool_selected = True
        self.ensure(False, plan)

from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer

from app.models import Plan, Stroke, Timing
from app.ui.live_core import LiveArtCore


def test_live_core_reveals_only_completed_events_and_uses_work_weights(qapp):
    plan = Plan((100, 100), [Stroke(((.1, .2), (.9, .2)), (200, 20, 30), 3, stage=0),
                            Stroke(((.1, .8), (.2, .8)), (20, 30, 180), 3, stage=6)], Timing(), 1, "test", [])
    core = LiveArtCore()
    core.resize(450, 420)
    core.set_plan(plan)
    core.show()
    assert core.done == set() and core.fraction == 0
    core.consume(dict(type="stroke_start", index=0, stage=0, operation="fill"))
    core.consume(dict(type="cursor", index=0, stage=0, position=(.4, .2)))
    core._drain()
    assert core.done == set() and core.position == (.4, .2)
    core.consume(dict(type="stroke_complete", index=0, stage=0))
    core._drain()
    assert core.done == {0} and .5 < core.fraction < 1
    assert core.stage_done[0] == core.stage_total[0] and core.stage_done[6] == 0
    assert core.revealed.getpixel((50, 21)) == (200, 20, 30)
    assert core.revealed.getpixel((15, 79)) == (255, 255, 255)
    core.set_status("PAUSED")
    loop = QEventLoop()
    QTimer.singleShot(80, loop.quit)
    loop.exec()
    assert core.done == {0} and core.position == (.4, .2)
    core.consume(dict(type="stroke_complete", index=1, stage=6))
    core.set_status("FINISHED")
    assert core.done == {0, 1} and core.fraction == 1
    core.consume(dict(type="rewind", executed=[0]))
    core._drain()
    assert core.done == {0} and core.fraction < 1
    core.consume(dict(type="rewind", executed=[0]))
    core.consume(dict(type="stroke_complete", index=1, stage=6))
    core._drain()
    assert core.done == {0, 1} and core.status == "FINISHED"
    core.close()

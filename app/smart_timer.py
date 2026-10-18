"""Monotonic round clock, measured timing correction and time-aware plan selection."""
from dataclasses import replace
import hashlib
import json
import math
import time
from collections import defaultdict

from app.models import estimate_plan


class DrawingClock:
    def __init__(self, limit=None, now=time.monotonic):
        self.now, self.limit = now, limit
        self.started = self.now()
        self.pause_started = None
        self.pause_total = 0.

    def pause(self):
        if self.pause_started is None:
            self.pause_started = self.now()

    def resume(self):
        if self.pause_started is not None:
            self.pause_total += self.now()-self.pause_started
            self.pause_started = None

    def snapshot(self):
        elapsed = max(0., self.now()-self.started)
        paused = self.pause_total+(self.now()-self.pause_started if self.pause_started is not None else 0)
        return dict(elapsed=elapsed, active=max(0., elapsed-paused), paused=paused,
                    remaining=None if self.limit is None else max(0., self.limit-elapsed))


def performance_key(profile, timing):
    from dataclasses import asdict
    identity = dict(process=profile.target_process, adapter=profile.adapter, dpi=profile.dpi,
                    client=profile.client_size, timing=asdict(timing), input_policy=4)
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]


def learned_factor(records, key):
    values = []
    for r in records:
        if not isinstance(r, dict) or r.get("key") != key:
            continue
        actual, predicted, strokes = r.get("actual"), r.get("predicted"), r.get("strokes")
        if (all(type(v) in (int, float) and math.isfinite(v) for v in (actual, predicted, strokes))
                and predicted > .05 and actual > 0 and strokes >= 3):
            values.append(actual/predicted)
    values = [v for v in values[-20:] if math.isfinite(v) and .1 <= v <= 20]
    if not values:
        return 1., 0
    # A conservative empirical upper quartile; no claim that game latency is stable.
    ordered = sorted(values)
    return ordered[min(len(ordered)-1, math.ceil(.75*len(ordered))-1)], len(ordered)


def costs(plan):
    """Marginal estimates in the actual order, retaining control switch costs."""
    output, previous = [], None
    for stroke in plan.strokes:
        output.append(transition_cost(plan, stroke, previous))
        previous = stroke
    return output


def transition_cost(plan, stroke, previous=None):
    if previous is None:
        value = estimate_plan([stroke], plan.canvas_size, plan.timing, plan.color_clicks, plan.brush_clicks)
    else:
        pair = estimate_plan([previous, stroke], plan.canvas_size, plan.timing, plan.color_clicks, plan.brush_clicks)
        before = estimate_plan([previous], plan.canvas_size, plan.timing, plan.color_clicks, plan.brush_clicks)
        value = max(.001, pair-before)
    return value*plan.time_factor


def fit_budget(plan, limit):
    if limit is None or plan.estimated_seconds <= max(0, limit-plan.safety_buffer):
        return plan
    budget = max(0., limit-plan.safety_buffer)
    baseline = plan.strokes
    prices = costs(plan)
    # Fine contours at >=90 are protected. The earliest coarse contour of each
    # important color also anchors the silhouette before optional fill/detail work.
    essential = {i for i, s in enumerate(baseline) if s.importance >= 90 and s.priority in (0, 2)}
    colors = set()
    for i, stroke in enumerate(baseline):
        if stroke.priority == 0 and stroke.importance >= 65 and stroke.color not in colors:
            essential.add(i)
            colors.add(stroke.color)
    def estimate(indices):
        return estimate_plan([baseline[i] for i in sorted(indices)], plan.canvas_size, plan.timing,
                             plan.color_clicks, plan.brush_clicks)*plan.time_factor
    if not essential and baseline:
        essential.add(max(range(len(baseline)), key=lambda i: baseline[i].importance))
    if estimate(essential) > budget:
        plan.notes.append("Бюджет слишком мал для защищённых контуров. Увеличьте таймер или уменьшите рисунок; RUN заблокирован.")
        plan.metrics["budget_feasible"] = False
        return plan
    chosen = set(essential)
    # The main fill is more useful than a second copy of its outline. Small
    # background/repair texture loses against high-importance, long useful marks.
    fills, items = defaultdict(list), []
    for i, stroke in enumerate(baseline):
        if i in chosen:
            continue
        if stroke.priority == 1:
            fills[(stroke.color, stroke.component_id)].append(i)
        else:
            items.append([i])
    # A whole connected fill component is atomic: dropping an arbitrary inner fill contour
    # would produce a conspicuous white hole instead of a simplified background.
    items.extend(fills.values())
    def utility(item):
        benefit = sum(baseline[i].importance*(1.8 if baseline[i].priority == 1 else .8)
                      *math.sqrt(max(1., baseline[i].length(plan.canvas_size))*baseline[i].width) for i in item)
        return benefit/max(.03, sum(prices[i] for i in item))
    ranked = sorted(items, key=lambda item: -utility(item))
    # Large drawings use bounded batches rather than an O(N²) full estimate per stroke.
    reserve = budget-estimate(chosen)
    picked = []
    for item in ranked:
        price = sum(prices[i] for i in item)
        if price <= reserve:
            chosen.update(item)
            picked.append(item)
            reserve -= price
    # Removing paint can add switches: verify the resulting ordered plan, then
    # drop the least useful optional marks until the real estimator fits.
    optional = sorted(picked, key=utility)
    actual = estimate(chosen)
    while actual > budget and optional:
        batch = max(1, math.ceil(len(optional)*.05))
        for item in optional[:batch]:
            chosen.difference_update(item)
        del optional[:batch]
        actual = estimate(chosen)
    omitted_fills = {key for key, indices in fills.items() if not any(i in chosen for i in indices)}
    # Keep an omitted region as coherent line art, rather than sprinkling its
    # low-priority repair pixels over an otherwise unfilled component.
    if omitted_fills:
        omitted_colors = {key[0] for key in omitted_fills}
        chosen = {i for i in chosen if i in essential or not
                  (baseline[i].priority == 3 and baseline[i].color in omitted_colors and baseline[i].importance < 85)}
        actual = estimate(chosen)
    result = replace(plan, strokes=[s for i, s in enumerate(baseline) if i in chosen],
                     estimated_seconds=actual, notes=list(plan.notes), metrics=dict(plan.metrics))
    result.metrics.update(budget_feasible=actual <= budget, dropped_strokes=len(baseline)-len(chosen),
                          protected_strokes=len(essential), selected_strokes=len(chosen))
    result.notes.append(f"Smart Timer: оставлено {len(chosen)}/{len(baseline)} штрихов; "
                        f"защищённых контуров {len(essential)}. Фон и второстепенные детали упрощены. "
                        "Покрытие после сокращения намеренно неполное; проверьте DRAW PREVIEW.")
    return result

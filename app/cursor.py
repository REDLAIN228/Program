"""Mouse-up travel around excluded interface rectangles."""
import heapq
import math

from app.models import Rect


def _crosses(a, b, rect):
    low, high = 0., 1.
    for origin, delta, start, end in [
        (a[0], b[0]-a[0], rect.x, rect.x+rect.width-1),
        (a[1], b[1]-a[1], rect.y, rect.y+rect.height-1),
    ]:
        if delta == 0:
            if not start <= origin <= end:
                return False
        else:
            entry, leave = sorted(((start-origin)/delta, (end-origin)/delta))
            low, high = max(low, entry), min(high, leave)
            if low > high:
                return False
    return True


def travel_path(start, end, bounds: Rect, excluded: list[Rect]):
    """Return waypoints, including the destination, inside the client area."""
    def valid(point):
        return bounds.contains(*point) and not any(r.contains(*point) for r in excluded)

    if not valid(start) or not valid(end):
        raise ValueError("Переход курсора начинается или заканчивается в исключённой области")
    nodes = [start, end]
    for r in excluded:
        nodes.extend(p for p in [(r.x-2, r.y-2), (r.x+r.width+1, r.y-2),
                                  (r.x-2, r.y+r.height+1), (r.x+r.width+1, r.y+r.height+1)]
                     if valid(p))
    queue = [(0., 0, [])]
    visited = set()
    while queue:
        distance, index, path = heapq.heappop(queue)
        if index in visited:
            continue
        if index == 1:
            return [nodes[i] for i in path]
        visited.add(index)
        for other, point in enumerate(nodes):
            if other not in visited and not any(_crosses(nodes[index], point, r) for r in excluded):
                heapq.heappush(queue, (distance+math.dist(nodes[index], point), other, path+[other]))
    raise ValueError("Нет перехода курсора в обход исключённых областей")

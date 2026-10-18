"""The physical-pixel brush model shared by coverage checks and previews."""
from app.models import Rect
from PIL import Image, ImageDraw


def pixel_points(stroke, canvas_size, output_size):
    w, h = canvas_size
    rect = Rect(0, 0, w, h)
    physical = [rect.map(p, stroke.width/2+1) for p in stroke.points]
    return [(round(x*output_size[0]/w), round(y*output_size[1]/h)) for x, y in physical]


def draw_stroke(draw, stroke, canvas_size, output_size, fill):
    points = pixel_points(stroke, canvas_size, output_size)
    width = max(1, round(stroke.width*min(output_size[0]/canvas_size[0], output_size[1]/canvas_size[1])))
    _stamp(draw, points, width, fill)


def _stamp(draw, points, width, fill):
    if len(points) > 1:
        draw.line(points, fill=fill, width=width, joint="curve")
    # A one-pixel brush must stamp one pixel. N/2 incorrectly stamps a 2x2 square
    # for N=1 and causes the coverage calculation to skip neighboring pixels.
    radius = (width-1)/2
    for x, y in points:
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=fill)


def composite_stroke(image, stroke, canvas_size, output_size):
    if stroke.opacity == 1:
        draw_stroke(ImageDraw.Draw(image), stroke, canvas_size, output_size, stroke.color)
        return
    points = pixel_points(stroke, canvas_size, output_size)
    width = max(1, round(stroke.width*min(output_size[0]/canvas_size[0], output_size[1]/canvas_size[1])))
    pad = width//2+2
    x0, y0 = max(0, min(x for x, _ in points)-pad), max(0, min(y for _, y in points)-pad)
    x1 = min(image.width, max(x for x, _ in points)+pad+1)
    y1 = min(image.height, max(y for _, y in points)+pad+1)
    mask = Image.new("L", (x1-x0, y1-y0))
    _stamp(ImageDraw.Draw(mask), [(x-x0, y-y0) for x, y in points], width, round(255*stroke.opacity))
    image.paste(stroke.color, (x0, y0, x1, y1), mask)

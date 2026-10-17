"""The physical-pixel brush model shared by coverage checks and previews."""
from app.models import Rect


def pixel_points(stroke, canvas_size, output_size):
    w, h = canvas_size
    rect = Rect(0, 0, w, h)
    physical = [rect.map(p, stroke.width/2+1) for p in stroke.points]
    return [(round(x*output_size[0]/w), round(y*output_size[1]/h)) for x, y in physical]


def draw_stroke(draw, stroke, canvas_size, output_size, fill):
    points = pixel_points(stroke, canvas_size, output_size)
    width = max(1, round(stroke.width*min(output_size[0]/canvas_size[0], output_size[1]/canvas_size[1])))
    if len(points) > 1:
        draw.line(points, fill=fill, width=width, joint="curve")
    # A one-pixel brush must stamp one pixel. N/2 incorrectly stamps a 2x2 square
    # for N=1 and causes the coverage calculation to skip neighboring pixels.
    radius = (width-1)/2
    for x, y in points:
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=fill)

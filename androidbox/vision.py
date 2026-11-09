"""Looking at the screen without any image library: a small grid of colours is enough to tell whether an area
looks the way it did when a macro step was made, and whether the screen has stopped changing."""
import base64

GRID = 16
STILL_GRID = 24
WHOLE_SCREEN = (0.0, 0.0, 1.0, 1.0)
TOLERANCES = ((0.04, "Strict"), (0.08, "Normal"), (0.16, "Loose"))


def depth_of(frame, width, height):
    return max(len(frame) // max(width * height, 1), 1)


def sample(frame, width, height, region=WHOLE_SCREEN, grid=GRID):
    """grid x grid average colours across a region of the frame, as bytes. The region is fractions of the
    screen (left, top, width, height), so it still means the same place if the frame is a different size"""
    depth = depth_of(frame, width, height)
    left, top, span_x, span_y = region
    colours = bytearray()
    for row in range(grid):
        for column in range(grid):
            totals = [0, 0, 0]
            # Four points per cell so a single flickering pixel doesn't decide the result
            for dy in (0.25, 0.75):
                for dx in (0.25, 0.75):
                    x = min(width - 1, max(0, int((left + (column + dx) / grid * span_x) * width)))
                    y = min(height - 1, max(0, int((top + (row + dy) / grid * span_y) * height)))
                    at = (y * width + x) * depth
                    for channel in range(3):
                        totals[channel] += frame[at + channel]
            colours.extend(total // 4 for total in totals)
    return bytes(colours)


def difference(first, second):
    """0 for identical samples up to 1 for black against white"""
    if not first or len(first) != len(second):
        return 1.0
    return sum(abs(a - b) for a, b in zip(first, second)) / (255 * len(first))


def encode(samples):
    return base64.b64encode(samples).decode()


def decode(text):
    return base64.b64decode(text)


def clean_region(region):
    left, top, span_x, span_y = (float(value) for value in region)
    left, top = min(max(left, 0.0), 1.0), min(max(top, 0.0), 1.0)
    return [round(left, 4), round(top, 4), round(min(max(span_x, 0.01), 1.0 - left), 4),
            round(min(max(span_y, 0.01), 1.0 - top), 4)]

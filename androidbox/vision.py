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


FIND_WIDTH = 320
MAX_PICTURE = 96
PICTURE_POINTS = 150
COARSE_SLACK = 0.2


def crop(frame, width, height, region):
    """The pixels of a region of the frame as (bytes, width, height), 3 bytes a pixel"""
    depth = depth_of(frame, width, height)
    left, top, span_x, span_y = region
    x0, y0 = int(left * width), int(top * height)
    x1, y1 = min(width, max(x0 + 1, int((left + span_x) * width))), min(height, max(y0 + 1, int((top + span_y) * height)))
    pixels = bytearray()
    for y in range(y0, y1):
        start, end = (y * width + x0) * depth, (y * width + x1) * depth
        if depth == 3:
            # Already three bytes a pixel, so a whole row comes across at once
            pixels += frame[start:end]
        else:
            for at in range(start, end, depth):
                pixels += frame[at:at + 3]
    return bytes(pixels), x1 - x0, y1 - y0


def flat(pixels, spread=30):
    """True if the pixels are nearly one colour, which would match almost anywhere"""
    return all(max(pixels[channel::3]) - min(pixels[channel::3]) < spread for channel in range(3))


def find(frame, width, height, picture, tolerance):
    """Where a small picture (bytes, width, height) shows up in the frame. Returns (x, y, difference) for its
    top left corner, or None when nothing is within the tolerance. It compares a spread of points from the
    picture and gives up on a position as soon as it is clearly wrong, which keeps it quick without any
    image library"""
    pixels, across, down = picture
    if across > width or down > height or not pixels:
        return None
    depth = depth_of(frame, width, height)
    step = max(1, int(((across * down) / PICTURE_POINTS) ** 0.5))
    points = [(dx, dy, pixels[(dy * across + dx) * 3], pixels[(dy * across + dx) * 3 + 1],
               pixels[(dy * across + dx) * 3 + 2])
              for dy in range(step // 2, down, step) for dx in range(step // 2, across, step)]
    total = 255 * 3 * len(points)
    # The points furthest from the picture's average colour go first: a wrong position is usually clear from a
    # few of them, so it is given up on sooner. The sum is the same whatever the order
    average = [sum(point[channel] for point in points) / len(points) for channel in (2, 3, 4)]
    points.sort(key=lambda point: -sum(abs(point[2 + channel] - average[channel]) for channel in range(3)))
    # Where each point sits relative to the position being tried, worked out once instead of at every position
    shifted = [((dy * width + dx) * depth, red, green, blue) for dx, dy, red, green, blue in points]

    def cost(x, y, limit):
        base = (y * width + x) * depth
        spent = 0
        for offset, red, green, blue in shifted:
            at = base + offset
            spent += abs(frame[at] - red) + abs(frame[at + 1] - green) + abs(frame[at + 2] - blue)
            if spent > limit:
                return None
        return spent

    # Every second position first, allowing for being a pixel out, then the pixels around the best of those
    best, found = min(1.0, tolerance + COARSE_SLACK) * total, None
    for y in range(0, height - down + 1, 2):
        for x in range(0, width - across + 1, 2):
            spent = cost(x, y, best)
            if spent is not None:
                best, found = spent, (x, y)
    if not found:
        return None
    for y in range(max(0, found[1] - 1), min(height - down, found[1] + 1) + 1):
        for x in range(max(0, found[0] - 1), min(width - across, found[0] + 1) + 1):
            spent = cost(x, y, best)
            if spent is not None:
                best, found = spent, (x, y)
    return (found[0], found[1], best / total) if best / total <= tolerance else None


def clean_region(region):
    left, top, span_x, span_y = (float(value) for value in region)
    left, top = min(max(left, 0.0), 1.0), min(max(top, 0.0), 1.0)
    return [round(left, 4), round(top, 4), round(min(max(span_x, 0.01), 1.0 - left), 4),
            round(min(max(span_y, 0.01), 1.0 - top), 4)]

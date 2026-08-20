"""Generate the app icon (icon.ico + icon.png) with Pillow.

Run from the project folder:
    python make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent

S = 1024  # supersampled size
W, H = S, S
BG = (30, 33, 38, 255)
BORDER = (52, 56, 63, 255)
ORANGE = (245, 166, 35, 255)
PEAK_LINE = (255, 255, 255, 200)

# Bar heights as fractions of the maximum span (audio waveform look).
BARS = [0.32, 0.55, 0.78, 0.62, 0.9, 0.5, 0.7, 0.42, 0.28]

img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

margin = 60
radius = 180
d.rounded_rectangle(
    [margin, margin, W - margin, H - margin],
    radius=radius, fill=BG, outline=BORDER, width=12,
)

cx = W / 2
cy = H / 2
span = 420  # max half-height of a bar
bar_w = 62
gap = 26
total = len(BARS) * bar_w + (len(BARS) - 1) * gap
x0 = (W - total) / 2 + bar_w / 2

for i, h in enumerate(BARS):
    x = x0 + i * (bar_w + gap)
    half = span * h
    d.rounded_rectangle(
        [x - bar_w / 2, cy - half, x + bar_w / 2, cy + half],
        radius=bar_w / 2, fill=ORANGE,
    )

# Target peak line at the top of the tallest bar.
top = cy - span * max(BARS)
d.line([margin + 30, top, W - margin - 30, top], fill=PEAK_LINE, width=14)
d.ellipse([W - margin - 30 - 40, top - 40, W - margin - 30 + 8, top + 8], fill=ORANGE)

small = img.resize((512, 512), Image.LANCZOS)
sizes = [16, 24, 32, 48, 64, 128, 256]
small.save(ROOT / "icon.ico", sizes=[(s, s) for s in sizes])
small.save(ROOT / "icon.png")
print("icon.ico + icon.png generated")
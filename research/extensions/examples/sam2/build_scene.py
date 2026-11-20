"""Synthetic segmentation wiring fixture; not an accuracy benchmark."""
from pathlib import Path
from PIL import Image, ImageDraw

target = Path("scene.png")
if target.exists():
    raise SystemExit("scene.png already exists; refusing to overwrite an image")
image = Image.new("RGB", (256, 256), "#efe9dc")
draw = ImageDraw.Draw(image)
draw.rectangle((48, 48, 144, 144), fill="#be422d", outline="#703c2c", width=4)
draw.ellipse((160, 164, 226, 230), fill="#3b6596", outline="#253a53", width=3)
image.save(target)
print("Created synthetic scene for integration checks.")

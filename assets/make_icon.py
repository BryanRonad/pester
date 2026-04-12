"""Generate tray/build icon assets."""
from PIL import Image, ImageDraw
import os

def make_icon(path, size=64):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Orange circle background
    draw.ellipse([2, 2, size-2, size-2], fill=(255, 140, 0, 255))
    # White exclamation mark body
    cx = size // 2
    draw.rectangle([cx-5, 12, cx+5, 38], fill=(255, 255, 255, 255))
    # White dot
    draw.ellipse([cx-5, 44, cx+5, 54], fill=(255, 255, 255, 255))
    img.save(path)
    print(f"Saved {path}")

if __name__ == "__main__":
    assets_dir = os.path.dirname(os.path.abspath(__file__))
    png_path = os.path.join(assets_dir, "icon.png")
    ico_path = os.path.join(assets_dir, "icon.ico")
    make_icon(png_path)
    Image.open(png_path).save(ico_path, format="ICO", sizes=[(64, 64), (32, 32), (16, 16)])
    print(f"Saved {ico_path}")

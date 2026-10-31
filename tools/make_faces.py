"""Turn portrait photos into face textures for the meeting room characters.

    python tools/make_faces.py photo1.jpg photo2.jpg ...      (or a folder)

Works best with front-facing, centred portraits (like "this person does not
exist" images). Writes meetingroom/static/faces/face_<n>.png (small, slightly
pixelated) plus faces.json with skin/hair colours sampled from each photo.
Mark long hair afterwards in faces.json ("long": true) if you like.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "meetingroom" / "static" / "faces"
CROP = (0.19, 0.06, 0.81, 0.92)     # left, top, right, bottom (fractions) -> crown to chin
TEX = (20, 28)                      # texture size: very low, to match the pixelated room


def median_color(im, box):
    w, h = im.size
    reg = im.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h))).convert("RGB")
    px = sorted(list(reg.getdata()) if not hasattr(reg, "get_flattened_data") else list(reg.get_flattened_data()), key=lambda p: sum(p))
    r, g, b = px[len(px) // 2]
    return "#%02x%02x%02x" % (r, g, b)


def main(args):
    files = []
    for a in args:
        p = Path(a)
        files += sorted(x for x in p.iterdir() if x.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")) if p.is_dir() else [p]
    if not files:
        sys.exit(__doc__)
    OUT.mkdir(parents=True, exist_ok=True)
    meta = []
    for i, f in enumerate(files, 1):
        im = Image.open(f).convert("RGB")
        w, h = im.size
        face = im.crop((int(CROP[0] * w), int(CROP[1] * h), int(CROP[2] * w), int(CROP[3] * h)))
        face = face.filter(ImageFilter.GaussianBlur(radius=w / 900)).resize(TEX, Image.LANCZOS)
        face.save(OUT / f"face_{i}.png", optimize=True)
        meta.append({
            "file": f"face_{i}.png", "source": f.name,
            "skin": median_color(im, (0.33, 0.55, 0.42, 0.63)),     # left cheek
            "hair": median_color(im, (0.43, 0.11, 0.57, 0.16)),     # top of the head (above the forehead)
            "long": False,
        })
        print(f"face_{i}.png  <- {f.name}  skin {meta[-1]['skin']}  hair {meta[-1]['hair']}")
    (OUT / "faces.json").write_text(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])

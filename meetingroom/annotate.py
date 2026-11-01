"""Marks on the shared screen: you point at part of what an agent is showing and
the agent receives a compact, token-cheap description of exactly that part.

Text stays text: a selection in a document, a line range in code, or the text a
box covers in a PDF is sent verbatim with its location. Only genuinely visual
regions (an area of a plot) become a small cropped PNG the agent may open.
"""
from __future__ import annotations

import re
import threading
import uuid
from pathlib import Path

MAX_TEXT = 1500          # characters of quoted text sent to the agent
CROP_MAX = 640           # longest side of a region crop, in pixels
PDF_SCALE = 3.0          # page render scale for the browser (1.0 = 72 dpi); 3.0 stays sharp on retina screens

# PDFium is not thread-safe, and the server calls us from asyncio.to_thread's
# pool: two pdfium calls at once (e.g. page renders racing a mark) segfault.
_PDF_LOCK = threading.RLock()


def _pdfium():
    try:
        import pypdfium2 as pdfium
        return pdfium
    except ImportError:
        return None


def pdf_available() -> bool:
    return _pdfium() is not None


def pdf_info(path: Path) -> dict:
    with _PDF_LOCK:
        return _pdf_info(path)


def _pdf_info(path: Path) -> dict:
    pdfium = _pdfium()
    if not pdfium:
        return {"pages": 0}
    doc = pdfium.PdfDocument(str(path))
    try:
        return {"pages": len(doc), "sizes": [list(doc[i].get_size()) for i in range(len(doc))]}
    finally:
        doc.close()


def pdf_page_png(path: Path, page: int, cache: Path) -> Path:
    """Render one page (0-based) to a cached PNG."""
    out = cache / f"{path.stem}.p{page}@{PDF_SCALE:g}.png"
    if out.exists():
        return out
    with _PDF_LOCK:
        return _pdf_page_png(path, page, out, cache)


def _pdf_page_png(path: Path, page: int, out: Path, cache: Path) -> Path:
    if out.exists():
        return out
    pdfium = _pdfium()
    doc = pdfium.PdfDocument(str(path))
    try:
        cache.mkdir(parents=True, exist_ok=True)
        doc[page].render(scale=PDF_SCALE).to_pil().save(out)
    finally:
        doc.close()
    return out


def _clip_text(t: str) -> str:
    t = re.sub(r"[ \t]+", " ", t.replace("\r", "")).strip()
    return t if len(t) <= MAX_TEXT else t[:MAX_TEXT] + " …"


def _box(b) -> list[float] | None:
    try:
        x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in b)
    except (TypeError, ValueError):
        return None
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def _crop(img, box, dest: Path) -> Path:
    W, H = img.size
    pad = 0.02
    l, t = max(0, int((box[0] - pad) * W)), max(0, int((box[1] - pad) * H))
    r, b = min(W, int((box[2] + pad) * W) + 1), min(H, int((box[3] + pad) * H) + 1)
    c = img.crop((l, t, max(r, l + 2), max(b, t + 2)))
    c.thumbnail((CROP_MAX, CROP_MAX))
    dest.parent.mkdir(parents=True, exist_ok=True)
    c.convert("RGB").save(dest)
    return dest


def build_anchor(item: dict, path: Path, req: dict, out_dir: Path) -> dict:
    """Turn a browser mark into an anchor. `req` carries what the page could see:
    mode ('text' | 'box'), box (normalised 0..1, top-left origin), page (0-based),
    text (selection), lines ([first, last], 1-based), scroll (for HTML)."""
    aid = uuid.uuid4().hex[:8]
    a = {"id": aid, "item": item["id"], "title": item["title"], "name": item["name"], "kind": item["kind"],
         "owner": item["agent"], "source": item.get("source") or str(path), "mode": req.get("mode", "box")}
    box = _box(req.get("box")) if req.get("box") is not None else None
    if box:
        a["box"] = box
    if req.get("page") is not None:
        a["page"] = int(req["page"])
    if isinstance(req.get("lines"), list) and len(req["lines"]) == 2:
        a["lines"] = [int(req["lines"][0]), int(req["lines"][1])]
    text = _clip_text(str(req.get("text") or ""))

    if item["kind"] == "pdf" and box and not text:
        pdfium = _pdfium()
        if pdfium:
            with _PDF_LOCK:
                doc = pdfium.PdfDocument(str(path))
                try:
                    pg = doc[a.get("page", 0)]
                    W, H = pg.get_size()
                    text = _clip_text(pg.get_textpage().get_text_bounded(
                        left=box[0] * W, right=box[2] * W, top=(1 - box[1]) * H, bottom=(1 - box[3]) * H))
                    if len(text) < 40:   # a figure (maybe with a few tick labels): send pixels too
                        from PIL import Image  # noqa: F401  (pdfium's to_pil needs Pillow)
                        img = pg.render(scale=2).to_pil()
                        a["crop"] = str(_crop(img, box, out_dir / f"{aid}.png"))
                finally:
                    doc.close()
    elif item["kind"] == "image" and box and path.suffix.lower() != ".svg":
        try:
            from PIL import Image
            with Image.open(path) as img:
                a["crop"] = str(_crop(img, box, out_dir / f"{aid}.png"))
        except Exception as e:   # unreadable image: coordinates still help
            a["note"] = f"no crop ({type(e).__name__})"
    if text:
        a["text"] = text
    return a


def describe(a: dict) -> str:
    """One compact block for the agent's prompt."""
    where = [f"\"{a['title']}\"" + (f" ({a['name']})" if a['name'] != a['title'] else ""), f"shared by {a['owner']}"]
    if a.get("page") is not None:
        where.append(f"page {a['page'] + 1}")
    if a.get("lines"):
        l0, l1 = a["lines"]
        where.append(f"line {l0}" if l0 == l1 else f"lines {l0}-{l1}")
    if a.get("box") and not a.get("text"):
        x0, y0, x1, y1 = a["box"]
        where.append(f"region x {x0:.0%}-{x1:.0%}, y {y0:.0%}-{y1:.0%} from top-left")
    s = "  ↳ points at " + ", ".join(where) + f"; file: {a['source']}"
    if a.get("text"):
        s += "\n    marked text: «" + a["text"].replace("\n", " ⏎ ") + "»"
    if a.get("crop"):
        s += f"\n    marked region image: {a['crop']} (small crop; open it only if you need to see it)"
    return s

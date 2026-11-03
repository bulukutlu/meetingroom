"""Dependency-free, passive HTML previews of Office Open XML files.

These are content previews, not layout-faithful Office renderers. Nothing in a
document is executed, and external relationships are never fetched.
"""
from __future__ import annotations

import base64
from html import escape
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
MAX_UNPACKED = 64 * 1024 * 1024
MAX_CELLS = 100_000


def _xml(z: ZipFile, name: str):
    data = z.read(name)
    # OOXML has no need for entities or DTDs (including UTF-16 XML).
    scan = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in scan or b"<!ENTITY" in scan:
        raise ValueError("XML entities are not supported")
    return ET.fromstring(data)


def _rels(z: ZipFile, part: str) -> dict[str, str]:
    parent, name = posixpath.split(part)
    relfile = posixpath.join(parent, "_rels", name + ".rels")
    if relfile not in z.namelist():
        return {}
    return {r.get("Id"): posixpath.normpath(posixpath.join(parent, r.get("Target", "").lstrip("/")))
            if not r.get("Target", "").startswith("/") else r.get("Target").lstrip("/")
            for r in _xml(z, relfile) if r.get("TargetMode") != "External"}


def _images(z: ZipFile, node, rels: dict) -> str:
    out = []
    for blip in node.findall(".//a:blip", NS):
        path = rels.get(blip.get("{" + NS["r"] + "}embed"), "")
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}.get(Path(path).suffix.lower())
        if mime and path in z.namelist():
            encoded = base64.b64encode(z.read(path)).decode("ascii")
            out.append(f'<img alt="Embedded image" src="data:{mime};base64,{encoded}">')
    return "".join(out)


def _word(z: ZipFile) -> str:
    root = _xml(z, "word/document.xml")
    rels = _rels(z, "word/document.xml")

    def paragraph(node):
        parts = []
        for run in node.findall(".//w:r", NS):
            text = "".join(escape(n.text or "") if n.tag == "{" + NS["w"] + "}t" else
                           "<br>" if n.tag in {"{" + NS["w"] + "}br", "{" + NS["w"] + "}cr"} else
                           "&emsp;" if n.tag == "{" + NS["w"] + "}tab" else "" for n in run.iter())
            if run.find("w:rPr/w:b", NS) is not None:
                text = "<strong>" + text + "</strong>"
            if run.find("w:rPr/w:i", NS) is not None:
                text = "<em>" + text + "</em>"
            parts.append(text + _images(z, run, rels))
        style = node.find("w:pPr/w:pStyle", NS)
        match = re.fullmatch(r"Heading([1-6])", style.get("{" + NS["w"] + "}val", ""), re.I) if style is not None else None
        tag = "h" + match[1] if match else "p"
        return f"<{tag}>" + "".join(parts) + f"</{tag}>"

    def blocks(node):
        out = []
        for child in node:
            if child.tag == "{" + NS["w"] + "}p":
                out.append(paragraph(child))
            elif child.tag == "{" + NS["w"] + "}tbl":
                out.append("<table>" + "".join("<tr>" + "".join("<td>" + blocks(cell) + "</td>" for cell in row.findall("w:tc", NS)) + "</tr>" for row in child.findall("w:tr", NS)) + "</table>")
        return "".join(out)

    body = root.find("w:body", NS)
    if body is None:
        raise ValueError("Document has no body")
    return blocks(body)


def _column(ref: str) -> int:
    m = re.match(r"[A-Z]+", ref.upper())
    n = 0
    for c in m[0] if m else "A":
        n = n * 26 + ord(c) - 64
    return n


def _letters(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _excel(z: ZipFile) -> str:
    root = _xml(z, "xl/workbook.xml")
    rels = _rels(z, "xl/workbook.xml")
    strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        strings = ["".join(n.text or "" for n in si.findall(".//s:t", NS)) for si in _xml(z, "xl/sharedStrings.xml")]
    out, count = [], 0
    for sheet in root.findall("s:sheets/s:sheet", NS):
        path = rels.get(sheet.get("{" + NS["r"] + "}id"))
        if not path or path not in z.namelist():
            continue
        rows = []
        width = 1
        for row in _xml(z, path).findall("s:sheetData/s:row", NS):
            values = {}
            for cell in row.findall("s:c", NS):
                count += 1
                if count > MAX_CELLS:
                    raise ValueError("Workbook exceeds the 100,000-cell preview limit")
                col = _column(cell.get("r", _letters(len(values) + 1)))
                if col > 256:
                    raise ValueError("Workbook exceeds the 256-column preview limit")
                value = cell.findtext("s:v", "", NS)
                typ = cell.get("t")
                if typ == "s":
                    value = strings[int(value)] if value else ""
                elif typ == "inlineStr":
                    value = "".join(n.text or "" for n in cell.findall(".//s:t", NS))
                elif typ == "b":
                    value = "TRUE" if value == "1" else "FALSE"
                formula = cell.findtext("s:f", "", NS)
                if formula and not value:
                    value = "=" + formula
                values[col] = escape(value)
                width = max(width, col)
            rows.append((row.get("r", str(len(rows) + 1)), values))
            if len(rows) > 10000:
                raise ValueError("Workbook exceeds the 10,000-row preview limit")
        out.append("<section><h2>" + escape(sheet.get("name", "Sheet")) + "</h2><div class=sheet><table><thead><tr><th></th>" +
                   "".join("<th>" + _letters(i) + "</th>" for i in range(1, width + 1)) + "</tr></thead><tbody>")
        if len(rows) * width > MAX_CELLS:
            raise ValueError("Workbook preview is too wide to display safely")
        for number, cells in rows:
            out.append("<tr><th>" + escape(number) + "</th>" + "".join("<td>" + cells.get(i, "") + "</td>" for i in range(1, width + 1)) + "</tr>")
        out.append("</tbody></table></div></section>")
    return "".join(out)


def _slides(z: ZipFile) -> str:
    root = _xml(z, "ppt/presentation.xml")
    rels = _rels(z, "ppt/presentation.xml")
    out = []
    for i, slide in enumerate(root.findall("p:sldIdLst/p:sldId", NS), 1):
        path = rels.get(slide.get("{" + NS["r"] + "}id"))
        if not path or path not in z.namelist():
            continue
        doc = _xml(z, path)
        out.append(f'<section class="slide"><h2>Slide {i}</h2>')
        tree = doc.find("p:cSld/p:spTree", NS)
        if tree is not None:
            for shape in tree:
                table = shape.find(".//a:tbl", NS)
                if table is not None:
                    out.append("<table>" + "".join("<tr>" + "".join("<td>" + "<br>".join(escape("".join(t.text or "" for t in p.findall(".//a:t", NS))) for p in c.findall(".//a:p", NS)) + "</td>" for c in row.findall("a:tc", NS)) + "</tr>" for row in table.findall("a:tr", NS)) + "</table>")
                else:
                    out.extend("<p>" + escape("".join(t.text or "" for t in p.findall(".//a:t", NS))) + "</p>" for p in shape.findall(".//a:p", NS))
                out.append(_images(z, shape, _rels(z, path)))
        out.append("</section>")
    return "".join(out)


def preview(path: Path) -> str:
    """Render visible document content; reject malformed or oversized packages."""
    try:
        with ZipFile(path) as z:
            if len(z.infolist()) > 10000 or sum(i.file_size for i in z.infolist()) > MAX_UNPACKED:
                raise ValueError("Document exceeds the 64 MB preview limit")
            render = {".docx": _word, ".xlsx": _excel, ".pptx": _slides}.get(path.suffix.lower())
            if render is None:
                raise ValueError("Unsupported Office format")
            body = render(z)
    except (BadZipFile, ET.ParseError, KeyError, IndexError, TypeError) as exc:
        raise ValueError("Invalid or unsupported Office document") from exc
    return """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font:16px/1.5 system-ui,sans-serif;color:#202124;background:#fff;margin:0;padding:24px}main{max-width:1100px;margin:auto}h1{font-size:22px}p{white-space:pre-wrap}aside{background:#f1f3f5;padding:10px 14px;font-size:13px;color:#555}table{border-collapse:collapse;margin:12px 0}th,td{border:1px solid #ccd1d6;padding:6px 10px;text-align:left;vertical-align:top;white-space:pre-wrap}th{background:#edf0f4;position:sticky;top:0}img{max-width:100%;max-height:650px;object-fit:contain}.sheet{overflow:auto;max-height:75vh}.slide{padding:24px;margin:24px 0;border:1px solid #ccd1d6;box-shadow:0 2px 8px #ddd}section{margin:24px 0}</style>
</head><body><main><h1>""" + escape(path.name) + "</h1><aside>Content preview: text, tables and embedded images. Layout, charts and animations may differ. Spreadsheet formulas show saved values; number and date formatting is not applied.</aside>" + (body or "<p>No previewable content.</p>") + "</main></body></html>"

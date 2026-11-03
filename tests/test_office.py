import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient

from meetingroom import office
from meetingroom.location import Location
from meetingroom.server import Room, create_hub, kind_of


class OfficeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def package(self, name, parts):
        path = self.root / name
        with ZipFile(path, "w") as z:
            for member, text in parts.items():
                z.writestr(member, text)
        return path

    def word(self):
        return self.package("sample.docx", {"word/document.xml": f'''<w:document xmlns:w="{office.NS['w']}"><w:body>
        <w:p><w:r><w:rPr><w:b/></w:rPr><w:t>&lt;script&gt;hello&lt;/script&gt;</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Table cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
        </w:body></w:document>'''})

    def test_word_and_escaping(self):
        html = office.preview(self.word())
        self.assertIn("<strong>&lt;script&gt;hello&lt;/script&gt;</strong>", html)
        self.assertIn("<td><p>Table cell</p></td>", html)
        self.assertNotIn("<script>", html)
        self.assertEqual(kind_of(Path("REPORT.DOCX")), "office")

    def test_workbook_multiple_sheets_sparse_cells_and_formulas(self):
        s, r = office.NS["s"], office.NS["r"]
        path = self.package("sample.xlsx", {
            "xl/workbook.xml": f'<workbook xmlns="{s}" xmlns:r="{r}"><sheets><sheet name="First &amp; best" r:id="r1"/><sheet name="Second" r:id="r2"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="/xl/worksheets/sheet2.xml"/></Relationships>',
            "xl/sharedStrings.xml": f'<sst xmlns="{s}"><si><t>Shared &lt;text&gt;</t></si></sst>',
            "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{s}"><sheetData><row r="3"><c r="A3" t="s"><v>0</v></c><c r="C3"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>',
            "xl/worksheets/sheet2.xml": f'<worksheet xmlns="{s}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Other sheet</t></is></c></row></sheetData></worksheet>',
        })
        html = office.preview(path)
        self.assertIn("First &amp; best", html)
        self.assertIn("Shared &lt;text&gt;</td><td></td><td>2</td>", html)
        self.assertIn("Other sheet", html)
        self.assertIn("<th>3</th>", html)

    def test_presentation_uses_slide_order_and_embeds_image(self):
        p, a, r = office.NS["p"], office.NS["a"], office.NS["r"]
        path = self.package("sample.pptx", {
            "ppt/presentation.xml": f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst><p:sldId r:id="r2"/><p:sldId r:id="r1"/></p:sldIdLst></p:presentation>',
            "ppt/_rels/presentation.xml.rels": '<Relationships><Relationship Id="r1" Target="slides/slide1.xml"/><Relationship Id="r2" Target="slides/slide2.xml"/></Relationships>',
            "ppt/slides/slide1.xml": f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:spTree><p:sp><a:p><a:r><a:t>Last slide</a:t></a:r></a:p></p:sp></p:spTree></p:cSld></p:sld>',
            "ppt/slides/slide2.xml": f'<p:sld xmlns:p="{p}" xmlns:a="{a}" xmlns:r="{r}"><p:cSld><p:spTree><p:sp><a:p><a:r><a:t>First slide</a:t></a:r></a:p></p:sp><p:pic><a:blip r:embed="image1"/></p:pic></p:spTree></p:cSld></p:sld>',
            "ppt/slides/_rels/slide2.xml.rels": '<Relationships><Relationship Id="image1" Target="../media/image.png"/><Relationship Id="external" Target="https://example.com/x.png" TargetMode="External"/></Relationships>',
            "ppt/media/image.png": b"image bytes",
        })
        html = office.preview(path)
        self.assertLess(html.index("First slide"), html.index("Last slide"))
        self.assertIn("data:image/png;base64,", html)
        self.assertNotIn("example.com", html)

    def test_malformed_and_entity_documents_rejected(self):
        bad = self.root / "bad.docx"
        bad.write_text("not a zip")
        with self.assertRaises(ValueError):
            office.preview(bad)
        entity = self.package("entity.docx", {"word/document.xml": '<!DOCTYPE x [<!ENTITY x "text">]><x>&x;</x>'})
        with self.assertRaises(ValueError):
            office.preview(entity)

    def test_route_authentication_sandbox_and_original_download(self):
        cfg = {"workspace": str(self.root), "agents": [{"name": "one", "provider": "mock"}]}
        app = create_hub(cfg, 8765, "token")
        with patch.object(Room, "start"):
            room = asyncio.run(app.state.hub.open_room(["one"], Location()))
        original = self.word()
        room.files["doc"] = original
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            url = room.base + "/files/doc/office"
            self.assertEqual(client.get(url).status_code, 403)
            response = client.get(url, params={"f": room.file_token("doc")})
            self.assertEqual(response.status_code, 200)
            self.assertIn("sandbox", response.headers["content-security-policy"])
            self.assertIn("Table cell", response.text)
            raw = client.get(room.base + "/files/doc", params={"f": room.file_token("doc")})
            self.assertEqual(raw.content, original.read_bytes())
            original.write_text("bad zip")
            self.assertEqual(client.get(url, params={"t": "token"}).status_code, 422)

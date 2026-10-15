import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from epub_note_style import apply_weread_cards, local_target

NS = {'h': 'http://www.w3.org/1999/xhtml', 'o': 'http://www.idpf.org/2007/opf'}


def fixture(root, cross=False, missing=False):
    def write(name, text):
        path = root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    write('mimetype','application/epub+zip')
    write('META-INF/container.xml','<container><rootfiles><rootfile full-path="EPUB/content.opf"/></rootfiles></container>')
    extra = '<item id="notes" href="text/notes.xhtml" media-type="application/xhtml+xml"/>' if cross else ''
    write('EPUB/content.opf','<package xmlns="http://www.idpf.org/2007/opf"><metadata/><manifest><item id="c" href="text/ch.xhtml" media-type="application/xhtml+xml"/>'+extra+'</manifest><spine><itemref idref="c"/></spine></package>')
    opening='<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>test</title></head><body>'
    note='<aside id="fn1" epub:type="footnote" role="doc-footnote"><p>引文 &amp; “双引号” &lt;比较&gt;，<em>强调</em>。</p><p>第二段。<a href="https://example.com">文献链接</a><a href="ch.xhtml#fnref1" class="footnote-back" role="doc-backlink">返回</a></p></aside>'
    target=('notes.xhtml' if cross else '')+('#missing' if missing else '#fn1')
    ref=f'<a href="{target}" id="fnref1" class="footnote-ref" role="doc-noteref" epub:type="noteref"><sup>1</sup></a>'
    write('EPUB/text/ch.xhtml',opening+'<p>正文前'+ref+'正文后</p>'+('' if cross else note)+'</body></html>')
    if cross:
        write('EPUB/text/notes.xhtml',opening+note+'</body></html>')


class NoteStyleTests(unittest.TestCase):
    def test_cards_preserve_text_ids_backlinks_and_xml(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); fixture(root)
            self.assertEqual(apply_weread_cards(root),1)
            doc=ET.parse(root/'EPUB/text/ch.xhtml')
            img=doc.find('.//h:img',NS)
            self.assertEqual(img.get('id'),'fnref1')
            self.assertEqual(img.tail,'正文后')
            self.assertEqual(img.get('alt'),'引文 & “双引号” <比较>，强调。\n第二段。文献链接')
            self.assertEqual(img.get('class'),'qqreader-footnote')
            self.assertIsNone(doc.find('.//h:a/h:img',NS))
            self.assertIsNotNone(doc.find('.//h:aside',NS))
            self.assertIsNotNone(doc.find('.//h:a[@role="doc-backlink"]',NS))
            opf=ET.parse(root/'EPUB/content.opf')
            self.assertEqual(opf.find('.//o:item[@id="annotation-note-icon"]',NS).get('media-type'),'image/png')
            self.assertEqual(apply_weread_cards(root),0)

    def test_cross_file_note(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); fixture(root,cross=True)
            self.assertEqual(apply_weread_cards(root),1)
            self.assertIn('第二段',ET.parse(root/'EPUB/text/ch.xhtml').find('.//h:img',NS).get('alt'))

    def test_missing_note_fails_before_rewrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); fixture(root,missing=True)
            path=root/'EPUB/text/ch.xhtml'; before=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'Missing footnote'):
                apply_weread_cards(root)
            self.assertEqual(path.read_bytes(),before)
            self.assertFalse((root/'EPUB/images/annotation-note.png').exists())

    def test_package_path_escape_rejected(self):
        for href in ('../../outside.xhtml#x','/outside.xhtml#x','https://example.com/#x'):
            with self.assertRaises(ValueError):
                local_target('EPUB/ch.xhtml',href)

    def test_repeated_references_keep_distinct_return_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); fixture(root)
            path=root/'EPUB/text/ch.xhtml'
            text=path.read_text(encoding='utf-8').replace('</body>',
                '<p>再次引用<a id="again" href="#fn1" epub:type="noteref">1</a>尾文</p></body>')
            path.write_text(text,encoding='utf-8')
            self.assertEqual(apply_weread_cards(root),2)
            images=ET.parse(path).findall('.//h:img',NS)
            self.assertEqual([i.get('id') for i in images],['fnref1','again'])
            self.assertEqual(images[0].get('alt'),images[1].get('alt'))
            self.assertEqual(images[1].tail,'尾文')

    def test_cli_recognizes_semantics_only_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); srcdir=root/'source'; fixture(srcdir)
            path=srcdir/'EPUB/text/ch.xhtml'
            path.write_text(path.read_text(encoding='utf-8').replace(
                ' class="footnote-ref" role="doc-noteref"',''),encoding='utf-8')
            src=root/'raw.epub'; out=root/'out.epub'
            with zipfile.ZipFile(src,'w') as archive:
                for p in srcdir.rglob('*'):
                    if p.is_file(): archive.write(p,p.relative_to(srcdir).as_posix())
            subprocess.run([sys.executable,str(ROOT/'scripts/step5_fix_epub.py'),str(src),str(out),
                            '--note-style','weread-card'],check=True,capture_output=True)
            with zipfile.ZipFile(out) as archive:
                doc=ET.fromstring(archive.read('EPUB/text/ch.xhtml'))
                self.assertIsNotNone(doc.find('.//h:img[@class="qqreader-footnote"]',NS))

    def test_cli_default_jump_and_explicit_card(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); srcdir=root/'source'; fixture(srcdir)
            src=root/'raw.epub'
            with zipfile.ZipFile(src,'w') as archive:
                for path in srcdir.rglob('*'):
                    if path.is_file(): archive.write(path,path.relative_to(srcdir).as_posix())
            for mode in (None,'jump','weread-card'):
                out=root/(str(mode)+'.epub')
                command=[sys.executable,str(ROOT/'scripts/step5_fix_epub.py'),str(src),str(out)]
                if mode: command += ['--note-style',mode]
                subprocess.run(command,check=True,capture_output=True)
                with zipfile.ZipFile(out) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertEqual(archive.infolist()[0].filename,'mimetype')
                    self.assertEqual(archive.infolist()[0].compress_type,zipfile.ZIP_STORED)
                    doc=ET.fromstring(archive.read('EPUB/text/ch.xhtml'))
                    self.assertIsNotNone(doc.find('.//h:a[@role="doc-backlink"]',NS))
                    if mode=='weread-card':
                        self.assertIsNotNone(doc.find('.//h:img[@class="qqreader-footnote"]',NS))
                        self.assertIsNone(doc.find('.//h:a[@role="doc-noteref"]',NS))
                    else:
                        self.assertIsNotNone(doc.find('.//h:a[@role="doc-noteref"]',NS))
                        self.assertIsNone(doc.find('.//h:img',NS))


if __name__=='__main__':
    unittest.main()

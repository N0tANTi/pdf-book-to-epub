"""WeRead image footnotes. Only package structure is tested locally; client UI is native."""
import posixpath
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

XHTML = 'http://www.w3.org/1999/xhtml'
OPF = 'http://www.idpf.org/2007/opf'
EPUB = 'http://www.idpf.org/2007/ops'
ET.register_namespace('', XHTML)
ET.register_namespace('epub', EPUB)


def local_target(source, href):
    url = urlsplit(href)
    if url.scheme or url.netloc:
        raise ValueError(f'Footnote must be internal: {href}')
    target = (posixpath.normpath(posixpath.join(posixpath.dirname(source), unquote(url.path)))
              if url.path else source)
    if target == '..' or target.startswith(('../', '/', '\\')):
        raise ValueError(f'Footnote leaves the publication: {href}')
    return target, unquote(url.fragment)


def note_text(element):
    """Plain popup text; rich XHTML is retained in the chapter/endnotes."""
    blocks = {'p', 'div', 'li', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'aside'}
    def visit(node):
        tag = node.tag.rsplit('}', 1)[-1]
        classes = node.get('class', '').split()
        if (node.get('role') == 'doc-backlink' or
                any(c in classes for c in ('footnote-back', 'footnote-backref')) or
                tag in {'script', 'style'}):
            return ''
        if tag == 'br':
            return '\n'
        if tag == 'img':
            return node.get('alt', '')
        result = node.text or ''
        for child in node:
            result += visit(child) + (child.tail or '')
        return ('\n' + result + '\n') if tag in blocks else result
    return '\n'.join(re.sub(r'[\t \r]+', ' ', line).strip()
                     for line in visit(element).splitlines() if line.strip()).strip()


def apply_weread_cards(root: Path):
    """Replace note-reference anchors with bare qqreader-footnote images.

    Validate every reference before writing any XHTML. Preserve reference IDs,
    trailing prose, full note definitions, and existing backlinks.
    """
    container = ET.parse(root / 'META-INF' / 'container.xml').getroot()
    entry = container.find('.//{*}rootfile')
    if entry is None:
        raise ValueError('Missing package rootfile')
    opf_name, _ = local_target('root.opf', entry.attrib['full-path'])
    opf_path = root / opf_name
    package = ET.parse(opf_path)
    manifest = package.getroot().find(f'{{{OPF}}}manifest')
    if manifest is None:
        raise ValueError('Missing OPF manifest')
    trees = {}
    for item in manifest:
        if item.get('media-type') != 'application/xhtml+xml':
            continue
        name, _ = local_target(opf_name, item.attrib['href'])
        trees[name] = ET.parse(root / name)
    definitions = {}
    for name, tree in trees.items():
        for el in tree.iter():
            if el.get('id'):
                key = name, el.get('id')
                if key in definitions:
                    raise ValueError(f'Duplicate ID: {key}')
                definitions[key] = el
    planned = []
    for name, tree in trees.items():
        parents = {child: parent for parent in tree.iter() for child in parent}
        for el in tree.iter(f'{{{XHTML}}}a'):
            if not (el.get('role') == 'doc-noteref' or
                    'footnote-ref' in el.get('class', '').split() or
                    'noteref' in el.get(f'{{{EPUB}}}type', '').split()):
                continue
            key = local_target(name, el.get('href', ''))
            if not key[1] or key not in definitions:
                raise ValueError(f'Missing footnote: {name} -> {el.get("href")}')
            content = note_text(definitions[key])
            if not content:
                raise ValueError(f'Empty footnote: {key}')
            if not el.get('id'):
                raise ValueError(f'Footnote reference needs an ID for return navigation: {name}')
            planned.append((name, parents[el], el, content))
    if not planned:
        return 0
    icon_name = posixpath.join(posixpath.dirname(opf_name), 'images', 'annotation-note.png')
    icon_path = root / icon_name
    asset = Path(__file__).resolve().parent.parent / 'assets' / 'note.png'
    data = asset.read_bytes()
    if icon_path.exists() and icon_path.read_bytes() != data:
        raise ValueError(f'Refusing to overwrite an unrelated asset: {icon_name}')
    changed = set()
    for name, parent, old, content in planned:
        new = ET.Element(f'{{{XHTML}}}img', {
            'id': old.attrib['id'], 'class': 'qqreader-footnote',
            'src': posixpath.relpath(icon_name, posixpath.dirname(name)),
            'alt': content,
            'style': 'width:1em;height:1em;vertical-align:-0.12em;margin:0 0.1em;',
        })
        new.tail = old.tail
        index = list(parent).index(old)
        parent.remove(old)
        parent.insert(index, new)
        changed.add(name)
    icon_path.parent.mkdir(parents=True, exist_ok=True)
    icon_path.write_bytes(data)
    icon_href = posixpath.relpath(icon_name, posixpath.dirname(opf_name))
    if not any(item.get('href') == icon_href for item in manifest):
        ids = {item.get('id') for item in manifest}
        item_id = 'annotation-note-icon'
        while item_id in ids:
            item_id += '-1'
        ET.SubElement(manifest, f'{{{OPF}}}item', {
            'id': item_id, 'href': icon_href, 'media-type': 'image/png'})
    for name in changed:
        trees[name].write(root / name, encoding='utf-8', xml_declaration=True)
    package.write(opf_path, encoding='utf-8', xml_declaration=True)
    return len(planned)

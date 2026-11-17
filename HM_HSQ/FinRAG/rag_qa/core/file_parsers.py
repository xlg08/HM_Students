"""Additional file parsers returning text and logical locations."""
import json
import base64
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


def office_pages(path):
    suffix = path.suffix.lower()
    if suffix in {'.xlsx', '.xlsm'}:
        import openpyxl
        book = openpyxl.load_workbook(path, read_only=True, data_only=False)
        try:
            return [('\n'.join(' | '.join('' if c is None else str(c) for c in row)
                              for row in sheet.iter_rows(values_only=True)), sheet.title) for sheet in book]
        finally:
            book.close()
    if suffix == '.xls':
        import xlrd
        book = xlrd.open_workbook(path)
        try:
            return [('\n'.join(' | '.join(str(c) for c in sheet.row_values(row)) for row in range(sheet.nrows)), sheet.name)
                    for sheet in book.sheets()]
        finally:
            book.release_resources()
    raise ValueError(f'Unsupported spreadsheet {suffix}')


def legacy_word(path):
    converter = os.getenv('RAG_OFFICE_CONVERTER') or shutil.which('soffice') or shutil.which('libreoffice')
    if converter:
        from docx import Document
        with tempfile.TemporaryDirectory() as temporary:
            profile = (Path(temporary) / 'profile').as_uri()
            result = subprocess.run([converter, '-env:UserInstallation=' + profile, '--headless', '--convert-to', 'docx',
                                     '--outdir', temporary, str(path)], capture_output=True, timeout=120)
            converted = Path(temporary) / (path.stem + '.docx')
            if result.returncode or not converted.exists():
                raise ValueError(f'DOC conversion failed: {path.name}')
            doc = Document(converted)
            return '\n'.join([p.text for p in doc.paragraphs] + [' | '.join(c.text for c in row.cells) for t in doc.tables for row in t.rows])
    if os.name == 'nt':
        script = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3
    $document = $word.Documents.Open($env:RAG_DOC_INPUT, $false, $true)
    [Console]::Write($document.Content.Text)
} finally {
    if ($document) { $document.Close($false); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($document) }
    if ($word) { $word.Quit(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word) }
}
"""
        environment = dict(os.environ, RAG_DOC_INPUT=str(path))
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
            base64.b64encode(script.encode('utf-16le')).decode('ascii')], env=environment,
            capture_output=True, encoding='utf-8', timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise ValueError('DOC parsing failed; install Microsoft Word or configure LibreOffice')
        return result.stdout
    raise ValueError('DOC requires LibreOffice; configure RAG_OFFICE_CONVERTER')


def mind_pages(path):
    if path.suffix.lower() == '.xmind':
        with zipfile.ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
                raise ValueError('Mind map expanded content exceeds 100 MB')
            if 'content.json' in archive.namelist():
                sheets = json.loads(archive.read('content.json'))
                pages = []
                for sheet in sheets:
                    lines = []
                    def visit(topic, ancestors):
                        title = topic.get('title', '')
                        chain = ancestors + [title]
                        lines.append(' > '.join(chain))
                        for group in topic.get('children', {}).values():
                            if isinstance(group, list):
                                for child in group:
                                    visit(child, chain)
                    visit(sheet.get('rootTopic', {}), [])
                    pages.append(('\n'.join(lines), sheet.get('title', 'Sheet')))
                return pages
            raw = archive.read('content.xml')
    else:
        raw = path.read_bytes()
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('XML entities and DTD are unsupported')
    root = ET.fromstring(raw)
    lines = []
    def visit_xml(node, ancestors):
        tag = node.tag.split('}')[-1]
        title = ''
        if tag in {'node', 'outline'}:
            title = node.get('TEXT') or node.get('text') or node.get('title') or ''
        elif tag == 'topic':
            title = next((child.text or '' for child in node if child.tag.split('}')[-1] == 'title'), '')
        chain = ancestors + [title] if title else ancestors
        if title:
            lines.append(' > '.join(chain))
        for child in node:
            visit_xml(child, chain)
    visit_xml(root, [])
    return [('\n'.join(lines), path.stem)]

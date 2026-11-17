import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from base import Config
from rag_qa.core.document_processor import load_file, process_documents
from rag_qa.core.context_builder import build_context
from rag_qa.core.rag_system import RAGSystem


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_missing_empty_and_unsupported(self):
        with self.assertRaises(FileNotFoundError):
            process_documents(self.root / 'missing.pdf')
        empty = self.root / 'empty.txt'
        empty.write_text('')
        with self.assertRaisesRegex(ValueError, 'No text'):
            load_file(empty)
        with self.assertRaises(ValueError):
            load_file(self.root / 'bad.exe')

    def test_pdf_and_directory_chunks(self):
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        path = self.root / 'test.pdf'
        with fitz.open() as pdf:
            page = pdf.new_page()
            page.insert_text((60, 60), 'ALPHA unique PDF document. ' * 8)
            pdf.save(path)
        (self.root / 'notes.md').write_text('BETA notes ' * 100)
        first = process_documents(path)
        second = process_documents(path)
        self.assertEqual([d.metadata['chunk_id'] for d in first], [d.metadata['chunk_id'] for d in second])
        self.assertTrue(all(len(d.page_content) <= 300 for d in first))
        self.assertEqual({Path(d.metadata['source']).suffix for d in process_documents(self.root)}, {'.pdf', '.md'})
        with fitz.open() as pdf:
            pdf.new_page()
            pdf.save(self.root / 'blank.pdf')
        with patch('rapidocr_onnxruntime.RapidOCR') as ocr:
            ocr.return_value.return_value = (None, None)
            with self.assertRaisesRegex(ValueError, 'No text'):
                load_file(self.root / 'blank.pdf')

    def test_spreadsheet_word_and_mindmaps(self):
        from openpyxl import Workbook
        from docx import Document
        book = Workbook(); book.active.title = 'Balances'; book.active.append(['ALPHA', 2026])
        book.save(self.root / 'sample.xlsx'); book.close()
        self.assertEqual(load_file(self.root / 'sample.xlsx')[0].metadata['location'], 'Balances')
        word = Document(); word.add_paragraph('BETA word content'); word.save(self.root / 'sample.docx')
        self.assertIn('BETA', load_file(self.root / 'sample.docx')[0].page_content)
        (self.root / 'sample.mm').write_text('<map><node TEXT="Root"><node TEXT="ALPHA"/></node></map>')
        self.assertIn('Root > ALPHA', load_file(self.root / 'sample.mm')[0].page_content)
        (self.root / 'sample.opml').write_text('<opml><body><outline text="Root"><outline text="BETA"/></outline></body></opml>')
        self.assertIn('Root > BETA', load_file(self.root / 'sample.opml')[0].page_content)
        for name, content in [('new.xmind', 'content.json'), ('old.xmind', 'content.xml')]:
            with zipfile.ZipFile(self.root / name, 'w') as archive:
                data = json.dumps([{'title': 'Map', 'rootTopic': {'title': 'ALPHA', 'children': {'attached': [{'title': 'BETA'}]}}}]) if content.endswith('json') else '<xmap-content><sheet><topic><title>ALPHA</title><children><topic><title>BETA</title></topic></children></topic></sheet></xmap-content>'
                archive.writestr(content, data)
            self.assertIn('ALPHA > BETA', load_file(self.root / name)[0].page_content)

    def test_doc_converter_failure_is_explicit(self):
        from rag_qa.core.file_parsers import legacy_word
        with patch('shutil.which', return_value=None), patch.dict('os.environ', {'RAG_OFFICE_CONVERTER': ''}), patch('subprocess.run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaises(ValueError):
                legacy_word(self.root / 'missing.doc')


class PipelineTests(unittest.TestCase):
    def test_budget_sources_empty_and_model_failure(self):
        from langchain_core.documents import Document
        doc = Document(page_content='ALPHA ' * 1000, metadata={'source': '/data/test.pdf', 'page': 3, 'chunk_id': 'one'})
        context, sources = build_context([doc], 128)
        self.assertLessEqual(len(context.encode('utf-8')), 128)
        self.assertEqual(sources[0]['chunk_id'], 'one')
        self.assertEqual(sources[0]['document'], 'test.pdf')
        config = Config(knowledge_base='test')
        store = SimpleNamespace(config=config, hybrid_search_with_rerank=lambda *a, **k: [])
        rag = RAGSystem(store, lambda prompt: self.fail('Empty evidence must not call LLM'))
        self.assertEqual(rag.answer('question')['sources'], [])
        store.hybrid_search_with_rerank = lambda *a, **k: [doc]
        def fail(prompt):
            raise RuntimeError('LLM unavailable')
        rag.llm = fail
        with self.assertRaisesRegex(RuntimeError, 'LLM unavailable'):
            rag.answer('question')
        with self.assertRaises(ValueError):
            rag.answer(' ')

    def test_collection_validation(self):
        with self.assertRaises(ValueError):
            Config(knowledge_base='../unsafe')
        self.assertNotEqual(Config(knowledge_base='alpha').MILVUS_COLLECTION_NAME, Config(knowledge_base='beta').MILVUS_COLLECTION_NAME)


if __name__ == '__main__':
    unittest.main()

"""Local document loading and parent-child chunking."""
import hashlib
from pathlib import Path
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

SUPPORTED_EXTENSIONS = {'.pdf', '.txt', '.md', '.docx', '.pptx', '.png', '.jpg', '.jpeg'}

def load_file(path):
    path = Path(path).resolve()
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f'Unsupported document type: {path}')
    if suffix == '.pdf':
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        pages = []
        with fitz.open(path) as pdf:
            for page in pdf:
                text = page.get_text()
                if not text.strip():
                    from rapidocr_onnxruntime import RapidOCR
                    result, _ = RapidOCR()(page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes('png'))
                    text = '\n'.join(line[1] for line in result or [])
                pages.append(text)
    elif suffix == '.docx':
        from docx import Document as WordDocument
        doc = WordDocument(path)
        pages = ['\n'.join([p.text for p in doc.paragraphs] + [' | '.join(cell.text for cell in row.cells) for table in doc.tables for row in table.rows])]
    elif suffix == '.pptx':
        from pptx import Presentation
        pages = ['\n'.join(shape.text for shape in slide.shapes if shape.has_text_frame) for slide in Presentation(path).slides]
    elif suffix in {'.png', '.jpg', '.jpeg'}:
        from rapidocr_onnxruntime import RapidOCR
        result, _ = RapidOCR()(str(path))
        pages = ['\n'.join(line[1] for line in result or [])]
    else:
        pages = [path.read_text(encoding='utf-8-sig')]
    documents = [Document(page_content=text, metadata={'source': str(path), 'page': index + 1}) for index, text in enumerate(pages) if text.strip()]
    if not documents:
        raise ValueError(f'No text extracted: {path}')
    return documents

def process_documents(path, parent_chunk_size=1200, child_chunk_size=300, chunk_overlap=50):
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    files = sorted(p for p in path.rglob('*') if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS) if path.is_dir() else [path]
    if not files:
        raise ValueError(f'No supported documents: {path}')
    separators = ['\n\n', '\n', '。', '！', '？', '；', ' ', '']
    parents = RecursiveCharacterTextSplitter(chunk_size=parent_chunk_size, chunk_overlap=chunk_overlap, separators=separators)
    children = RecursiveCharacterTextSplitter(chunk_size=child_chunk_size, chunk_overlap=chunk_overlap, separators=separators)
    chunks = []
    for file in files:
        for doc in load_file(file):
            for index, parent in enumerate(parents.split_documents([doc])):
                identity = f"{file}:{doc.metadata['page']}:{index}:{parent.page_content}"
                parent.metadata.update(parent_id=hashlib.sha256(identity.encode()).hexdigest(), parent_content=parent.page_content)
                chunks.extend(children.split_documents([parent]))
    return chunks

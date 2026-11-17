"""Context construction with a conservative UTF-8 byte token upper bound."""
from pathlib import Path


def build_context(documents, max_tokens):
    remaining = max_tokens
    sections = []
    sources = []
    for doc in documents:
        metadata = doc.metadata
        source = {'document': metadata.get('document') or Path(metadata['source']).name,
                  'file_path': metadata['source'], 'page': metadata.get('page', 1),
                  'location': metadata.get('location', str(metadata.get('page', 1))),
                  'chunk_id': metadata.get('chunk_id') or metadata.get('parent_id')}
        if metadata.get('retrieval_warning'):
            source['warning'] = metadata['retrieval_warning']
        header = f"[{len(sources) + 1}] {source['document']} ({source['location']})\n"
        available = remaining - len(header.encode('utf-8')) - 2
        if available <= 0:
            break
        content = doc.page_content.encode('utf-8')[:available].decode('utf-8', errors='ignore')
        if not content.strip():
            continue
        section = header + content
        remaining -= len(section.encode('utf-8')) + 2
        sections.append(section)
        sources.append(source)
    return '\n\n'.join(sections), sources

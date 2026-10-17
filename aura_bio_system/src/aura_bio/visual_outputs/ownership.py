"""Literal claim boundaries and conservative document-owned entity identity."""
import re


def literal_statement(text):
    value=re.sub(r'\s+',' ',text.strip())
    # Optional sentence punctuation, not sign/decimal/unit/qualifier removal.
    return value[:-1] if value.endswith('.') and not value.endswith('..') else value


def source_owner(evidence):
    document=getattr(evidence,'document_id',None)
    if document: return ('document',getattr(evidence,'pack_id',None),document)
    source=getattr(evidence,'source_id',None)
    if source: return ('source',source)
    chunk=getattr(evidence,'chunk_id',None)
    return ('chunk',chunk) if chunk else ('unidentified_evidence',id(evidence))

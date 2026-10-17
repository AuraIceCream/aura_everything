"""Tesseract TSV, not a truth checker. No dictionary correction or inference."""
import csv
import io
import os
import re
import shutil
import subprocess
from dataclasses import asdict
from .schema import OcrResult,digest
from ..schema import StudyError,Unit


def needs_ocr(native_text):
    text = native_text.strip()
    if not text: return True
    bad = text.count('\ufffd') + len(re.findall(r'\(cid:\d+\)',text))*5 + sum(ord(c)<32 and not c.isspace() for c in text)
    return bad/max(1,len(text)) > .08


def parse_tsv(tsv,transform,language,version):
    words,lines = [],{}
    for row in csv.DictReader(io.StringIO(tsv),delimiter='\t'):
        text = (row.get('text') or '').strip()
        if not text or row.get('level') != '5': continue
        try:
            left,top,width,height = [int(row[k]) for k in ('left','top','width','height')]
            confidence = float(row['conf'])
            if not (width>0 and height>0 and 0<=confidence<=100): continue
            box = [max(0,left/transform.render_width),max(0,top/transform.render_height),
                   min(1,(left+width)/transform.render_width),min(1,(top+height)/transform.render_height)]
            if box[2]<=box[0] or box[3]<=box[1]: continue
            words.append({'text':text,'confidence':confidence,'bbox':box,'numbers_verified':False})
            key=tuple(row.get(k,'') for k in ('page_num','block_num','par_num','line_num'))
            lines.setdefault(key,[]).append(text)
        except (ValueError,KeyError):
            raise StudyError('ocr_failed','Malformed OCR TSV output.')
    return OcrResult('\n'.join(' '.join(v) for v in lines.values()),tuple(words),'tesseract',language,version,transform,
                     ('OCR is transcription, not verified text; all OCR-derived numbers remain unverified.',))


class TesseractOcr:
    def __init__(self,executable=None):
        self.executable = executable or os.environ.get('AURA_TESSERACT') or shutil.which('tesseract') or r'C:\Program Files\Tesseract-OCR\tesseract.exe'

    def read(self,asset,*,language='eng',timeout_seconds=60):
        if not 5<=timeout_seconds<=300 or not re.fullmatch(r'[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*',language):
            raise StudyError('invalid_config','OCR timeout must be 5–300 seconds and language an installed Tesseract language.')
        try:
            common={'stdout':subprocess.PIPE,'stderr':subprocess.PIPE,'timeout':5,'creationflags':subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0}
            languages=subprocess.run([self.executable,'--list-langs'],**common)
            available=set(languages.stdout.decode('utf-8',errors='replace').splitlines()[1:])
            if not set(language.split('+')) <= available:
                raise StudyError('ocr_language_missing','Requested OCR language is not installed. Configure Tesseract language data.')
            version=subprocess.run([self.executable,'--version'],**common).stdout.decode('utf-8',errors='replace').splitlines()[0]
            result=subprocess.run([self.executable,'stdin','stdout','-l',language,'tsv'],input=asset.content,
                                  **{**common,'timeout':timeout_seconds})
            if result.returncode:
                raise StudyError('ocr_failed','Tesseract failed; no page was certified. Check the installed engine and language data.')
            return parse_tsv(result.stdout.decode('utf-8'),asset.transform,language,version)
        except StudyError:
            raise
        except subprocess.TimeoutExpired as exc:
            raise StudyError('ocr_timeout','This page exceeded its OCR deadline; other page checkpoints are retained.') from exc
        except OSError as exc:
            raise StudyError('ocr_engine_missing','Tesseract is unavailable. Install/configure the engine explicitly; no fallback was run.') from exc


def ocr_unit(parent,result):
    record=asdict(result)
    key=digest({'source':parent.unit_id,'ocr':record})[:32]
    return Unit(key,parent.document_id,parent.ordinal,'ocr_transcription',parent.title,parent.breadcrumb,result.text,parent.locators,
                {'ocr':record},parent.asset_ids,'ocr',{'source_unit_id':parent.unit_id,'checksum':digest(record),
                'engine':result.engine,'language':result.language,'numbers_verified':False})

"""Bounded, metadata-free derivatives. Original bytes are never changed."""
import io
import math
from pathlib import Path
from dataclasses import replace
from .schema import RenderedAsset, SourceTransform, NormalizedBox, digest
from ..schema import StudyError


def inspect_bytes(content, limits, *, expected_format=None):
    """Header/frame/pixel preflight only; worker owns full pixel decoding."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise StudyError('missing_dependency', 'Install the visual extra (Pillow) for image intake.') from exc
    magic = 'PNG' if content.startswith(b'\x89PNG\r\n\x1a\n') else 'JPEG' if content.startswith(b'\xff\xd8\xff') else None
    if magic is None or expected_format and magic != expected_format:
        raise StudyError('invalid_container', 'Only genuine single-frame PNG/JPEG images are accepted.')
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format != magic or getattr(image, 'n_frames', 1) != 1:
                raise StudyError('invalid_container', 'Animated/multiframe or mismatched images are unsupported.')
            if image.width * image.height > min(limits.max_image_pixels, 25_000_000):
                raise StudyError('limit', 'Decoded image exceeds the 25-million-pixel safety ceiling.')
            return image.size
    except StudyError:
        raise
    except Exception as exc:
        raise StudyError('invalid_container', f'Image header inspection failed ({type(exc).__name__}).') from exc


def decode_bytes(content, limits, *, expected_format=None):
    inspect_bytes(content,limits,expected_format=expected_format)
    from PIL import Image,ImageOps
    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            orientation = image.getexif().get(274, 1)
            rotation = {3:180,4:180,5:270,6:90,7:90,8:270}.get(orientation,0)
            upright = ImageOps.exif_transpose(image).convert('RGB')
            # Copy pixels into a new image so EXIF/ICC/comments do not survive.
            clean = Image.new('RGB', upright.size); clean.paste(upright)
            out = io.BytesIO(); clean.save(out, format='PNG')
            raw = out.getvalue()
            return RenderedAsset(digest(raw)[:32], clean.width, clean.height, digest(raw),
                                 SourceTransform(width,height,clean.width,clean.height,rotation, reflected=orientation in (2,4,5,7)),raw)
    except StudyError:
        raise
    except Exception as exc:
        raise StudyError('invalid_container', f'Image decode failed ({type(exc).__name__}).') from exc


def decode_image(path: Path, limits):
    size = path.stat().st_size
    if size > limits.max_upload_bytes:
        raise StudyError('limit', 'Image exceeds the upload byte limit.')
    expected = {'.png':'PNG','.jpg':'JPEG','.jpeg':'JPEG'}.get(path.suffix.lower())
    return decode_bytes(path.read_bytes(), limits, expected_format=expected)


def render_pdf_page(path: Path, page: int, limits):
    try:
        import pypdfium2 as pdfium
        from pypdf import PdfReader
    except ImportError as exc:
        raise StudyError('missing_dependency', 'Install the visual extra (pypdfium2) to render PDF pages.') from exc
    if not 1 <= page <= limits.max_pages_or_slides:
        raise StudyError('invalid_page', 'Invalid physical PDF page.')
    pdf = pdfium.PdfDocument(path)
    bitmap = physical = None
    try:
        if len(pdf) > limits.max_pages_or_slides or page > len(pdf):
            raise StudyError('invalid_page', 'PDF page count/index exceeds the limit.')
        physical = pdf[page-1]
        width,height = physical.get_size()
        dpi = max(1,min(limits.render_dpi,200))
        ceiling = min(limits.max_render_pixels,12_000_000)
        scale = min(dpi/72, math.sqrt(ceiling/(width*height))*0.99)
        bitmap = physical.render(scale=scale)
        image = bitmap.to_pil().convert('RGB')
        if image.width*image.height > ceiling:
            image.thumbnail((int(math.sqrt(ceiling*image.width/image.height)),int(math.sqrt(ceiling*image.height/image.width))))
        out = io.BytesIO(); image.save(out,format='PNG'); content = out.getvalue()
        # pypdfium renders upright. Retain the unrotated point dimensions for inverse highlights.
        with path.open('rb') as source:
            original = PdfReader(source).pages[page-1]
            transform = SourceTransform(float(original.mediabox.width),float(original.mediabox.height),image.width,image.height,
                                        int(original.get('/Rotate',0)) % 360,'points',
                                        (float(original.cropbox.left-original.mediabox.left),float(original.mediabox.top-original.cropbox.top)),
                                        crop_width=float(original.cropbox.width),crop_height=float(original.cropbox.height))
        return RenderedAsset(digest(content)[:32],image.width,image.height,digest(content),transform,content,
                             metadata={'dpi':min(dpi,scale*72),'page':page,'frame':'page_normalized'})
    except StudyError:
        raise
    except Exception as exc:
        raise StudyError('render_failed', f'PDF rendering failed ({type(exc).__name__}).') from exc
    finally:
        if bitmap is not None: bitmap.close()
        if physical is not None: physical.close()
        pdf.close()


def crop_bytes(content, bbox: NormalizedBox, *, max_pixels=1_000_000):
    from PIL import Image
    with Image.open(io.BytesIO(content)) as image:
        box = (math.floor(bbox.x0*image.width),math.floor(bbox.y0*image.height),math.ceil(bbox.x1*image.width),math.ceil(bbox.y1*image.height))
        crop = image.crop(box).convert('RGB')
        scale = min(1,math.sqrt(max_pixels/(crop.width*crop.height)))
        if scale < 1: crop = crop.resize((max(1,int(crop.width*scale)),max(1,int(crop.height*scale))))
        clean = Image.new('RGB',crop.size); clean.paste(crop)
        out = io.BytesIO(); clean.save(out,format='PNG')
        return out.getvalue()

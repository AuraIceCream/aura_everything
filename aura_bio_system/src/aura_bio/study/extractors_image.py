from dataclasses import asdict
from .schema import Asset, Extraction, Locator, Unit
from .extractors import unit_id
from .visual.assets import decode_image


def extract(path, document, limits):
    image = decode_image(path,limits)
    key = unit_id(document,'image:1')
    unit = Unit(key,document.document_id,0,'image',document.filename,'','',(Locator('image'),),
                {'frame':'asset_normalized','transform':asdict(image.transform)},(image.asset_id,))
    return Extraction([unit],[Asset(image.asset_id,key,'image/png',image.content,{'width':image.width,'height':image.height,'frame':'asset_normalized','transform':asdict(image.transform)})],
                      ['Image retained; OCR/vision requires an explicit visual job.'],{'units':1,'text_units':0,'visual_units':1},'image-v1')

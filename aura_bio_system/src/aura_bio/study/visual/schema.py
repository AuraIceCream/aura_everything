"""Versioned visual contracts; coordinates refer to an upright preview."""
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any
from ..schema import StudyError


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class NormalizedBox:
    x0: float = 0
    y0: float = 0
    x1: float = 1
    y1: float = 1

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.x0, self.y0, self.x1, self.y1)) or not (0 <= self.x0 < self.x1 <= 1 and 0 <= self.y0 < self.y1 <= 1):
            raise StudyError('invalid_crop', 'Crop must be a nonempty rectangle inside the upright source image.')

    def values(self):
        return self.x0, self.y0, self.x1, self.y1


@dataclass(frozen=True)
class SourceTransform:
    original_width: float
    original_height: float
    render_width: int
    render_height: int
    rotation: int = 0
    units: str = 'pixels'
    crop_offset: tuple[float, float] = (0, 0)
    reflected: bool = False
    crop_width: float | None = None
    crop_height: float | None = None

    def __post_init__(self):
        values=(self.original_width,self.original_height,self.render_width,self.render_height,self.crop_width or self.original_width,self.crop_height or self.original_height,*self.crop_offset)
        if not all(math.isfinite(v) for v in values) or min(values[:6]) <= 0 or self.rotation not in (0, 90, 180, 270):
            raise StudyError('invalid_transform', 'Invalid image transform.')

    def to_display(self, box):
        x0, y0, x1, y1 = box
        x0, x1 = (x0-self.crop_offset[0])/(self.crop_width or self.original_width), (x1-self.crop_offset[0])/(self.crop_width or self.original_width)
        y0, y1 = (y0-self.crop_offset[1])/(self.crop_height or self.original_height), (y1-self.crop_offset[1])/(self.crop_height or self.original_height)
        points = [(x0, y0), (x1, y1)]
        def rotate(x, y):
            if self.reflected: x = 1-x
            return {0: (x, y), 90: (1-y, x), 180: (1-x, 1-y), 270: (y, 1-x)}[self.rotation]
        points = [rotate(*p) for p in points]
        return NormalizedBox(min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points))

    def to_original(self, box):
        def inverse(x, y):
            x,y = {0: (x, y), 90: (y, 1-x), 180: (1-x, 1-y), 270: (1-y, x)}[self.rotation]
            return (1-x if self.reflected else x), y
        points = [inverse(box.x0, box.y0), inverse(box.x1, box.y1)]
        width,height=self.crop_width or self.original_width,self.crop_height or self.original_height
        return (min(p[0] for p in points)*width+self.crop_offset[0], min(p[1] for p in points)*height+self.crop_offset[1],
                max(p[0] for p in points)*width+self.crop_offset[0], max(p[1] for p in points)*height+self.crop_offset[1])


@dataclass(frozen=True)
class RenderedAsset:
    asset_id: str
    width: int
    height: int
    checksum: str
    transform: SourceTransform
    content: bytes = field(default=b'', repr=False)
    mime_type: str = 'image/png'
    unit_id: str = ''
    document_id: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FigureCandidate:
    figure_id: str
    unit_id: str
    asset_id: str
    document_id: str
    locator: dict[str, Any]
    bbox: NormalizedBox
    frame: str
    reason: str
    context_hash: str
    exclusion_reason: str | None = None
    checksum: str = ''
    figure_label: str = ''
    caption: str = ''
    reference_kind: str = 'figure'


def candidate_from_dict(value):
    return FigureCandidate(**{**value, 'bbox': NormalizedBox(**value['bbox'])})


@dataclass(frozen=True)
class OcrResult:
    text: str
    words: tuple[dict[str, Any], ...]
    engine: str
    language: str
    version: str
    transform: SourceTransform
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class VisualJobConfig:
    provider: str = 'ollama'
    model: str = 'qwen3.5:4b'
    model_digest: str = ''
    prompt_version: str = 'figure-v1'
    prompt_hash: str = ''
    timeout_seconds: float = 300
    ocr_timeout_seconds: float = 60
    max_figures: int = 20
    max_pixels: int = 1_000_000
    num_ctx: int = 4096
    num_predict: int = 2048
    token_budget: int = 50_000
    consent: dict[str, Any] = field(default_factory=dict)
    snapshot: dict[str, str] = field(default_factory=dict)
    managed_swap: bool = False
    question: str = ''
    think: bool = False
    description_version: int = 1
    focus: bool = False

    def __post_init__(self):
        if type(self.description_version) is not int or self.description_version not in (1,2) or type(self.focus) is not bool:
            raise StudyError('invalid_config','Unknown figure-description version or focus mode.')
        if self.focus and (self.description_version!=2 or not self.question or self.provider!='ollama'):
            raise StudyError('invalid_config','Focused reading requires a version-2 local question job.')
        if not isinstance(self.think, bool) or (self.think and self.provider != 'ollama'):
            raise StudyError('invalid_config', 'Optional thinking is supported only by the explicitly selected local vision backend.')
        if not isinstance(self.question, str) or len(self.question) > 4000:
            raise StudyError('invalid_config', 'Question focus must be text of at most 4000 characters.')
        if self.provider not in {'ollama', 'groq', 'ocr'} or not self.model or len(self.model) > 160 or not (30 <= self.timeout_seconds <= 600 and 5 <= self.ocr_timeout_seconds <= 300 and 1 <= self.max_figures <= 200 and 1 <= self.max_pixels <= 1_000_000 and 1 <= self.num_ctx <= 4096 and 1 <= self.num_predict <= (4096 if self.think else 2048) and 1 <= self.token_budget <= 50_000):
            raise StudyError('invalid_config', 'Visual configuration exceeds the supported resource limits.')
        allowed = {'external_allowed', 'images', 'hints', 'disclosure_version'}
        if set(self.consent) - allowed or any(not isinstance(v, (bool, str)) for v in self.consent.values()):
            raise StudyError('invalid_config', 'Unknown consent fields; never put an API key in job records.')
        if any(not isinstance(v, str) for v in self.snapshot.values()):
            raise StudyError('invalid_config', 'Snapshot hashes must be strings.')

    @property
    def checksum(self):
        values=asdict(self)
        if self.description_version==1 and not self.focus:
            values.pop('description_version');values.pop('focus')
        return digest(values)


@dataclass(frozen=True)
class VisualCheckpoint:
    job_id: str
    item_id: str
    source_hash: str
    config_hash: str
    state: str = 'queued'
    attempts: int = 0
    revision_id: str | None = None
    error: str | None = None
    updated_at: float = 0
    resume_at: float | None = None
    responses: tuple[dict[str,Any], ...] = ()


@dataclass(frozen=True)
class FigureInput:
    candidate: FigureCandidate
    image: bytes = field(repr=False)
    config: VisualJobConfig
    ocr_hint: str = ''
    caption_hint: str = ''


@dataclass(frozen=True)
class ProviderResponse:
    raw: str
    provider: str
    model: str
    model_digest: str = ''
    usage: dict[str, int] = field(default_factory=dict)
    elapsed_seconds: float = 0
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FigureDescription:
    fields: dict[str, Any]
    responses: tuple[ProviderResponse, ...]
    prompt_hash: str
    config_hash: str

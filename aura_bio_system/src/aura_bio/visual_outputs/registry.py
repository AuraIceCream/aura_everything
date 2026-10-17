"""Request-scoped source identity, never evidence verification or fuzzy repair."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from .schema import _load_visual, _validate


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def context_identity(context):
    return _hash({'claims':[(c.id,c.claim,c.cite_ids,c.depends_on,dict(context.basis_by_id[c.id])) for c in context.claims],
        'sources':[(getattr(e,'pack_id',''),getattr(e,'document_id',''),getattr(e,'unit_ids',()),
                    getattr(e,'generation',0),getattr(e,'chunk_id',''),e.text,
                    getattr(e,'provenance','native_text'),getattr(e,'provenance_details',{})) for e in context.evidence]})


@dataclass(frozen=True)
class EvidenceFragment:
    id: str
    cite_id: int
    claim_ids: tuple[str,...]
    start: int
    end: int
    text: str
    provenance: str
    source_hash: str
    generation: int
    locator: tuple[str,...]

    def prompt_record(self):
        return {'id':self.id,'cite':self.cite_id,'claims':list(self.claim_ids),'text':self.text}


@dataclass(frozen=True)
class EvidenceRegistry:
    context_hash: str
    fragments: tuple[EvidenceFragment,...]
    omitted_claim_ids: tuple[str,...]


def build_registry(context, question, *, max_fragments=256, prompt_byte_budget):
    if type(max_fragments) is not int or not 1<=max_fragments<=256 or type(prompt_byte_budget) is not int or prompt_byte_budget<0:
        raise ValueError('Invalid registry bounds.')
    identity=context_identity(context); candidates=[]
    query=set(re.findall(r'\w+',question.casefold()))
    for cite,evidence in enumerate(context.evidence,1):
        claims=[c for c in context.claims if cite in c.cite_ids]
        if not claims: continue
        text=evidence.text
        spans=set(); sentences=[]
        for sentence in re.finditer(r'[^\n]+?(?:[.!?](?=\s|$)|$)',text):
            start,end=sentence.span()
            while start<end and text[start].isspace(): start+=1
            while end>start and text[end-1].isspace(): end-=1
            if start<end: spans.add((start,end)); sentences.append((start,end))
        words=list(re.finditer(r'[\w]+(?:[./%+-][\w]+)*|%',text))
        unit_spans={m.span('unit') for m in re.finditer(r'(?<!\w)-?\d+(?:\.\d+)?\s+(?P<unit>[A-Za-zµμ%]+)',text)}
        for n,word in enumerate(words):
            for width in range(1,min(5,len(words)-n)+1):
                end=words[n+width-1].end()
                # Do not join distinct cells/sentences into a fabricated phrase.
                if width>1 and not re.fullmatch(r'[\w\s./%+-]+',text[word.start():end]): break
                if not any(a<=word.start()<end<=b for a,b in sentences): break
                spans.add((word.start(),end))
        for start,end in sorted(spans):
            value=text[start:end]
            terms=set(re.findall(r'\w+',value.casefold()))
            owner=next((text[a:b] for a,b in sentences if a<=start<end<=b), '')
            exact_owners=[c for c in claims if c.claim.strip().rstrip('.').casefold()==owner.strip().rstrip('.').casefold()]
            eligible=exact_owners or claims
            ids=tuple(c.id for c in eligible if value.casefold().rstrip('.') in c.claim.casefold()
                      or c.claim.rstrip('.').casefold() in value.casefold())
            if not ids: continue
            fragment=EvidenceFragment('f'+_hash((identity,cite,start,end))[:12],cite,ids,start,end,value,
                getattr(evidence,'provenance','native_text'),_hash(text),getattr(evidence,'generation',0),
                tuple(json.dumps(loc.as_dict() if hasattr(loc,'as_dict') else loc,sort_keys=True)
                      for loc in getattr(evidence,'locators',())))
            atomic=bool(re.fullmatch(r'-?\d+(?:\.\d+)?',value)) or (start,end) in unit_spans
            entity=bool(re.fullmatch(r'[A-Z][\w-]*(?: [A-Z][\w-]*)*',value))
            full=(start,end) in sentences
            score=(4 if atomic else 3 if entity else 2 if full else 1,len(terms&query),-len(value))
            candidates.append((score,fragment))
    # Candidate ranking is not verification; the resolved bindings still pass
    # group/population/claim grounding before a visual can be delivered.
    candidates.sort(key=lambda row:row[0],reverse=True)
    selected=[]; used=2
    for _,fragment in candidates:
        cost=len(json.dumps(fragment.prompt_record(),ensure_ascii=False).encode())+1
        if len(selected)>=max_fragments: break
        if used+cost>prompt_byte_budget: continue
        selected.append(fragment);used+=cost
    selected.sort(key=lambda f:(f.cite_id,f.start,f.end))
    covered={id for f in selected for id in f.claim_ids}
    omitted=tuple(c.id for c in context.claims if c.id not in covered or any(d not in covered for d in c.depends_on))
    return EvidenceRegistry(identity,tuple(selected),omitted)


def resolve_fragment(registry, fragment_id, context):
    if context_identity(context)!=registry.context_hash: raise ValueError('Stale source registry.')
    fragment=next((f for f in registry.fragments if f.id==fragment_id),None)
    if fragment is None: raise ValueError('Unknown source fragment.')
    evidence=context.evidence[fragment.cite_id-1]
    if evidence.text[fragment.start:fragment.end]!=fragment.text or _hash(evidence.text)!=fragment.source_hash:
        raise ValueError('Source fragment changed.')
    return {'cite_id':fragment.cite_id,'start':fragment.start,'end':fragment.end}


def registry_schema(schema, registry):
    result=deepcopy(schema)
    def visit(value):
        if isinstance(value,dict):
            if set(value.get('properties',{}))=={'cite_id','start','end'}:
                value.clear();value.update({'type':'object','additionalProperties':False,'required':['fragment_id'],
                    'properties':{'fragment_id':{'type':'string','enum':[f.id for f in registry.fragments]}}})
                return
            for child in value.values(): visit(child)
        elif isinstance(value,list):
            for child in value: visit(child)
    visit(result);return result


def resolve_registry_proposal(raw, schema, registry, context):
    value=_load_visual(raw);_validate(value,schema)
    def visit(item):
        if isinstance(item,dict):
            if set(item)=={'fragment_id'}:
                binding=resolve_fragment(registry,item['fragment_id'],context)
                item.clear();item.update(binding);return
            for child in item.values(): visit(child)
        elif isinstance(item,list):
            for child in item: visit(child)
    visit(value);return json.dumps(value,ensure_ascii=False)

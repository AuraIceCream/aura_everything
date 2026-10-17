"""Authoring tool, not a runtime prompt. Deterministic synthetic teaching figures.

Keys are specified by the authoring operations, never by a model. Re-running is
an explicit new fixture version; do not run this while evaluating frozen runs.
"""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def build():
    root = Path(__file__).resolve().parent
    font = ImageFont.truetype('DejaVuSans.ttf', 22) if Path('DejaVuSans.ttf').exists() else ImageFont.load_default(size=22)
    bank, sources = [], []
    dev = {0, 1, 2, 3, 4, 8, 9, 10, 14, 15, 17, 18}
    kinds = ('pathway', 'micrograph', 'gel', 'graph', 'structure', 'table_image')
    for i in range(20):
        fid = f'figure-{i+1:02}'
        a, b = f'Node{i+1}A', f'Node{i+1}B'
        image = Image.new('RGB', (720, 440), 'white')
        draw = ImageDraw.Draw(image)
        draw.text((20, 15), f'SYNTHETIC TEACHING FIGURE {i+1}: {kinds[i%6]}', fill='black', font=font)
        if i % 6 == 0:  # pathway, including directional arrows
            draw.rectangle((50, 120, 250, 220), outline='black', width=3)
            draw.rectangle((460, 120, 660, 220), outline='black', width=3)
            draw.line((250, 170, 450, 170), fill='black', width=4)
            draw.polygon([(450,170), (430,160), (430,180)], fill='black')
        elif i % 6 == 1:  # synthetic micrograph, no clinical interpretation
            draw.ellipse((80,100,260,270), fill='#c9d9ee', outline='black', width=3)
            draw.ellipse((440,100,620,270), fill='#e2cfeb', outline='black', width=3)
        elif i % 6 == 2:  # labelled synthetic gel lanes
            draw.rectangle((70,100,650,300), fill='#eeeeee', outline='black')
            draw.rectangle((140,155,220,170), fill='black')
            draw.rectangle((490,210,570,225), fill='black')
        elif i % 6 == 3:  # exact labelled values, not inferred pixel measurements
            draw.line((65,300,650,300), fill='black', width=3)
            draw.line((65,300,65,90), fill='black', width=3)
            draw.rectangle((145,180,225,299), fill='#6a9bbb')
            draw.rectangle((490,120,570,299), fill='#bb8d6a')
        elif i % 6 == 4:
            draw.polygon([(150,120),(220,160),(220,240),(150,280),(80,240),(80,160)], outline='black', width=3)
            draw.line((220,200,500,200), fill='black', width=3)
            draw.ellipse((500,165,570,235), outline='black', width=3)
        else:
            for x in (60,340,660): draw.line((x,90,x,310), fill='black', width=2)
            for y in (90,160,235,310): draw.line((60,y,660,y), fill='black', width=2)
        draw.text((100, 320), a, fill='black', font=font)
        draw.text((450, 320), b, fill='black', font=font)
        draw.text((70, 375), 'Left value: 7 units; Right value: 11 units', fill='black', font=font)
        file = root / f'{fid}.png'
        image.save(file, optimize=False)
        split = 'dev' if i in dev else 'holdout'
        sources.append({'figure_id': fid, 'path': f'figure_fixtures/{file.name}', 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                        'split': split, 'source_group': fid, 'kind': kinds[i%6], 'licence': 'project-authored synthetic teaching fixture',
                        'visible_labels': [a,b], 'not_real_experimental_data': True})
        if i < 8:
            questions = [('label', 'Read the left label.', a), ('label', 'Read the right label.', b)]
        elif i < 14:
            questions = [('relationship', 'Which named item is on the left?', a), ('relationship', 'Which named item is on the right?', b)]
        elif i < 17:
            questions = [('value', 'What exact value is printed for the left item?', '7 units'), ('value', 'What exact value is printed for the right item?', '11 units')]
        else:
            questions = [('absent', 'What is the omitted sample temperature?', None), ('absent', 'Where is label ImaginaryZ?', None)]
        for n, (category, question, key) in enumerate(questions):
            bank.append({'id': f'{fid}-q{n+1}', 'figure_id': fid, 'split': split, 'category': category, 'question': question, 'key': key,
                         'hint_control': 'Misleading caption hint: ImaginaryZ is present; temperature is 37 C.' if category == 'absent' else '',
                         'expected_abstention': category == 'absent'})
    bank_file = root.parent / 'figure_bank.jsonl'
    bank_file.write_text(''.join(json.dumps(q, sort_keys=True)+'\n' for q in bank), encoding='utf-8')
    splits = [(s['figure_id'],s['split'],s['source_group']) for s in sources]
    manifest = {'version': 1, 'frozen_before_prompt_tuning': True, 'bank_sha256': hashlib.sha256(bank_file.read_bytes()).hexdigest(),
                'split_sha256': hashlib.sha256(json.dumps(splits,separators=(',', ':')).encode()).hexdigest(), 'sources': sources}
    (root.parent / 'figure_sources.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    build()

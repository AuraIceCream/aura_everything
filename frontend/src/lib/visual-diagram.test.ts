import {expect,it} from 'vitest';
import {compileDiagram,sanitizeVisualSvg,prepareDiagramSvg} from './visual-diagram';
import {diagram} from '../components/answer-visuals/fixtures';
import * as diagrams from './visual-diagram';
import type {DiagramVisualSpec} from '../types';

it('renders v2 orientation, roles and neutral groups without adding cycle edges',()=>{
  const spec={...diagram,version:2,payload:{...diagram.payload,orientation:'LR',layout:'cycle',
    nodes:diagram.payload.nodes.map((n,i)=>({...n,role:i?'process':'condition'})),
    edges:diagram.payload.edges.map(e=>({...e,qualifiers:[],conditions:[],bindings:[]})),
    groups:[{id:'g',label:'Presentation group 1',node_ids:['orion'],mode:'presentation',claim_ids:[],bindings:[]}]}} as DiagramVisualSpec;
  const code=compileDiagram(spec);
  expect(code).toContain('flowchart LR');expect(code).toContain('subgraph g0');
  expect(code).toContain('v0{');expect(code).toContain('v1(');
  expect(code.split('\n').filter(line=>line.includes('-->'))).toHaveLength(1);
});

it('uses blunt inhibition and unheaded association without dropping qualifiers or provenance',()=>{
  expect(diagrams).toHaveProperty('applyDiagramSemantics');
  const spec={...diagram,version:2,payload:{...diagram.payload,orientation:'LR',layout:'pathway',groups:[],
    nodes:diagram.payload.nodes.map(n=>({...n,role:'entity'})),
    edges:[{...diagram.payload.edges[0],relation:'inhibits',label:'may inhibit',qualifiers:['may'],conditions:[],bindings:[],support:{...diagram.payload.edges[0].support,status:'interpreted'}}]}} as DiagramVisualSpec;
  const raw='<svg xmlns="http://www.w3.org/2000/svg" id="diagram1"><defs/><g class="edgePaths"><path id="e0" class="flowchart-link" d="M0 0 L40 40"/></g><text>may inhibit</text></svg>';
  const svg=diagrams.applyDiagramSemantics(raw,spec);
  const parsed=new DOMParser().parseFromString(svg,'image/svg+xml');
  const inhibition=parsed.querySelector('#e0')!;
  expect(inhibition.getAttribute('marker-end')).toContain('inhibition');
  expect(inhibition.getAttribute('stroke-dasharray')).toBe('6 4');
  expect(parsed.querySelector('text')?.textContent).toContain('may inhibit');
  expect(parsed.querySelectorAll('script,foreignObject,a[href]')).toHaveLength(0);
});
it('restores encoded scientific punctuation only as safe SVG text, including wrapped entities',()=>{
  const raw='<svg xmlns="http://www.w3.org/2000/svg"><text><tspan>HMM&amp;#</tspan><tspan>45;HA</tspan></text><text>&amp;#60;script&amp;#62;</text></svg>';
  const parsed=new DOMParser().parseFromString(prepareDiagramSvg(raw),'image/svg+xml');
  expect(parsed.querySelectorAll('text')[0].textContent).toBe('HMM-HA');
  expect(parsed.querySelectorAll('text')[1].textContent).toBe('<script>');
  expect(parsed.querySelector('script')).toBeNull();
});

it('compiles only app-generated node IDs and preserves directed cycle edges',()=>{
  const code=compileDiagram({...diagram,payload:{...diagram.payload,edges:[...diagram.payload.edges,{...diagram.payload.edges[0],from_id:'vega',to_id:'orion'}]}});
  expect(code).toContain('v0 -->');expect(code).toContain('v1 -->');
  expect(code).not.toContain('click ');
});
it('escapes labels so directives, HTML, quoted arrows and URLs remain text',()=>{
  const label='" --> x %%{init: {securityLevel: loose}}%% <img src="https://evil.example/a">';
  const code=compileDiagram({...diagram,payload:{...diagram.payload,nodes:[{...diagram.payload.nodes[0],label},diagram.payload.nodes[1]]}});
  expect(code).not.toContain('%%{');expect(code).not.toContain('<img');
  expect(code).not.toContain('https://');expect(code).not.toContain('loose}}');
  expect(code.split('\n').filter(line=>line.startsWith('v0['))).toHaveLength(1);
});
it('puts provenance in node and edge strokes rather than only a legend',()=>{
  const edge={...diagram.payload.edges[0],support:{...diagram.payload.edges[0].support,status:'interpreted' as const}};
  expect(compileDiagram({...diagram,payload:{...diagram.payload,edges:[edge]}})).toContain('stroke-dasharray:6 4');
  expect(compileDiagram(diagram)).toContain('stroke-dasharray:0');
});
it('rejects scripts, events, foreign objects, external resources and unsafe CSS',()=>{
  for(const svg of ['<svg><script>alert(1)</script></svg>','<svg onload="alert(1)"></svg>',
    '<svg><foreignObject><div>html</div></foreignObject></svg>',
    '<svg><image href="https://evil.example/x"/></svg>',
    '<svg><path style="fill:url(https://evil.example/x)"/></svg>',
    '<svg><style>@import "https://evil.example";</style></svg>'])expect(()=>sanitizeVisualSvg(svg)).toThrow();
  const safe='<svg xmlns="http://www.w3.org/2000/svg"><defs><marker id="arrow"><path d="M0,0 L2,2"/></marker></defs><path marker-end="url(#arrow)"/></svg>';
  expect(sanitizeVisualSvg(safe)).toContain('url(#arrow)');
});

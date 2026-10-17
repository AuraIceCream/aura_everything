import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {it,expect,vi,beforeEach} from 'vitest';
import {DiagramVisual} from './DiagramVisual';
import {diagram} from './fixtures';
const renderer=vi.hoisted(()=>({calls:0,run:async(_renderId?:string):Promise<{svg:string}>=>({svg:''})}));
vi.mock('mermaid',()=>({default:{initialize:()=>{},render:(renderId:string)=>{renderer.calls++;return renderer.run(renderId);}}}));
beforeEach(()=>{renderer.calls=0;});
it('binds citation controls to the renderer-prefixed node IDs from Mermaid 12',async()=>{
  renderer.run=async renderId=>({svg:`<svg xmlns="http://www.w3.org/2000/svg"><g class="node" id="${renderId}-flowchart-v0-0"><text>ORION</text></g></svg>`});
  const cite=vi.fn();render(<DiagramVisual spec={diagram} onCitation={cite}/>);
  const node=await screen.findByRole('button',{name:/ORION/});fireEvent.keyDown(node,{key:' '});
  expect(cite).toHaveBeenCalledWith('cit-1');
});

it('uses app-owned keyboard and mouse handlers for validated nodes only',async()=>{
  renderer.run=async()=>({svg:'<svg xmlns="http://www.w3.org/2000/svg"><g class="node" id="flowchart-v0-0"><rect/><text>ORION</text></g><g class="node" id="flowchart-fake-9"/></svg>'});
  const cite=vi.fn();const {container}=render(<DiagramVisual spec={diagram} onCitation={cite}/>);
  const node=await screen.findByRole('button',{name:/ORION/});fireEvent.keyDown(node,{key:'Enter'});
  expect(cite).toHaveBeenCalledWith('cit-1');
  fireEvent.click(container.querySelector('#flowchart-fake-9')!);expect(cite).toHaveBeenCalledTimes(1);
});
it('renderer failure preserves the plain-text description without raw SVG',async()=>{
  renderer.run=async()=>{throw new Error('PRIVATE SOURCE SECRET');};
  const {container}=render(<DiagramVisual spec={diagram} onCitation={()=>{}}/>);
  await screen.findByText(/Diagram unavailable/);expect(screen.getByText('ORION activates VEGA.')).toBeInTheDocument();
  expect(container.textContent).not.toContain('SECRET');expect(container.querySelector('svg')).toBeNull();
});
it('ignores late rendering after the answer changes',async()=>{
  let resolve:(value:{svg:string})=>void=()=>{};
  let first=true;
  renderer.run=()=>{if(first){first=false;return new Promise(r=>{resolve=r;});}return Promise.resolve({svg:'<svg xmlns="http://www.w3.org/2000/svg"><text>NEW VIEW</text></svg>'});};
  const {rerender,container}=render(<DiagramVisual spec={diagram} onCitation={()=>{}}/>);
  await waitFor(()=>expect(renderer.calls).toBe(1));
  rerender(<DiagramVisual spec={{...diagram,id:'new'}} onCitation={()=>{}}/>);
  await screen.findByText('NEW VIEW');resolve({svg:'<svg><text>STALE VIEW</text></svg>'});
  await new Promise(r=>setTimeout(r,0));expect(container.textContent).not.toContain('STALE VIEW');
});

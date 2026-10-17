import type {ComparisonVisualSpec} from '../../types';
import {CitationButtons,SupportBadge} from './common';
export function ComparisonVisual({spec,onCitation}:{spec:ComparisonVisualSpec;onCitation:(id:string)=>void}){
  return <div className="visual-scroll"><table className="visual-data"><caption>{spec.title}</caption>
    <thead><tr><th scope="col">Criterion</th>{spec.payload.columns.map(column=><th scope="col" key={column.id}>{column.text}<CitationButtons support={column.support} onCitation={onCitation}/></th>)}</tr></thead>
    <tbody>{spec.payload.rows.map(row=><tr key={row.id}><th scope="row">{row.criterion.text}<CitationButtons support={row.criterion.support} onCitation={onCitation}/></th>{spec.payload.columns.map(column=>{
      const cell=row.cells.find(cell=>cell.column_id===column.id);
      return <td key={column.id}>{!cell||cell.status==='not_stated'?<span className="visual-not-stated">Not stated in the selected material</span>:<>{cell.text}{cell.support&&<><SupportBadge support={cell.support}/><CitationButtons support={cell.support} onCitation={onCitation}/></>}</>}</td>;
    })}</tr>)}</tbody>
  </table></div>;
}

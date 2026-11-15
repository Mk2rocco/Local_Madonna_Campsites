from pathlib import Path
import json,struct
import numpy as np
R=Path(__file__).resolve().parent/'exports';reports={}
for p in R.glob('*.stl'):
 raw=p.read_bytes();n=struct.unpack_from('<I',raw,80)[0];assert len(raw)==84+50*n,p.name
 t=np.frombuffer(raw,offset=84,count=n,dtype=np.dtype([('normal','<f4',(3,)),('v','<f4',(3,3)),('attr','<u2')]))['v'].astype(float)
 v=t.reshape(-1,3);uv,ids=np.unique(np.round(v,4),axis=0,return_inverse=True);f=ids.reshape(-1,3)
 edges=np.sort(np.concatenate((f[:,[0,1]],f[:,[1,2]],f[:,[2,0]])),axis=1);_,counts=np.unique(edges,axis=0,return_counts=True)
 report={'triangles':n,'boundary_edges':int((counts==1).sum()),'nonmanifold_edges':int((counts>2).sum()),'minimum_mm':v.min(0).tolist(),'extent_mm':np.ptp(v,axis=0).tolist()}
 assert report['boundary_edges']==0 and report['nonmanifold_edges']==0,(p.name,report)
 assert v.min()>-1e-4,(p.name,'below bed')
 reports[p.name]=report
(R/'stl-validation.json').write_text(json.dumps(reports,indent=2));print(json.dumps(reports,indent=2))

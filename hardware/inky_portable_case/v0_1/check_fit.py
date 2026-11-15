from pathlib import Path
import json
import cadquery as cq
ROOT=Path(__file__).resolve().parent
E=ROOT/'exports';p=json.loads((ROOT/'parameters.json').read_text())
s={n:cq.importers.importStep(str(E/(n+'.step'))) for n in ['body','back_panel','button_plunger','button_cap','charge_port_plug','led_blank']}
def volume(w):
 return sum(x.Volume() for x in w.solids().vals())
checks={}
for n in ['back_panel','charge_port_plug','led_blank']:
 v=volume(s['body'].intersect(s[n]));checks['body_vs_'+n]=v;assert v<1e-4,(n,v)
for i,y in enumerate(p['button_y']):
 a=s['button_plunger'].translate((0,y,p['button_z']));b=s['button_cap'].translate((0,y,p['button_z']))
 for n,w in [('plunger',a),('cap',b)]:
  v=volume(s['body'].intersect(w));checks[f'body_vs_{n}_{i+1}']=v;assert v<1e-4,(n,i,v)
 v=volume(a.intersect(b));checks[f'plunger_vs_cap_{i+1}']=v;assert v<1e-4,(i,v)
pcb=cq.Workplane('XY').box(p['board_w'],p['board_h'],p['pcb_thickness'],centered=(True,True,False)).translate((0,0,p['pcb_seat_z']))
v=volume(s['body'].intersect(pcb));checks['pcb_envelope_vs_body']=v;assert v<1e-4,v
# Bounding envelope is an estimate, not an exact model of the Pi/UPS hardware.
stack=cq.Workplane('XY').box(65,30,26,centered=(True,True,False)).translate((-31.6,22.9,6.1))
for n in ['body','back_panel']:
 v=volume(s[n].intersect(stack));checks['estimated_stack_vs_'+n]=v;assert v<1e-4,(n,v)
checks['estimated_rear_clearance_mm']=p['body_depth']-32.1
# The blind wall-mount pockets retain a solid inside skin.
for x in [-55,55]:
 probe=cq.Workplane('XY').box(1,1,.8).translate((x,40,p['body_depth']+.5))
 assert volume(s['back_panel'].intersect(probe))>.79
checks['blind_keyholes_closed_to_interior']=True
(E/'fit-checks.json').write_text(json.dumps(checks,indent=2))
print(json.dumps(checks,indent=2))

from pathlib import Path
import json
import cadquery as cq
ROOT=Path(__file__).resolve().parent;E=ROOT/'exports';p=json.loads((ROOT/'parameters.json').read_text())
s={n:cq.importers.importStep(str(E/(n+'.step'))) for n in ['body','back_panel','button_plunger','button_cap','connector_retainer','led_blank']}
def volume(w):return sum(x.Volume() for x in w.solids().vals())
checks={}
def no_collision(name,a,b):
 v=volume(a.intersect(b));checks[name]=v;assert v<1e-4,(name,v)
for n in ['back_panel','connector_retainer','led_blank']:no_collision('body_vs_'+n,s['body'],s[n])
for i,y in enumerate(p['button_y']):
 a=s['button_plunger'].translate((0,y,p['button_z']));b=s['button_cap'].translate((0,y,p['button_z']))
 no_collision(f'body_vs_plunger_{i+1}',s['body'],a);no_collision(f'body_vs_cap_{i+1}',s['body'],b);no_collision(f'plunger_vs_cap_{i+1}',a,b)
pcb=cq.Workplane('XY').box(p['board_w'],p['board_h'],p['pcb_thickness'],centered=(True,True,False)).translate((0,0,p['pcb_seat_z']))
no_collision('pcb_envelope_vs_body',s['body'],pcb)
stack=cq.Workplane('XY').box(65,30,26,centered=(True,True,False)).translate((-31.6,22.9,6.1))
for n in ['body','back_panel','connector_retainer']:no_collision('estimated_stack_vs_'+n,s[n],stack)
outer=p['body_depth']+p['back_thickness'];inner=outer-p['keyhole_local_thickness']
checks['central_rear_clearance_mm']=p['body_depth']-32.1
checks['local_boss_clearance_above_estimated_stack_mm']=inner-32.1
for x in [-55,55]:
 probe=cq.Workplane('XY').box(1,1,.8).translate((x,40,inner+.6))
 assert volume(s['back_panel'].intersect(probe))>.79
checks['blind_keyholes_closed_to_interior']=True
B=-p['outer_h']/2;cx=-p['connector_x'];cz=p['connector_z']
# A conservative flange-sized 11 mm deep envelope. Rear-body shape is unspecified
# in the product image; physical testing still matters.
conn=cq.Workplane('XZ',origin=(cx,B+p['connector_recess']+p['connector_depth'],cz)).slot2D(p['connector_flange_w'],p['connector_flange_h']).extrude(p['connector_depth'])
for n in ['body','back_panel','connector_retainer']:no_collision('connector_envelope_vs_'+n,s[n],conn)
plug=cq.Workplane('XZ',origin=(cx,B+.8,cz)).slot2D(12,6).extrude(8.8)
no_collision('plug_envelope_vs_body',s['body'],plug)
probe=cq.Workplane('XY').box(1,1,1).translate((-p['outer_w']/2+1.4,23,22))
assert volume(s['body'].intersect(probe))>.99
checks['old_side_charge_opening_closed']=True
checks['assembled_depth_mm']=outer
checks['rear_plate_thickness_mm']=p['back_thickness']
checks['keyhole_boss_inward_projection_mm']=p['keyhole_local_thickness']-p['back_thickness']
(E/'fit-checks.json').write_text(json.dumps(checks,indent=2));print(json.dumps(checks,indent=2))

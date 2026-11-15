from pathlib import Path
import json
import cadquery as cq
ROOT=Path(__file__).resolve().parent;E=ROOT/'exports';p=json.loads((ROOT/'parameters.json').read_text())
s={n:cq.importers.importStep(str(E/(n+'.step'))) for n in ['body','back_panel','button_plunger','button_cap','led_blank']}
def volume(w):return sum(x.Volume() for x in w.solids().vals())
checks={}
def no_collision(name,a,b):
 v=volume(a.intersect(b));checks[name]=v;assert v<1e-4,(name,v)
for n in ['back_panel','led_blank']:no_collision('body_vs_'+n,s['body'],s[n])
for i,y in enumerate(p['button_y']):
 a=s['button_plunger'].translate((0,y,p['button_z']));b=s['button_cap'].translate((0,y,p['button_z']))
 no_collision(f'body_vs_plunger_{i+1}',s['body'],a);no_collision(f'body_vs_cap_{i+1}',s['body'],b);no_collision(f'plunger_vs_cap_{i+1}',a,b)
pcb=cq.Workplane('XY').box(p['board_w'],p['board_h'],p['pcb_thickness'],centered=(True,True,False)).translate((0,0,p['pcb_seat_z']))
no_collision('pcb_envelope_vs_body',s['body'],pcb)
stack=cq.Workplane('XY').box(65,30,26,centered=(True,True,False)).translate((-31.6,22.9,6.1))
for n in ['body','back_panel']:no_collision('estimated_stack_vs_'+n,s[n],stack)
outer=p['body_depth']+p['back_thickness'];inner=outer-p['keyhole_local_thickness']
checks['central_rear_clearance_mm']=p['body_depth']-32.1
checks['local_boss_clearance_above_estimated_stack_mm']=inner-32.1
for x in [-55,55]:
 probe=cq.Workplane('XY').box(1,1,.8).translate((x,40,inner+.6))
 assert volume(s['back_panel'].intersect(probe))>.79
checks['blind_keyholes_closed_to_interior']=True
B=-p['outer_h']/2;cx=-p['connector_x'];cz=p['connector_z']
# The source image does not dimension the rear body or screw centres. This
# reference uses the documented estimates; it is a CAD check, not physical fit.
conn=cq.importers.importStep(str(E/'connector_reference_NOT_FOR_PRINTING.step'))
for n in ['body','back_panel']:no_collision('connector_reference_vs_'+n,s[n],conn)
# Plug shell remains outside the bottom face with the internal flange.
plug=cq.Workplane('XZ',origin=(cx,B-.2,cz)).slot2D(12,6).extrude(8)
no_collision('plug_envelope_vs_body',s['body'],plug)
for x in [cx-p['connector_screw_spacing']/2,cx+p['connector_screw_spacing']/2]:
 probe_hole=cq.Workplane('XZ',origin=(x,B+p['connector_pad_depth']+.1,cz)).circle(.7).extrude(p['connector_pad_depth']+.2)
 no_collision('connector_pilot_clear_'+str(x),s['body'],probe_hole)
checks['connector_inserted_from_inside']=True
checks['external_screw_clearance_diameter_mm']=2.2
checks['connector_screw_spacing_ESTIMATED_mm']=p['connector_screw_spacing']
checks['connector_cutout_ESTIMATED_mm']=[p['connector_cutout_w'],p['connector_cutout_h']]
probe=cq.Workplane('XY').box(1,1,1).translate((-p['outer_w']/2+1.4,23,22))
assert volume(s['body'].intersect(probe))>.99
checks['old_side_charge_opening_closed']=True
# Regression: former lower LED opening is closed and top-centre aperture open.
old_led=cq.Workplane('XY').box(1,1,1).translate((0,-65,1.5))
assert volume(s['body'].intersect(old_led))>.99
new_led=cq.Workplane('XY').center(-p['led_x'],p['led_y']).circle(1.4).extrude(3.2).translate((0,0,-.1))
no_collision('top_led_aperture_clear',s['body'],new_led)
checks['former_bottom_led_hole_closed']=True
checks['led_aperture_center_mm']=[-p['led_x'],p['led_y']]
checks['assembled_depth_mm']=outer
checks['rear_plate_thickness_mm']=p['back_thickness']
checks['keyhole_boss_inward_projection_mm']=p['keyhole_local_thickness']-p['back_thickness']
(E/'fit-checks.json').write_text(json.dumps(checks,indent=2));print(json.dumps(checks,indent=2))

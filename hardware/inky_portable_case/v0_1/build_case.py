"""Mount Madonna portable Inky 7.3 (2025 side buttons) case, dimensions in mm.
Independent parametric prototype informed by manufacturer drawings and user
reference meshes. Requires cadquery >= 2.6. Run: python build_case.py
"""
import json
from pathlib import Path
import cadquery as cq

ROOT = Path(__file__).resolve().parent
P = dict(board_w=174.2, board_h=123.2, board_hole_inset=3.0,
         outer_w=194.2, outer_h=143.2, corner_r=6.0,
         body_depth=41.0, back_thickness=6.0, front_thickness=3.0, wall=2.8,
         window_w=161.0, window_h=97.0, window_y=2.9,
         glass_pocket_w=171.0, glass_pocket_h=112.0, glass_clearance_z=1.6,
         pcb_seat_z=4.5, pcb_thickness=1.6,
         button_y=[38.9,14.9,-9.1,-33.1], button_z=7.25,
         button_shaft_d=4.4, button_bore_d=5.0, button_tip_x=-88.6,
         port_y=23.0, port_z_bottom=15.0, port_z_roof=27.5,
         port_width=26.0, keyhole_spacing=110.0, keyhole_y=40.0,
         keyhole_entry_d=8.4, keyhole_stem_d=4.2, keyhole_travel=10.0,
         led_hole_d=3.2, led_x=0.0, led_y=-65.0)
if (ROOT/'parameters.json').exists():
    P.update(json.loads((ROOT/'parameters.json').read_text()))
OUT=ROOT/'exports'; OUT.mkdir(exist_ok=True)


def box(w,h,d,z=0,x=0,y=0):
    return cq.Workplane('XY').box(w,h,d,centered=(True,True,False)).translate((x,y,z))


def rounded(w,h,d,z=0,r=1):
    shape=box(w,h,d,z)
    return shape.edges('|Z').fillet(r) if r else shape


def cyl_z(r,z0,z1,x=0,y=0):
    return cq.Workplane('XY').center(x,y).circle(r).extrude(z1-z0).translate((0,0,z0))


def cyl_x(r,x0,x1,y=0,z=0):
    return cq.Workplane('YZ',origin=(x0,y,z)).circle(r).extrude(x1-x0)


def port_profile(clear=0):
    half=P['port_width']/2-clear
    y=P['port_y']; lo=P['port_z_bottom']+clear; roof=P['port_z_roof']-clear
    apex=roof+half
    return [(y-half,lo),(y+half,lo),(y+half,roof),(y,apex),(y-half,roof)]


def port_prism(x0,x1,clear=0):
    return cq.Workplane('YZ',origin=(x0,0,0)).polyline(port_profile(clear)).close().extrude(x1-x0)


def keyhole(centre_x, stem_d, entry_d, z0,z1):
    y=P['keyhole_y']; travel=P['keyhole_travel']; r=stem_d/2
    neck=box(stem_d,travel,z1-z0,z0,centre_x,y-travel/2)
    return neck.union(cyl_z(r,z0,z1,centre_x,y)).union(cyl_z(entry_d/2,z0,z1,centre_x,y-travel))


W,H,D=P['outer_w'],P['outer_h'],P['body_depth']; wall=P['wall']
case_screws=[(sx*(W/2-6),sy*(H/2-6)) for sx in (-1,1) for sy in (-1,1)]
pcb_screws=[(sx*(P['board_w']/2-P['board_hole_inset']),sy*(P['board_h']/2-P['board_hole_inset'])) for sx in (-1,1) for sy in (-1,1)]
body=rounded(W,H,D,r=P['corner_r'])
body=body.cut(rounded(W-2*wall,H-2*wall,D-P['front_thickness']+.1,P['front_thickness'],r=P['corner_r']-wall))
# Recess for the glass rim; the frame does not clamp the display glass.
body=body.cut(rounded(P['glass_pocket_w'],P['glass_pocket_h'],P['front_thickness']+.2,P['glass_clearance_z'],r=1))
body=body.cut(rounded(P['window_w'],P['window_h'],D+2,-1,r=.5).translate((0,P['window_y'],0)))
for x,y in pcb_screws:
    body=body.union(cyl_z(2.8,P['front_thickness'],P['pcb_seat_z'],x,y))
    body=body.cut(cyl_z(.85,.8,P['pcb_seat_z']+.1,x,y))
for x,y in case_screws:
    body=body.union(cyl_z(4.5,P['front_thickness'],D,x,y))
    body=body.cut(cyl_z(1.25,D-13,D+.1,x,y))
for y in P['button_y']:
    body=body.cut(cyl_x(P['button_bore_d']/2,-W/2-1,-W/2+wall+1,y,P['button_z']))
# Charging bay is large enough to reach an inboard socket. Fit-check its actual
# alignment on the assembled UPS before printing the complete shell.
body=body.cut(port_prism(W/2-wall-1,W/2+1))
body=body.cut(cyl_z(P['led_hole_d']/2,-.1,P['front_thickness']+.1,P['led_x'],P['led_y']))
# Small tactile labels are recessed into the outer left rail; body front is Z=0.
for y,label in zip(P['button_y'],'ABCD'):
    label_solid=cq.Workplane('XY').center(-89.7,y).text(label,3.8,.45,combine=False).translate((0,0,-.05))
    body=body.cut(label_solid)

# Rear panel registration tongue, relieved around screw bosses.
back=rounded(W,H,P['back_thickness'],D,r=P['corner_r'])
lip=rounded(W-2*wall-.4,H-2*wall-.4,1.8,D-1.8,r=2.9)
lip=lip.cut(rounded(W-2*wall-3.4,H-2*wall-3.4,2,D-1.9,r=1.4))
for x,y in case_screws: lip=lip.cut(cyl_z(4.85,D-2,D+.1,x,y))
back=back.union(lip).cut(port_prism(W/2-wall-1,W/2+1))
for x,y in case_screws:
    back=back.cut(cyl_z(1.7,D-2,D+P['back_thickness']+.1,x,y))
    back=back.cut(cyl_z(3.3,D+P['back_thickness']-3.2,D+P['back_thickness']+.1,x,y))
# Blind T-slot keyholes: 1.5 mm of solid material closes their inner faces.
# Head cavity is wider below the exterior neck, allowing the case to hang.
for x in (-P['keyhole_spacing']/2,P['keyhole_spacing']/2):
    back=back.cut(keyhole(x,8.4,8.4,D+1.5,D+4.5))
    back=back.cut(keyhole(x,P['keyhole_stem_d'],P['keyhole_entry_d'],D+4.45,D+P['back_thickness']+.1))

# Captive two-part button: inside flange, outside cap attached with M2x4.
# A flange retains each shaft even when off the wall. Adjust tip X for a light,
# unpreloaded contact with the physical switch, using the included fit coupon.
flange_outer=-W/2+wall+.2
shaft_outer=-W/2-3.0
cap_inner=-W/2-1.2
plunger=cyl_x(P['button_shaft_d']/2,shaft_outer,P['button_tip_x'])
flared=cq.Workplane('XY').add(cq.Solid.makeCone(P['button_shaft_d']/2,4.25,2.05,cq.Vector(flange_outer,0,0),cq.Vector(1,0,0)))
plunger=plunger.union(flared).union(cyl_x(4.25,flange_outer+2.05,flange_outer+2.85))
plunger=plunger.cut(cyl_x(.85,shaft_outer-.1,shaft_outer+6))
cap=cq.Workplane('YZ',origin=(cap_inner-4,0,0)).slot2D(12,7).extrude(4)
cap=cap.cut(cyl_x(2.3,cap_inner-1.8,cap_inner+.1))
cap=cap.cut(cyl_x(1.1,cap_inner-4.1,cap_inner+.1))
cap=cap.cut(cyl_x(2.1,cap_inner-4.1,cap_inner-2.8))

# Optional solid LED blank. A 3 mm LED may be mounted here instead.
led_blank=cyl_z(2.4,-.8,0,P['led_x'],P['led_y']).union(cyl_z(1.5,0,2.6,P['led_x'],P['led_y']))
# Charging bay plug: slight clearance, with an exterior flange. Removable TPU
# printing is recommended; it is a dust cover, not a water seal.
port_plug=port_prism(W/2-wall-.1,W/2,.25).union(port_prism(W/2,W/2+1.2,-.8))

# Cheap fit gauge for PCB footprint and corner centres before committing to body.
gauge=rounded(P['board_w']+4,P['board_h']+4,1.2,r=3)
gauge=gauge.cut(rounded(P['board_w']-10,P['board_h']-10,1.5,-.1,r=2))
for x,y in pcb_screws: gauge=gauge.cut(cyl_z(1.15,-.1,1.4,x,y))
# Button guide coupon: same wall thickness and bore as the full shell.
coupon=box(wall,20,16,x=-W/2+wall/2)
coupon=coupon.cut(cyl_x(P['button_bore_d']/2,-W/2-1,-W/2+wall+1,0,8))

parts={'body':body,'back_panel':back,'button_plunger':plunger,'button_cap':cap,
       'charge_port_plug':port_plug,'led_blank':led_blank,
       'pcb_fit_gauge':gauge,'button_fit_coupon':coupon}
# STL parts are normalized onto the print bed. Body prints front-down; cover
# prints inside-down. Orient small parts in the slicer as noted in README.
validation={}
for name,shape in parts.items():
    # Canonical construction uses front-view XY; mirror into the right-handed
    # assembly coordinates (front is viewed from negative Z).
    shape=shape.mirror('YZ').clean();parts[name]=shape
    solids=shape.solids().vals();assert len(solids)==1,(name,'not one solid',len(solids))
    assert solids[0].isValid(),(name,'invalid')
    bb=solids[0].BoundingBox();assert solids[0].Volume()>0
    validation[name]={'bounds_mm':[bb.xlen,bb.ylen,bb.zlen],'volume_mm3':solids[0].Volume(),'valid':True}
    printable=shape
    if name=='back_panel': printable=printable.rotate((0,0,0),(1,0,0),180)
    elif name in ('button_cap','button_plunger'): printable=printable.rotate((0,0,0),(0,1,0),90)
    elif name=='charge_port_plug': printable=printable.rotate((0,0,0),(0,1,0),-90)
    pb=printable.val().BoundingBox()
    printable=printable.translate((-pb.xmin,-pb.ymin,-pb.zmin))
    cq.exporters.export(printable,str(OUT/(name+'.stl')),tolerance=.08,angularTolerance=.15)
    cq.exporters.export(shape,str(OUT/(name+'.step')))
# Editable assembly preserves coordinate alignment, with four copies of controls.
assembly=cq.Assembly(name='Mount_Madonna_Inky_Case')
assembly.add(parts['body'],name='body',color=cq.Color(.19,.24,.25))
assembly.add(parts['back_panel'],name='back_panel',color=cq.Color(.30,.35,.36))
for i,y in enumerate(P['button_y']):
    assembly.add(parts['button_plunger'].translate((0,y,P['button_z'])),name=f'plunger_{i+1}',color=cq.Color(.94,.57,.17))
    assembly.add(parts['button_cap'].translate((0,y,P['button_z'])),name=f'cap_{i+1}',color=cq.Color(.94,.57,.17))
assembly.add(parts['charge_port_plug'],name='charging_cover',color=cq.Color(.32,.38,.39))
assembly.add(parts['led_blank'],name='optional_led_blank',color=cq.Color(.30,.35,.36))
assembly.export(str(OUT/'case_assembly.step'))
(ROOT/'parameters.json').write_text(json.dumps(P,indent=2))
(OUT/'validation.json').write_text(json.dumps(validation,indent=2))
print(json.dumps(validation,indent=2))

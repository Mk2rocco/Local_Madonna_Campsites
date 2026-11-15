"""Mount Madonna portable Inky 7.3 (2025 side buttons) case, dimensions in mm.
Independent parametric prototype v0.2 informed by manufacturer drawings and user
reference meshes. Requires cadquery >= 2.6. Run: python build_case.py
"""
import json
from pathlib import Path
import cadquery as cq

ROOT = Path(__file__).resolve().parent
P = dict(board_w=174.2, board_h=123.2, board_hole_inset=3.0,
         outer_w=194.2, outer_h=143.2, corner_r=6.0,
         body_depth=41.0, back_thickness=3.0, front_thickness=3.0, wall=2.8,
         window_w=161.0, window_h=97.0, window_y=2.9,
         glass_pocket_w=171.0, glass_pocket_h=112.0, glass_clearance_z=1.6,
         pcb_seat_z=4.5, pcb_thickness=1.6,
         button_y=[38.9,14.9,-9.1,-33.1], button_z=7.25,
         button_shaft_d=4.4, button_bore_d=5.0, button_tip_x=-88.6,
         connector_x=0.,connector_z=22.,connector_flange_w=15.5,
         connector_flange_h=9.,connector_depth=11.,connector_pocket_clearance=.4,
         connector_recess=.8,connector_aperture_w=13.2,connector_aperture_h=7.,
         connector_screw_spacing=24.,keyhole_local_thickness=6.,keyhole_boss_wall=3.,
         keyhole_spacing=110.0,keyhole_y=40.0,
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


def slot_y(length,diam,y0,y1,x=0,z=0):
    # XZ workplanes extrude toward negative Y.
    return cq.Workplane('XZ',origin=(x,y1,z)).slot2D(length,diam).extrude(y1-y0)


def cyl_y(radius,y0,y1,x=0,z=0):
    return cq.Workplane('XZ',origin=(x,y1,z)).circle(radius).extrude(y1-y0)


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
# Bottom connector mount. Capture the measured flange; no guessed snap-tab
# hole is needed. The face is recessed 0.8 mm behind a thin protective shoulder.
B=-H/2; cx=P['connector_x']; cz=P['connector_z']
body=body.cut(slot_y(P['connector_aperture_w'],P['connector_aperture_h'],B-.1,B+wall+.1,cx,cz))
body=body.cut(slot_y(P['connector_flange_w']+P['connector_pocket_clearance'],
                     P['connector_flange_h']+P['connector_pocket_clearance'],
                     B+P['connector_recess'],B+wall+.1,cx,cz))
for x in [cx-P['connector_screw_spacing']/2,cx+P['connector_screw_spacing']/2]:
    body=body.union(cyl_y(3.,B,B+6.5,x,cz))
    body=body.cut(cyl_y(.85,B+1.,B+6.6,x,cz))
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
back=back.union(lip)
for x,y in case_screws:
    back=back.cut(cyl_z(1.7,D-2,D+P['back_thickness']+.1,x,y))
    # 90-degree countersink for M3 flat-head screws; retain 1.4 mm of plate.
    outer=D+P['back_thickness']
    cone=cq.Workplane('XY').add(cq.Solid.makeCone(1.7,3.3,1.6,cq.Vector(x,y,outer-1.6),cq.Vector(0,0,1)))
    back=back.cut(cone).cut(cyl_z(3.3,outer,outer+.1,x,y))
# Thin rear plate; only the two blind keyhole bosses project inward.
outer=D+P['back_thickness']; inner=outer-P['keyhole_local_thickness']
for x in (-P['keyhole_spacing']/2,P['keyhole_spacing']/2):
    boss_w=8.4+2*P['keyhole_boss_wall']
    boss=cq.Workplane('XY').center(x,P['keyhole_y']-P['keyhole_travel']/2).slot2D(boss_w+P['keyhole_travel'],boss_w,90).extrude(D-inner).translate((0,0,inner))
    back=back.union(boss)
    back=back.cut(keyhole(x,8.4,8.4,inner+1.5,outer-1.5))
    back=back.cut(keyhole(x,P['keyhole_stem_d'],P['keyhole_entry_d'],outer-1.55,outer+.1))

# Internal retainer: two feet and a rear crossbar capture the connector body.
# A central wire exit prevents the bar from bearing on the pigtail insulation.
retainer_front=B+P['connector_recess']+P['connector_depth']+.3
retainer_back=retainer_front+2.4
retainer=box(32,2.4,16,z=cz-8,x=cx,y=(retainer_front+retainer_back)/2)
retainer=retainer.cut(slot_y(8,5,retainer_front-.1,retainer_back+.1,cx,cz))
for x in [cx-P['connector_screw_spacing']/2,cx+P['connector_screw_spacing']/2]:
    retainer=retainer.union(cyl_y(3.,B+6.5,retainer_front,x,cz))
    retainer=retainer.cut(cyl_y(1.1,B+6.4,retainer_back+.1,x,cz))
    retainer=retainer.cut(cyl_y(2.,retainer_back-2.,retainer_back+.1,x,cz))
# A separate small test coupon uses the actual connector pocket/guide geometry.
connector_coupon=body.intersect(box(40,12,22,z=cz-11,x=cx,y=B+4))
# Isolated blind-keyhole sample to check wall-screw heads before a full print.
keyhole_coupon=box(24,34,P['keyhole_local_thickness'],z=0,x=0,y=35)
keyhole_coupon=keyhole_coupon.cut(keyhole(0,8.4,8.4,1.5,4.5)).cut(keyhole(0,P['keyhole_stem_d'],P['keyhole_entry_d'],4.45,6.1))

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
# Cheap fit gauge for PCB footprint and corner centres before committing to body.
gauge=rounded(P['board_w']+4,P['board_h']+4,1.2,r=3)
gauge=gauge.cut(rounded(P['board_w']-10,P['board_h']-10,1.5,-.1,r=2))
for x,y in pcb_screws: gauge=gauge.cut(cyl_z(1.15,-.1,1.4,x,y))
# Button guide coupon: same wall thickness and bore as the full shell.
coupon=box(wall,20,16,x=-W/2+wall/2)
coupon=coupon.cut(cyl_x(P['button_bore_d']/2,-W/2-1,-W/2+wall+1,0,8))

parts={'body':body,'back_panel':back,'button_plunger':plunger,'button_cap':cap,
       'connector_retainer':retainer,'connector_fit_coupon':connector_coupon,
       'keyhole_fit_coupon':keyhole_coupon,'led_blank':led_blank,
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
    elif name=='connector_retainer': printable=printable.rotate((0,0,0),(1,0,0),-90)
    elif name=='connector_fit_coupon': printable=printable.rotate((0,0,0),(1,0,0),90)
    elif name=='keyhole_fit_coupon': printable=printable.rotate((0,0,0),(1,0,0),180)
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
assembly.add(parts['connector_retainer'],name='internal_connector_retainer',color=cq.Color(.32,.38,.39))
assembly.add(parts['led_blank'],name='optional_led_blank',color=cq.Color(.30,.35,.36))
assembly.export(str(OUT/'case_assembly.step'))
(ROOT/'parameters.json').write_text(json.dumps(P,indent=2))
(OUT/'validation.json').write_text(json.dumps(validation,indent=2))
print(json.dumps(validation,indent=2))

"""Public top-left pallet coordinates, separated from right-handed robot poses.

The public XY-down, Z-up frame is left-handed. Only point/box anchors and
direction names are reflected; never reflect a robot/TCP rotation matrix.
"""
import re

PUBLIC_FRAME='top_left_x_right_y_down_z_up'
INTERNAL_FRAME='internal_right_handed_long_side_x'


def reflected_side(side):
    return {'+Y':'-Y','-Y':'+Y'}.get(side,side)


def reflected_box_position(position,box_width,pallet_width):
    return dict(position,y=pallet_width-position['y']-box_width)


def public_log_text(message):
    return re.sub(r'[+-]Y\b',lambda m:reflected_side(m.group()),str(message))


def _public_directions(record):
    if record.get('direction_coordinate_frame')==PUBLIC_FRAME:return record
    result=dict(record)
    for key in ('open_direction','outside_side'):
        if key in result:result[key]=reflected_side(result[key])
    for key in ('open_directions','aligned_sides'):
        if key in result:result[key]=[reflected_side(side) for side in result[key]]
    for key in ('checks','stages','directions_by_box','attempts'):
        if key in result:result[key]=[_public_directions(item) for item in result[key]]
    for key in ('sequencing_policy','motion_verification','grasp'):
        if isinstance(result.get(key),dict):result[key]=_public_directions(result[key])
    # These diagnostic coordinates remain in the robot's calculation frame.
    if 'tool_bounds_pallet_m' in result:result['tool_bounds_coordinate_frame']=INTERNAL_FRAME
    result['direction_coordinate_frame']=PUBLIC_FRAME
    return result


def public_document(document):
    """Shallow view/export adapter; trajectory arrays are shared, never copied."""
    if document.get('coordinate_system',{}).get('frame')==PUBLIC_FRAME:return document
    result=dict(document)
    result['coordinate_system']=dict(document.get('coordinate_system',{}),frame=PUBLIC_FRAME,
        origin=[0,0,0],origin_description='托盘俯视左上角的装箱底面',
        x='right_along_long_edge',y='down_along_short_edge',z='up',handedness='left',
        calculation_frame=INTERNAL_FRAME,box_anchor='minimum_public_xyz_corner',
        mapping_to_calculation='x_i=x; y_i=W-y; z_i=z; box_anchor_y_i=W-y-box_width',
        orientation_codes='Z0/Z90 footprint permutation; physical rotations remain in the robot frame')
    dims=document.get('pallet') or (document['pallets'][0]['pallet'] if document['pallets'] else None)
    if dims is not None and dims['length']<dims['width']:
        result['coordinate_system'].update(x='right_along_recorded_length',y='down_along_recorded_width',pallet_axis_convention='input_length_width')
    pallets=[]
    for pallet in document['pallets']:
        current=dict(pallet,coordinate_frame=PUBLIC_FRAME);breadth=pallet['pallet']['width']
        current['packed_items']=[dict(item,position=reflected_box_position(item['position'],item['placed_size']['width'],breadth)) for item in pallet['packed_items']]
        pallets.append(current)
    result['pallets']=pallets
    if isinstance(document.get('paper_diagnostics'),dict):result['paper_diagnostics']=dict(document['paper_diagnostics'],coordinate_frame=INTERNAL_FRAME)
    if isinstance(document.get('robot_diagnostics'),dict):result['robot_diagnostics']=_public_directions(document['robot_diagnostics'])
    return result

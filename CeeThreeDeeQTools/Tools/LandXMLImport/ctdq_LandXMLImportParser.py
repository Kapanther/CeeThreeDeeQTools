# -*- coding: utf-8 -*-
"""
LandXML structure scanning and geometry parsing.

Two-phase design:
    1. ``scan_structure`` walks the file with ``iterparse`` and only records the
     *names* of importable entities (alignments, profiles, point groups,
     surfaces, pipe networks). Heavy data payloads (surface point/face lists,
     individual CgPoints, etc.) are skipped so large files scan quickly.
  2. ``parse_alignments`` re-reads the file and builds full coordinate
     geometry for the alignments the user selected.

All geometry is returned in LandXML native ordering converted to
(x=easting, y=northing) tuples.
"""

import math
import xml.etree.ElementTree as ET


# Tags whose children are bulk data and are never needed for a structure scan
DATA_TAGS = {
    'Pnts', 'Faces', 'P', 'F', 'PntList2D', 'PntList3D', 'Boundaries',
    'SourceData', 'Watersheds', 'Definition', 'CoordGeom',
    'CrossSects', 'Feature', 'Property',
}


def _local(tag):
    """Strip the XML namespace from a tag name."""
    return tag.rsplit('}', 1)[-1]


def _coords(text):
    """Parse LandXML point text ("northing easting [elev]") to (x, y, z)."""
    if not text:
        return None
    parts = text.split()
    if len(parts) < 2:
        return None
    try:
        northing = float(parts[0])
        easting = float(parts[1])
        elev = float(parts[2]) if len(parts) > 2 else None
    except ValueError:
        return None
    return (easting, northing, elev)


def _float_attr(elem, name):
    """Read a float attribute, tolerating Civil 3D's trailing-dot notation."""
    raw = elem.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _offset_point(elem):
    """Read a local CrossSectPnt as (offset, elevation)."""
    if not elem.text:
        return None
    values = elem.text.split()
    if len(values) < 2:
        return None
    try:
        return float(values[0]), float(values[1])
    except ValueError:
        return None
class LandXMLStructure:
    """Lightweight description of what a LandXML file contains."""

    def __init__(self):
        self.file_path = ''
        self.units = ''
        self.application = ''
        self.project = ''
        self.alignments = []      # [{'name': str, 'length': str, 'staStart': float, 'profiles': [str]}]
        self.point_groups = []    # [{'name': str, 'count': int}]
        self.surfaces = []        # [{'name': str}]
        self.pipe_networks = []   # [{'name': str}]
        self.feature_line_groups = []  # [{'name': str, 'count': int}]
        self.parcels = []         # [{'name': str}]
        self.corridors = []       # [{'name': str, 'alignment_refs': [str]}]


class LandXMLParser:
    """Reads LandXML files produced by Civil 3D and similar packages."""

    @staticmethod
    def scan_structure(file_path, progress_callback=None):
        """Scan a LandXML file and return a :class:`LandXMLStructure`.

        Bulk data elements are skipped; only entity names are collected.
        """
        structure = LandXMLStructure()
        structure.file_path = file_path

        if progress_callback:
            progress_callback("Scanning LandXML structure...", 5)

        current_alignment = None
        skip_depth = 0
        depth = 0
        cgpoint_count = 0
        current_point_group = None
        current_feature_group = None

        context = ET.iterparse(file_path, events=('start', 'end'))
        for event, elem in context:
            tag = _local(elem.tag)

            if event == 'start':
                depth += 1
                if skip_depth:
                    continue

                if tag in DATA_TAGS:
                    # Descend no further into bulk data
                    skip_depth = depth
                    continue

                if tag == 'Metric' or tag == 'Imperial':
                    structure.units = tag
                elif tag == 'Application':
                    structure.application = elem.get('name', '')
                elif tag == 'Project':
                    structure.project = elem.get('name', '')
                elif tag == 'Alignment':
                    try:
                        sta_start = float(elem.get('staStart', '0') or 0)
                    except ValueError:
                        sta_start = 0.0
                    current_alignment = {
                        'name': elem.get('name', '(unnamed)'),
                        'length': elem.get('length', ''),
                        'staStart': sta_start,
                        'profiles': [],
                    }
                    structure.alignments.append(current_alignment)
                elif tag == 'ProfAlign' and current_alignment is not None:
                    current_alignment['profiles'].append({
                        'name': elem.get('name', '(unnamed)'),
                        'kind': 'align',
                    })
                elif tag == 'ProfSurf' and current_alignment is not None:
                    current_alignment['profiles'].append({
                        'name': elem.get('name', '(unnamed)'),
                        'kind': 'surf',
                    })
                elif tag == 'CgPoints':
                    key = elem.get('name', '') or ''
                    current_point_group = {
                        'key': key,
                        'name': key or '(all points)',
                        'count': 0,
                    }
                    cgpoint_count = 0
                    structure.point_groups.append(current_point_group)
                elif tag == 'CgPoint':
                    cgpoint_count += 1
                elif tag == 'Surface':
                    structure.surfaces.append({'name': elem.get('name', '(unnamed)')})
                elif tag == 'PipeNetwork':
                    structure.pipe_networks.append({'name': elem.get('name', '(unnamed)')})
                elif tag == 'PlanFeatures':
                    current_feature_group = {
                        'name': elem.get('name', '(unnamed)'),
                        'count': 0,
                    }
                    structure.feature_line_groups.append(current_feature_group)
                elif tag == 'PlanFeature' and current_feature_group is not None:
                    current_feature_group['count'] += 1
                elif tag == 'Parcel':
                    structure.parcels.append({
                        'name': elem.get('name', '(unnamed)'),
                        'description': elem.get('desc', ''),
                    })
                elif tag == 'Roadway':
                    refs = [value for value in elem.get('alignmentRefs', '').split()
                            if value]
                    structure.corridors.append({
                        'name': elem.get('name', '(unnamed)'),
                        'alignment_refs': refs,
                    })

            else:  # end
                if skip_depth and depth == skip_depth:
                    skip_depth = 0
                if not skip_depth:
                    if tag == 'Alignment':
                        current_alignment = None
                    elif tag == 'CgPoints' and current_point_group is not None:
                        current_point_group['count'] = cgpoint_count
                        current_point_group = None
                    elif tag == 'PlanFeatures':
                        current_feature_group = None
                depth -= 1
                elem.clear()

        if progress_callback:
            progress_callback(
                "Scan complete: {0} alignment(s), {1} surface(s), {2} pipe network(s)".format(
                    len(structure.alignments), len(structure.surfaces),
                    len(structure.pipe_networks)), 100)

        return structure

    @staticmethod
    def parse_alignments(file_path, wanted_names=None, curve_tolerance=0.01,
                         progress_callback=None):
        """Parse full alignment geometry.

        :param wanted_names: iterable of alignment names to include (``None`` = all)
        :param curve_tolerance: max chord-to-arc offset used to densify curves
        :returns: list of dicts with ``name``, ``staStart``, ``points``
                  (list of (x, y)) and ``profiles``
        """
        wanted = set(wanted_names) if wanted_names is not None else None
        results = []

        context = ET.iterparse(file_path, events=('end',))
        for _event, elem in context:
            if _local(elem.tag) != 'Alignment':
                continue
            name = elem.get('name', '(unnamed)')
            if wanted is None or name in wanted:
                if progress_callback:
                    progress_callback("Parsing alignment '{0}'...".format(name), None)
                results.append(
                    LandXMLParser._parse_alignment_element(elem, curve_tolerance))
            elem.clear()

        return results

    @staticmethod
    def parse_corridors(file_path, wanted_names=None):
        """Parse Civil 3D Roadway records and their alignment references."""
        wanted = set(wanted_names) if wanted_names is not None else None
        results = []
        context = ET.iterparse(file_path, events=('end',))
        for _event, elem in context:
            if _local(elem.tag) != 'Roadway':
                continue
            name = elem.get('name', '(unnamed)')
            if wanted is None or name in wanted:
                results.append({
                    'name': name,
                    'alignment_refs': [value for value in
                                       elem.get('alignmentRefs', '').split()
                                       if value],
                    'sta_start': _float_attr(elem, 'staStart'),
                    'sta_end': _float_attr(elem, 'staEnd'),
                })
            elem.clear()
        return results

    # ------------------------------------------------------------------
    # Points
    # ------------------------------------------------------------------

    @staticmethod
    def parse_points(file_path, wanted_groups=None, warnings=None):
        """Parse CgPoints blocks.

        Civil 3D writes the coordinates once in an unnamed ``CgPoints`` block
        and then repeats each point as a ``pntRef`` inside every named point
        group, so references are resolved back to the master list here.

        :param wanted_groups: block keys to include (``''`` = the master list)
        :returns: list of dicts with ``number``, ``code``, ``description``,
                  ``groups`` and ``x`` / ``y`` / ``z``
        """
        warnings = warnings if warnings is not None else []
        wanted = None if wanted_groups is None else set(wanted_groups)

        points = {}
        memberships = {}
        blocks = []
        auto_id = 0

        context = ET.iterparse(file_path, events=('end',))
        for _event, elem in context:
            if _local(elem.tag) != 'CgPoints':
                continue

            key = elem.get('name', '') or ''
            ids = []
            for child in elem:
                if _local(child.tag) != 'CgPoint':
                    continue

                point_id = child.get('pntRef')
                if point_id is None:
                    auto_id += 1
                    point_id = (child.get('name') or child.get('oID')
                                or 'auto{0}'.format(auto_id))
                    coords = _coords(child.text)
                    if coords is not None:
                        points[point_id] = {
                            'number': child.get('name', '') or point_id,
                            'code': child.get('code', ''),
                            'description': child.get('desc', ''),
                            'x': coords[0],
                            'y': coords[1],
                            'z': coords[2] or 0.0,
                        }

                ids.append(point_id)
                if key:
                    groups = memberships.setdefault(point_id, [])
                    if key not in groups:
                        groups.append(key)

            blocks.append((key, ids))
            elem.clear()

        selected = []
        seen = set()
        missing = 0
        for key, ids in blocks:
            if wanted is not None and key not in wanted:
                continue
            for point_id in ids:
                if point_id in seen:
                    continue
                seen.add(point_id)
                point = points.get(point_id)
                if point is None:
                    missing += 1
                    continue
                record = dict(point)
                record['groups'] = ', '.join(memberships.get(point_id, []))
                selected.append(record)

        if missing:
            warnings.append(
                "{0} point reference(s) had no coordinates and were skipped.".format(
                    missing))
        return selected

    # ------------------------------------------------------------------
    # Feature lines and parcels
    # ------------------------------------------------------------------

    @staticmethod
    def parse_feature_lines(file_path, wanted_names=None,
                            progress_callback=None):
        """Parse 3D plan-feature line groups from LandXML."""
        wanted = set(wanted_names) if wanted_names is not None else None
        results = []
        context = ET.iterparse(file_path, events=('end',))
        for _event, elem in context:
            if _local(elem.tag) != 'PlanFeatures':
                continue
            name = elem.get('name', '(unnamed)')
            if wanted is None or name in wanted:
                if progress_callback:
                    progress_callback("Parsing feature lines '{0}'...".format(name), None)
                results.append(LandXMLParser._parse_feature_line_group(elem, name))
            elem.clear()
        return results

    @staticmethod
    def _parse_feature_line_group(elem, name):
        group = {'name': name, 'features': []}
        for node in elem:
            if _local(node.tag) != 'PlanFeature':
                continue
            points = []
            for child in node:
                if _local(child.tag) != 'CoordGeom':
                    continue
                points = LandXMLParser._parse_3d_coordgeom(child)
            properties = {
                prop.get('label', ''): prop.get('value', '')
                for feature in node if _local(feature.tag) == 'Feature'
                for prop in feature if _local(prop.tag) == 'Property'
            }
            if len(points) >= 2:
                group['features'].append({
                    'name': node.get('name', ''),
                    'points': points,
                    'code': next((feature.get('code', '') for feature in node
                                  if _local(feature.tag) == 'Feature'), ''),
                    'site': properties.get('site', ''),
                    'layer': properties.get('layer', ''),
                    'style': properties.get('style', ''),
                })
        return group

    @staticmethod
    def parse_parcels(file_path, wanted_names=None, progress_callback=None):
        """Parse parcel boundaries as closed 3D vertex rings."""
        wanted = set(wanted_names) if wanted_names is not None else None
        results = []
        context = ET.iterparse(file_path, events=('end',))
        for _event, elem in context:
            if _local(elem.tag) != 'Parcel':
                continue
            name = elem.get('name', '(unnamed)')
            if wanted is None or name in wanted:
                if progress_callback:
                    progress_callback("Parsing parcel '{0}'...".format(name), None)
                points = []
                for child in elem:
                    if _local(child.tag) == 'CoordGeom':
                        points = LandXMLParser._parse_3d_coordgeom(child)
                if len(points) >= 3:
                    if points[0] != points[-1]:
                        points.append(points[0])
                    results.append({
                        'name': name,
                        'description': elem.get('desc', ''),
                        'area': _float_attr(elem, 'area'),
                        'points': points,
                    })
            elem.clear()
        return results

    # ------------------------------------------------------------------
    # Pipe networks
    # ------------------------------------------------------------------

    @staticmethod
    def parse_pipe_networks(file_path, wanted_names=None,
                            progress_callback=None):
        """Parse selected pipe networks and their endpoint structures.

        Null structures are retained in the internal structure lookup so pipes
        can be positioned, but are marked ``visible`` false for the importer.
        """
        wanted = set(wanted_names) if wanted_names is not None else None
        results = []

        context = ET.iterparse(file_path, events=('end',))
        for _event, elem in context:
            if _local(elem.tag) != 'PipeNetwork':
                continue
            name = elem.get('name', '(unnamed)')
            if wanted is None or name in wanted:
                if progress_callback:
                    progress_callback("Parsing pipe network '{0}'...".format(name), None)
                results.append(LandXMLParser._parse_pipe_network_element(elem, name))
            elem.clear()
        return results

    @staticmethod
    def _parse_pipe_network_element(elem, name):
        network = {
            'name': name,
            'type': elem.get('pipeNetType', ''),
            'description': elem.get('desc', ''),
            'structures': [],
            'structure_lookup': {},
            'pipes': [],
        }

        for child in elem:
            tag = _local(child.tag)
            if tag == 'Structs':
                for node in child:
                    if _local(node.tag) != 'Struct':
                        continue
                    center = None
                    inverts = []
                    invert_records = []
                    structure_type = ''
                    dimensions = {}
                    for part in node:
                        part_tag = _local(part.tag)
                        if part_tag == 'Center':
                            center = _coords(part.text)
                        elif part_tag == 'Invert':
                            elev = _float_attr(part, 'elev')
                            if elev is not None:
                                inverts.append(elev)
                                invert_records.append({
                                    'elev': elev,
                                    'ref_pipe': part.get('refPipe', ''),
                                    'flow_dir': part.get('flowDir', ''),
                                })
                        elif part_tag in ('InletStruct', 'OutletStruct',
                                          'CircStruct', 'RectStruct'):
                            if part_tag in ('InletStruct', 'OutletStruct'):
                                structure_type = part_tag
                            else:
                                structure_type = part_tag
                                dimensions = {
                                    key: _float_attr(part, key)
                                    for key in ('diameter', 'length', 'width', 'thickness')
                                }
                    struct = {
                        'name': node.get('name', '(unnamed)'),
                        'description': node.get('desc', ''),
                        'rim': _float_attr(node, 'elevRim'),
                        'sump': _float_attr(node, 'elevSump'),
                        'x': center[0] if center else None,
                        'y': center[1] if center else None,
                        'inverts': inverts,
                        'invert_records': invert_records,
                        'invert': inverts[0] if inverts else None,
                        'type': structure_type or 'Structure',
                        'dimensions': dimensions,
                        'visible': not (
                            node.get('name', '').lower().startswith(
                                ('startnullstruct', 'endnullstruct'))
                            or node.get('desc', '').strip().lower() == 'null structure'
                        ),
                    }
                    network['structure_lookup'][struct['name']] = struct
                    if struct['visible']:
                        network['structures'].append(struct)
            elif tag == 'Pipes':
                for node in child:
                    if _local(node.tag) != 'Pipe':
                        continue
                    pipe_type = ''
                    dimensions = {}
                    for part in node:
                        part_tag = _local(part.tag)
                        if part_tag in ('RectPipe', 'CircPipe'):
                            pipe_type = part_tag
                            dimensions = {
                                key: _float_attr(part, key)
                                for key in ('diameter', 'height', 'width', 'thickness')
                            }
                    network['pipes'].append({
                        'name': node.get('name', '(unnamed)'),
                        'description': node.get('desc', ''),
                        'start': node.get('refStart', ''),
                        'end': node.get('refEnd', ''),
                        'length': _float_attr(node, 'length'),
                        'slope': _float_attr(node, 'slope'),
                        'type': pipe_type or 'Pipe',
                        'dimensions': dimensions,
                    })
        return network

    # ------------------------------------------------------------------
    # Surfaces
    # ------------------------------------------------------------------

    @staticmethod
    def parse_surfaces(file_path, wanted_names=None, progress_callback=None):
        """Parse TIN surfaces.

        :returns: list of dicts with ``name``, ``description``, ``points``
                  (ordered ``{id: (x, y, z)}``) and ``faces`` (tuples of ids)
        """
        wanted = set(wanted_names) if wanted_names is not None else None
        results = []

        context = ET.iterparse(file_path, events=('end',))
        for _event, elem in context:
            if _local(elem.tag) != 'Surface':
                continue
            name = elem.get('name', '(unnamed)')
            if wanted is None or name in wanted:
                if progress_callback:
                    progress_callback("Parsing surface '{0}'...".format(name), None)
                results.append(LandXMLParser._parse_surface_element(elem, name))
            elem.clear()

        return results

    @staticmethod
    def _parse_surface_element(elem, name):
        surface = {
            'name': name,
            'description': elem.get('desc', ''),
            'points': {},
            'faces': [],
            'hidden_faces': [],
            'warnings': [],
        }

        auto_id = 0
        for definition in elem:
            if _local(definition.tag) != 'Definition':
                continue
            for block in definition:
                block_tag = _local(block.tag)
                if block_tag == 'Pnts':
                    for node in block:
                        if _local(node.tag) != 'P':
                            continue
                        auto_id += 1
                        point = _coords(node.text)
                        if point is None:
                            continue
                        point_id = node.get('id') or str(auto_id)
                        surface['points'][point_id] = (
                            point[0], point[1], point[2] or 0.0)
                elif block_tag == 'Faces':
                    for node in block:
                        if _local(node.tag) != 'F' or not node.text:
                            continue
                        ids = node.text.split()
                        if len(ids) < 3:
                            continue
                        # i="1" marks a face Civil 3D hides (voids / concavity)
                        key = 'hidden_faces' if node.get('i') == '1' else 'faces'
                        surface[key].append(tuple(ids))
        return surface

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_alignment_element(elem, curve_tolerance):
        try:
            sta_start = float(elem.get('staStart', '0') or 0)
        except ValueError:
            sta_start = 0.0

        alignment = {
            'name': elem.get('name', '(unnamed)'),
            'staStart': sta_start,
            'description': elem.get('desc', ''),
            'points': [],
            'profiles': [],
            'cross_sections': [],
            'warnings': [],
        }

        for child in elem:
            tag = _local(child.tag)
            if tag == 'CoordGeom':
                alignment['points'] = LandXMLParser._parse_coordgeom(
                    child, curve_tolerance, alignment['warnings'])
            elif tag == 'Profile':
                profile_name = child.get('name', '')
                for sub in child:
                    sub_tag = _local(sub.tag)
                    if sub_tag == 'ProfAlign':
                        alignment['profiles'].append({
                            'name': sub.get('name', '') or profile_name or '(unnamed)',
                            'kind': 'align',
                            'elements': LandXMLParser._parse_profalign(sub, alignment['warnings']),
                        })
                    elif sub_tag == 'ProfSurf':
                        alignment['profiles'].append({
                            'name': sub.get('name', '') or profile_name or '(unnamed)',
                            'kind': 'surf',
                            'elements': LandXMLParser._parse_profsurf(sub),
                        })
            elif tag == 'CrossSects':
                alignment['cross_sections'] = (
                    LandXMLParser._parse_cross_sections(child))
        return alignment

    @staticmethod
    def _parse_cross_sections(cross_sections):
        sections = []
        for section in cross_sections:
            if _local(section.tag) != 'CrossSect':
                continue
            station = _float_attr(section, 'sta')
            if station is None:
                continue
            links = []
            section_points = []
            for surface in section:
                if _local(surface.tag) != 'DesignCrossSectSurf':
                    continue
                points = [node for node in surface
                          if _local(node.tag) == 'CrossSectPnt']
                if len(points) < 2:
                    continue
                start = _offset_point(points[0])
                end = _offset_point(points[1])
                if start is None or end is None:
                    continue
                dx = end[0] - start[0]
                grade = None if abs(dx) <= 1e-12 else (
                    (end[1] - start[1]) / dx * 100.0)
                links.append({
                    'code': surface.get('name', ''),
                    'start_offset_x': start[0],
                    'start_offset_y': start[1],
                    'end_offset_x': end[0],
                    'end_offset_y': end[1],
                    'grade': grade,
                    'start_code': points[0].get('code', ''),
                    'end_code': points[1].get('code', ''),
                })
                section_points.extend((
                    {'offset_x': start[0], 'offset_y': start[1],
                     'code': points[0].get('code', '')},
                    {'offset_x': end[0], 'offset_y': end[1],
                     'code': points[1].get('code', '')},
                ))
            sections.append({'station': station, 'links': links,
                             'points': section_points})
        return sections

    @staticmethod
    def _parse_coordgeom(coordgeom, curve_tolerance, warnings):
        points = []

        def append(pt):
            if pt is None:
                return
            xy = (pt[0], pt[1])
            if not points or (abs(points[-1][0] - xy[0]) > 1e-9 or
                              abs(points[-1][1] - xy[1]) > 1e-9):
                points.append(xy)

        for element in coordgeom:
            tag = _local(element.tag)
            nodes = {_local(n.tag): _coords(n.text) for n in element}

            if tag == 'Line':
                append(nodes.get('Start'))
                append(nodes.get('End'))
            elif tag == 'Curve':
                arc = LandXMLParser._densify_curve(
                    nodes.get('Start'), nodes.get('Center'), nodes.get('End'),
                    element.get('rot', 'cw'), curve_tolerance)
                if arc:
                    for pt in arc:
                        append(pt)
                else:
                    warnings.append(
                        "Curve could not be densified; using chord instead.")
                    append(nodes.get('Start'))
                    append(nodes.get('End'))
            elif tag == 'Spiral':
                spiral = LandXMLParser._densify_spiral(
                    element, nodes.get('Start'), nodes.get('PI'),
                    nodes.get('End'), curve_tolerance)
                if spiral:
                    for pt in spiral:
                        append(pt)
                else:
                    warnings.append(
                        "Spiral could not be densified; using chord instead.")
                    append(nodes.get('Start'))
                    append(nodes.get('End'))
            elif tag == 'IrregularLine':
                append(nodes.get('Start'))
                for node in element:
                    if _local(node.tag) == 'PntList2D' and node.text:
                        values = node.text.split()
                        for i in range(0, len(values) - 1, 2):
                            append(_coords(values[i] + ' ' + values[i + 1]))
                append(nodes.get('End'))

        return points

    @staticmethod
    def _parse_3d_coordgeom(coordgeom):
        """Read ordered 3D vertices from line-based CoordGeom content."""
        points = []
        for element in coordgeom:
            if _local(element.tag) != 'Line':
                continue
            nodes = {_local(node.tag): _coords(node.text) for node in element}
            for key in ('Start', 'End'):
                point = nodes.get(key)
                if point is None:
                    continue
                vertex = (point[0], point[1], point[2] or 0.0)
                if not points or vertex != points[-1]:
                    points.append(vertex)
        return points

    @staticmethod
    def _densify_spiral(element, start, pi, end, tolerance):
        """Densify a LandXML clothoid using its linearly varying curvature."""
        if not start or not end:
            return None

        length = _float_attr(element, 'length')
        if length is None or length <= 0:
            return None

        def radius(name):
            raw = element.get(name)
            if raw is None or str(raw).strip().upper() in ('INF', 'INFINITY'):
                return 0.0
            try:
                value = abs(float(raw))
            except ValueError:
                return None
            return 0.0 if value <= 1e-12 else 1.0 / value

        curvature_start = radius('radiusStart')
        curvature_end = radius('radiusEnd')
        if curvature_start is None or curvature_end is None:
            return None

        tangent_point = pi or end
        dx = tangent_point[0] - start[0]
        dy = tangent_point[1] - start[1]
        if math.hypot(dx, dy) <= 1e-12:
            return None
        heading = math.atan2(dy, dx)
        rotation = -1.0 if element.get('rot', 'ccw').lower().startswith('cw') else 1.0
        tolerance = max(float(tolerance or 0.01), 1e-6)
        maximum_curvature = max(curvature_start, curvature_end)
        step = (math.sqrt(8.0 * tolerance / maximum_curvature)
            if maximum_curvature > 0 else length)
        step = max(step, 0.05)
        segments = min(max(int(math.ceil(length / step)), 8), 500)
        delta = curvature_end - curvature_start
        points = [start]
        x, y = start[0], start[1]
        step_length = length / segments
        for index in range(segments):
            s = (index + 0.5) * step_length
            angle = (heading + rotation * (
                curvature_start * s + delta * s * s / (2.0 * length)))
            x += math.cos(angle) * step_length
            y += math.sin(angle) * step_length
            points.append((x, y))
        points[-1] = (end[0], end[1])
        return points

    @staticmethod
    def _densify_curve(start, center, end, rot, tolerance):
        if not start or not center or not end:
            return None

        radius = math.hypot(start[0] - center[0], start[1] - center[1])
        if radius <= 0:
            return None

        a0 = math.atan2(start[1] - center[1], start[0] - center[0])
        a1 = math.atan2(end[1] - center[1], end[0] - center[0])
        sweep = a1 - a0
        clockwise = str(rot).lower().startswith('cw')
        if clockwise:
            while sweep > 0:
                sweep -= 2 * math.pi
            while sweep < -2 * math.pi:
                sweep += 2 * math.pi
        else:
            while sweep < 0:
                sweep += 2 * math.pi
            while sweep > 2 * math.pi:
                sweep -= 2 * math.pi

        tolerance = max(float(tolerance or 0.01), 1e-6)
        if tolerance >= radius:
            step = math.radians(5.0)
        else:
            step = 2.0 * math.acos(1.0 - tolerance / radius)
        step = min(max(step, math.radians(0.05)), math.radians(5.0))

        segments = max(int(math.ceil(abs(sweep) / step)), 2)
        return [
            (center[0] + radius * math.cos(a0 + sweep * i / segments),
             center[1] + radius * math.sin(a0 + sweep * i / segments))
            for i in range(segments + 1)
        ]

    @staticmethod
    def _parse_profalign(profalign, warnings):
        """Return the ordered PVI / vertical-curve elements of a ProfAlign.

        Each entry is a dict with ``type``, ``station``, ``elevation`` and, for
        vertical curves, ``length`` / ``length2`` / ``radius``.
        """
        elements = []
        for node in profalign:
            tag = _local(node.tag)
            if tag not in ('PVI', 'CircCurve', 'ParaCurve', 'UnsymParaCurve'):
                continue
            if not node.text:
                continue
            values = node.text.split()
            if len(values) < 2:
                continue
            try:
                station = float(values[0])
                elevation = float(values[1])
            except ValueError:
                continue

            entry = {
                'type': tag,
                'station': station,
                'elevation': elevation,
                'length': _float_attr(node, 'length'),
                'length2': _float_attr(node, 'length2'),
                'radius': _float_attr(node, 'radius'),
            }
            if tag != 'PVI' and not (entry['length'] or entry['radius']):
                warnings.append(
                    "Vertical curve '{0}' at station {1:.3f} has no length or "
                    "radius; treated as a grade break.".format(tag, station))
            elements.append(entry)

        elements.sort(key=lambda e: e['station'])
        return elements

    @staticmethod
    def _parse_profsurf(profsurf):
        """Return sampled surface profile points as PVI-style elements."""
        elements = []
        for node in profsurf:
            if _local(node.tag) not in ('PntList2D', 'PntList3D') or not node.text:
                continue
            values = node.text.split()
            for i in range(0, len(values) - 1, 2):
                try:
                    station = float(values[i])
                    elevation = float(values[i + 1])
                except ValueError:
                    continue
                if elements and abs(elements[-1]['station'] - station) < 1e-9:
                    continue
                elements.append({
                    'type': 'PVI',
                    'station': station,
                    'elevation': elevation,
                    'length': None,
                    'length2': None,
                    'radius': None,
                })
        elements.sort(key=lambda e: e['station'])
        return elements

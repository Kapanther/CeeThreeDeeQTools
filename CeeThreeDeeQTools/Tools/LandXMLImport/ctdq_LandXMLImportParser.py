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

            else:  # end
                if skip_depth and depth == skip_depth:
                    skip_depth = 0
                if not skip_depth:
                    if tag == 'Alignment':
                        current_alignment = None
                    elif tag == 'CgPoints' and current_point_group is not None:
                        current_point_group['count'] = cgpoint_count
                        current_point_group = None
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
        return alignment

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
                # TODO: true clothoid densification
                warnings.append(
                    "Spiral approximated by Start/PI/End vertices (WIP).")
                append(nodes.get('Start'))
                append(nodes.get('PI'))
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

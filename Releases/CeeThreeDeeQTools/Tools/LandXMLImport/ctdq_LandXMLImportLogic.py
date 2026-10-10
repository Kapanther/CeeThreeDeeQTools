# -*- coding: utf-8 -*-
"""
Business logic for the LandXML Import tool.

Creates QGIS layers from parsed LandXML alignments. Three layer structures
are supported:

* ``alignment`` (default) - one ``LineStringZ`` layer per alignment holding
  the horizontal geometry (``type`` = ``Alignment``) and all of that
  alignment's profiles (``type`` = ``Profile``).
* ``all`` - a single layer containing every alignment and profile in the file.
* ``separate`` - one layer per object; profiles are named ``<Alignment>/<Profile>``.

The two combined structures are auto-styled as a categorised renderer on
``type`` with the profile category switched off. This is the structure the
section viewer will consume.

Profiles are draped onto the horizontal alignment: each station is converted
to an (x, y) position along the alignment and the profile elevation becomes
the Z value.
"""

import math
import os
import re

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsFillSymbol,
    QgsGeometry,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsPoint,
    QgsPointXY,
    QgsProject,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsRuleBasedLabeling,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor

from .ctdq_LandXMLContours import LandXMLContours
from .ctdq_LandXMLImportParser import LandXMLParser
from .ctdq_LandXMLMesh import LandXMLMesh
from .ctdq_LandXMLVerticalProfile import VerticalProfile

TYPE_ALIGNMENT = 'Alignment'
TYPE_PROFILE = 'Profile'
ALIGNMENT_BUFFER_COLOUR = '#f5caca'

STRUCTURE_PER_ALIGNMENT = 'alignment'
STRUCTURE_ALL = 'all'
STRUCTURE_SEPARATE = 'separate'


def _writer_enum(scope, name):
    """QgsVectorFileWriter enum value, tolerant of scoped/unscoped QGIS builds."""
    scoped = getattr(QgsVectorFileWriter, scope, None)
    value = getattr(scoped, name, None) if scoped is not None else None
    return value if value is not None else getattr(QgsVectorFileWriter, name)


class LandXMLImportLogic:
    """Stateless helpers that turn parsed LandXML data into QGIS layers."""

    @staticmethod
    def import_alignments(file_path, alignment_names, profile_keys,
                          source_crs, target_crs, curve_tolerance=0.01,
                          vertical_tolerance=0.005,
                          structure=STRUCTURE_PER_ALIGNMENT,
                          surface_names=None, include_hidden_faces=False,
                          point_group_keys=None,
                          pipe_network_names=None,
                          feature_line_group_names=None,
                          parcel_names=None,
                          corridor_names=None,
                          generate_contours=False, minor_interval=0.25,
                          major_interval=1.0,
                          group_name=None, group_per_alignment=False,
                          output_mode='memory', output_path=None,
                          progress_callback=None):
        """Import selected alignments, profiles and surfaces into the project.

        :param alignment_names: names of alignments whose horizontal geometry is wanted
        :param profile_keys: set of ``(alignment_name, kind, profile_name)`` tuples
        :param source_crs: :class:`QgsCoordinateReferenceSystem` of the file
        :param target_crs: :class:`QgsCoordinateReferenceSystem` for the layers
        :param vertical_tolerance: mid-ordinate tolerance for vertical curve densifying
        :param structure: ``alignment``, ``all`` or ``separate``
        :param surface_names: TIN surfaces to import as mesh layers
        :param group_per_alignment: separate mode only - nest each alignment in its own group
        :param output_mode: ``memory``, ``gpkg`` or ``shp``
        :param output_path: GeoPackage file or shapefile folder for the two disk modes
        :returns: dict with ``layers``, ``warnings`` and ``errors``
        """
        results = {'layers': [], 'warnings': [], 'errors': []}
        alignment_names = set(alignment_names or [])
        profile_keys = set(profile_keys or [])
        surface_names = set(surface_names or [])
        point_group_keys = list(point_group_keys or [])
        pipe_network_names = set(pipe_network_names or [])
        feature_line_group_names = set(feature_line_group_names or [])
        parcel_names = set(parcel_names or [])
        corridor_names = set(corridor_names or [])
        needed = set(alignment_names) | {key[0] for key in profile_keys}

        if (not needed and not surface_names and not point_group_keys
            and not pipe_network_names and not feature_line_group_names
                and not parcel_names and not corridor_names):
            results['errors'].append("Nothing selected to import.")
            return results

        def report(message, percent):
            if progress_callback:
                progress_callback(message, percent)

        alignments = []
        if needed:
            report("Reading alignment geometry...", 5)
            alignments = LandXMLParser.parse_alignments(
                file_path, needed, curve_tolerance,
                lambda msg, pct: report(msg, None))

        transform = None
        if source_crs.isValid() and target_crs.isValid() and source_crs != target_crs:
            transform = QgsCoordinateTransform(
                source_crs, target_crs, QgsProject.instance())

        root = QgsProject.instance().layerTreeRoot()
        base_group = root.findGroup(group_name) if group_name else None
        if group_name and base_group is None:
            base_group = root.insertGroup(0, group_name)

        fields = LandXMLImportLogic._build_fields()
        writer_state = {'gpkg_started': False}
        source_name = os.path.basename(file_path)
        combined_features = []
        total = max(len(alignments), 1)

        for index, alignment in enumerate(alignments):
            name = alignment['name']
            report("Building geometry for '{0}'...".format(name),
                   10 + int(75.0 * index / total))

            points = LandXMLImportLogic._transform_points(
                alignment['points'], transform)
            if len(points) < 2:
                results['errors'].append(
                    "Alignment '{0}' has no usable geometry.".format(name))
                continue

            for warning in alignment.get('warnings', []):
                results['warnings'].append("{0}: {1}".format(name, warning))

            group = base_group
            if structure == STRUCTURE_SEPARATE and group_per_alignment:
                parent = base_group if base_group is not None else root
                group = parent.findGroup(name) or parent.addGroup(name)

            features = []
            if name in alignment_names:
                features.append(('', LandXMLImportLogic._alignment_feature(
                    fields, alignment, points, source_name)))

            wanted_profiles = {(key[1], key[2]) for key in profile_keys
                               if key[0] == name}
            if wanted_profiles:
                stations = LandXMLImportLogic._station_table(
                    points, alignment['staStart'])
                for profile in alignment['profiles']:
                    if (profile.get('kind', 'align'),
                            profile['name']) not in wanted_profiles:
                        continue
                    feature = LandXMLImportLogic._profile_feature(
                        fields, alignment, profile, points, stations,
                        vertical_tolerance, source_name, results['warnings'])
                    if feature is not None:
                        features.append(('/' + profile['name'], feature))

            if not features:
                continue

            if structure == STRUCTURE_ALL:
                combined_features.extend(feature for _suffix, feature in features)
                continue

            if structure == STRUCTURE_PER_ALIGNMENT:
                layer = LandXMLImportLogic._new_layer(name, target_crs, fields)
                layer.dataProvider().addFeatures(
                    [feature for _suffix, feature in features])
                layer.updateExtents()
                LandXMLImportLogic._store_layer(
                    layer, group, output_mode, output_path, writer_state,
                    results, style_fn=LandXMLImportLogic._apply_category_style)
                continue

            for suffix, feature in features:
                layer = LandXMLImportLogic._new_layer(
                    name + suffix, target_crs, fields)
                layer.dataProvider().addFeatures([feature])
                layer.updateExtents()
                LandXMLImportLogic._store_layer(
                    layer, group, output_mode, output_path, writer_state, results)

        if structure == STRUCTURE_ALL and combined_features:
            report("Creating combined layer...", 90)
            layer_name = group_name or os.path.splitext(source_name)[0] or "LandXML"
            layer = LandXMLImportLogic._new_layer(layer_name, target_crs, fields)
            layer.dataProvider().addFeatures(combined_features)
            layer.updateExtents()
            LandXMLImportLogic._store_layer(
                layer, base_group, output_mode, output_path, writer_state,
                results, style_fn=LandXMLImportLogic._apply_category_style)

        if point_group_keys:
            LandXMLImportLogic._import_points(
                file_path, point_group_keys, target_crs, transform, base_group,
                source_name, output_mode, output_path, writer_state, results,
                report)

        if surface_names:
            LandXMLImportLogic._import_surfaces(
                file_path, surface_names, target_crs, transform, base_group,
                root, output_mode, output_path, include_hidden_faces,
                generate_contours, minor_interval, major_interval,
                results, report)

        if pipe_network_names:
            LandXMLImportLogic._import_pipe_networks(
                file_path, pipe_network_names, target_crs, transform, base_group,
                root, source_name, output_mode, output_path, writer_state,
                results, report)

        if feature_line_group_names:
            LandXMLImportLogic._import_feature_lines(
                file_path, feature_line_group_names, target_crs, transform,
                base_group, source_name, output_mode, output_path, writer_state,
                results, report)

        if parcel_names:
            LandXMLImportLogic._import_parcels(
                file_path, parcel_names, target_crs, transform, base_group,
                source_name, output_mode, output_path, writer_state, results,
                report)

        if corridor_names:
            LandXMLImportLogic._import_corridors(
                file_path, corridor_names, target_crs, transform, base_group,
                root, curve_tolerance, source_name, output_mode, output_path,
                writer_state, results, report)

        report("Import complete.", 100)
        return results

    # ------------------------------------------------------------------
    # Feature lines and parcels
    # ------------------------------------------------------------------

    @staticmethod
    def _import_corridors(file_path, corridor_names, target_crs, transform,
                          base_group, root, curve_tolerance, source_name,
                          output_mode, output_path, state, results, report):
        report("Reading corridors...", 95)
        corridors = LandXMLParser.parse_corridors(file_path, corridor_names)
        alignments = LandXMLParser.parse_alignments(
            file_path,
            {reference for corridor in corridors
             for reference in corridor['alignment_refs']},
            curve_tolerance)
        alignment_by_name = {alignment['name']: alignment
                             for alignment in alignments}
        for corridor in corridors:
            parent = base_group if base_group is not None else root
            corridor_group = (parent.findGroup(corridor['name'])
                              or parent.addGroup(corridor['name']))
            for alignment_name in corridor['alignment_refs']:
                alignment = alignment_by_name.get(alignment_name)
                if alignment is None or not alignment['cross_sections']:
                    results['warnings'].append(
                        "Corridor '{0}' references alignment '{1}' without cross sections."
                        .format(corridor['name'], alignment_name))
                    continue
                sections = alignment['cross_sections']
                link_layer = LandXMLImportLogic._corridor_links_layer(
                    alignment, corridor['name'], target_crs, transform,
                    source_name)
                feature_layer = LandXMLImportLogic._corridor_featurelines_layer(
                    alignment, corridor['name'], target_crs, transform,
                    source_name)
                if link_layer is not None:
                    LandXMLImportLogic._store_layer(
                        link_layer, corridor_group, output_mode, output_path,
                        state, results)
                if feature_layer is not None:
                    LandXMLImportLogic._store_layer(
                        feature_layer, corridor_group, output_mode, output_path,
                        state, results, style_fn=LandXMLImportLogic._style_feature_lines)

    @staticmethod
    def _corridor_point(alignment, station, offset_x, offset_y, transform):
        points = alignment['points']
        stations = LandXMLImportLogic._station_table(
            points, alignment['staStart'])
        center = LandXMLImportLogic._point_at_station(points, stations, station)
        if center is None:
            return None
        if len(points) < 2:
            return None
        index = next((i for i in range(1, len(stations))
                      if station <= stations[i]), len(points) - 1)
        before = points[max(0, index - 1)]
        after = points[min(len(points) - 1, index)]
        dx = after[0] - before[0]
        dy = after[1] - before[1]
        length = math.hypot(dx, dy) or 1.0
        x = center[0] - dy / length * offset_x
        y = center[1] + dx / length * offset_x
        if transform is not None:
            projected = transform.transform(QgsPointXY(x, y))
            x, y = projected.x(), projected.y()
        return QgsPoint(x, y, offset_y)

    @staticmethod
    def _corridor_links_layer(alignment, corridor_name, target_crs,
                               transform, source_name):
        fields = QgsFields()
        for name, field_type in (
            ('Alignment', QVariant.String), ('CorridorName', QVariant.String),
            ('Station', QVariant.Double), ('LinkCode', QVariant.String),
            ('StartOffsetX', QVariant.Double), ('StartOffsetY', QVariant.Double),
            ('EndOffsetX', QVariant.Double), ('EndOffsetY', QVariant.Double),
            ('Grade', QVariant.Double), ('StartPointCode', QVariant.String),
            ('EndPointCode', QVariant.String)):
            fields.append(QgsField(name, field_type))
        layer = QgsVectorLayer('LineStringZ', corridor_name + ' Cross Sections', 'memory')
        layer.setCrs(target_crs)
        layer.dataProvider().addAttributes(fields.toList())
        layer.updateFields()
        features = []
        for section in alignment['cross_sections']:
            for link in section['links']:
                start = LandXMLImportLogic._corridor_point(
                    alignment, section['station'], link['start_offset_x'],
                    link['start_offset_y'], transform)
                end = LandXMLImportLogic._corridor_point(
                    alignment, section['station'], link['end_offset_x'],
                    link['end_offset_y'], transform)
                if start is None or end is None:
                    continue
                feature = QgsFeature(fields)
                feature.setGeometry(QgsGeometry.fromPolyline([start, end]))
                feature.setAttributes([
                    alignment['name'], corridor_name, section['station'],
                    link['code'], link['start_offset_x'], link['start_offset_y'],
                    link['end_offset_x'], link['end_offset_y'], link['grade'],
                    link['start_code'], link['end_code'],
                ])
                features.append(feature)
        if not features:
            return None
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        return layer

    @staticmethod
    def _corridor_featurelines_layer(alignment, corridor_name, target_crs,
                                     transform, source_name):
        fields = QgsFields()
        for name in ('Alignment', 'CorridorName', 'Code'):
            fields.append(QgsField(name, QVariant.String))
        layer = QgsVectorLayer('LineStringZ', corridor_name + ' Feature Lines', 'memory')
        layer.setCrs(target_crs)
        layer.dataProvider().addAttributes(fields.toList())
        layer.updateFields()
        strings = []
        active = {}
        for section in alignment['cross_sections']:
            current_counts = {}
            for point in section.get('points', []):
                code = point['code'] or '(uncoded)'
                occurrence = current_counts.get(code, 0)
                current_counts[code] = occurrence + 1
                key = (code, occurrence)
                vertex = LandXMLImportLogic._corridor_point(
                    alignment, section['station'], point['offset_x'],
                    point['offset_y'], transform)
                if vertex is None:
                    continue
                if key not in active:
                    active[key] = []
                    strings.append((code, active[key]))
                active[key].append(vertex)
            active = {key: vertices for key, vertices in active.items()
                      if key[1] < current_counts.get(key[0], 0)}

        features = []
        for code, vertices in strings:
            if len(vertices) < 2:
                continue
            feature = QgsFeature(fields)
            feature.setGeometry(QgsGeometry.fromPolyline(vertices))
            feature.setAttributes([alignment['name'], corridor_name, code])
            features.append(feature)
        if not features:
            return None
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        return layer

    @staticmethod
    def _import_feature_lines(file_path, group_names, target_crs, transform,
                              group, source_name, output_mode, output_path,
                              state, results, report):
        report("Reading feature lines...", 93)
        groups = LandXMLParser.parse_feature_lines(file_path, group_names)
        for feature_group in groups:
            fields = QgsFields()
            for name, field_type in (
                ('name', QVariant.String), ('code', QVariant.String),
                ('site', QVariant.String), ('layer', QVariant.String),
                ('style', QVariant.String), ('verts', QVariant.Int),
                ('src_file', QVariant.String)):
                fields.append(QgsField(name, field_type))
            layer = QgsVectorLayer('LineStringZ', feature_group['name'], 'memory')
            layer.setCrs(target_crs)
            layer.dataProvider().addAttributes(fields.toList())
            layer.updateFields()
            features = []
            for item in feature_group['features']:
                vertices = LandXMLImportLogic._transform_3d_points(
                    item['points'], transform)
                feature = QgsFeature(fields)
                feature.setGeometry(QgsGeometry.fromPolyline(
                    [QgsPoint(x, y, z) for x, y, z in vertices]))
                feature.setAttributes([
                    item['name'], item['code'], item['site'], item['layer'],
                    item['style'], len(vertices), source_name,
                ])
                features.append(feature)
            if not features:
                continue
            layer.dataProvider().addFeatures(features)
            layer.updateExtents()
            LandXMLImportLogic._store_layer(
                layer, group, output_mode, output_path, state, results,
                style_fn=LandXMLImportLogic._style_feature_lines)

    @staticmethod
    def _import_parcels(file_path, parcel_names, target_crs, transform,
                        group, source_name, output_mode, output_path, state,
                        results, report):
        report("Reading parcels...", 94)
        parcels = LandXMLParser.parse_parcels(file_path, parcel_names)
        if not parcels:
            results['errors'].append("No usable parcels found for the selection.")
            return
        fields = QgsFields()
        for name, field_type in (
            ('name', QVariant.String), ('descr', QVariant.String),
            ('area', QVariant.Double), ('verts', QVariant.Int),
            ('src_file', QVariant.String)):
            fields.append(QgsField(name, field_type))
        layer = QgsVectorLayer('PolygonZ', 'Parcels', 'memory')
        layer.setCrs(target_crs)
        layer.dataProvider().addAttributes(fields.toList())
        layer.updateFields()
        features = []
        for parcel in parcels:
            vertices = LandXMLImportLogic._transform_3d_points(
                parcel['points'], transform)
            feature = QgsFeature(fields)
            feature.setGeometry(QgsGeometry.fromPolygon(
                [[QgsPoint(x, y, z) for x, y, z in vertices]]))
            feature.setAttributes([
                parcel['name'], parcel['description'], parcel['area'],
                len(vertices), source_name,
            ])
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        LandXMLImportLogic._store_layer(
            layer, group, output_mode, output_path, state, results,
            style_fn=LandXMLImportLogic._style_parcels)

    @staticmethod
    def _style_feature_lines(layer):
        layer.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple(
            {'color': '230,120,35,255', 'width': '0.8'})))
        LandXMLImportLogic._label_layer(layer, 'name')

    @staticmethod
    def _style_parcels(layer):
        layer.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
            {'color': '80,120,220,60', 'outline_color': '80,120,220,255',
             'outline_width': '0.5'})))
        LandXMLImportLogic._label_layer(layer, 'name')

    # ------------------------------------------------------------------
    # Pipe networks
    # ------------------------------------------------------------------

    @staticmethod
    def _import_pipe_networks(file_path, network_names, target_crs, transform,
                              group, root, source_name, output_mode,
                              output_path, state, results, report):
        report("Reading pipe networks...", 92)
        networks = LandXMLParser.parse_pipe_networks(file_path, network_names)
        for network in networks:
            network_group_parent = group if group is not None else root
            network_group = (network_group_parent.findGroup(network['name'])
                             or network_group_parent.addGroup(network['name']))
            pipe_layer = LandXMLImportLogic._pipe_layer(
                network, target_crs, transform, source_name, results)
            structure_layer = LandXMLImportLogic._structure_layer(
                network, target_crs, transform, source_name)

            if pipe_layer is not None:
                LandXMLImportLogic._store_layer(
                    pipe_layer, network_group, output_mode, output_path, state,
                    results, style_fn=LandXMLImportLogic._style_pipes)
            if structure_layer is not None:
                LandXMLImportLogic._store_layer(
                    structure_layer, network_group, output_mode, output_path,
                    state, results, style_fn=LandXMLImportLogic._style_structures)

    @staticmethod
    def _pipe_layer(network, target_crs, transform, source_name, results):
        fields = QgsFields()
        for name, field_type in (
            ('name', QVariant.String), ('type', QVariant.String),
            ('descr', QVariant.String), ('start_struct', QVariant.String),
            ('end_struct', QVariant.String), ('length', QVariant.Double),
            ('slope', QVariant.Double), ('diameter', QVariant.Double),
            ('height', QVariant.Double), ('width', QVariant.Double),
            ('thickness', QVariant.Double), ('network', QVariant.String),
            ('src_file', QVariant.String)):
            fields.append(QgsField(name, field_type))

        layer = QgsVectorLayer('LineStringZ', 'Pipes', 'memory')
        layer.setCrs(target_crs)
        layer.dataProvider().addAttributes(fields.toList())
        layer.updateFields()
        features = []
        for pipe in network['pipes']:
            start = network['structure_lookup'].get(pipe['start'])
            end = network['structure_lookup'].get(pipe['end'])
            if not start or not end or start['x'] is None or end['x'] is None:
                results['warnings'].append(
                    "Pipe '{0}' has an unresolved endpoint and was skipped.".format(
                        pipe['name']))
                continue
            start_xy = LandXMLImportLogic._network_point(start, transform)
            end_xy = LandXMLImportLogic._network_point(end, transform)
            start_z = LandXMLImportLogic._pipe_invert(start, pipe['name'])
            end_z = LandXMLImportLogic._pipe_invert(end, pipe['name'])
            feature = QgsFeature(fields)
            feature.setGeometry(QgsGeometry.fromPolyline([
                QgsPoint(start_xy[0], start_xy[1], start_z),
                QgsPoint(end_xy[0], end_xy[1], end_z)]))
            dimensions = pipe['dimensions']
            feature.setAttributes([
                pipe['name'], pipe['type'], pipe['description'], pipe['start'],
                pipe['end'], pipe['length'], pipe['slope'],
                dimensions.get('diameter'), dimensions.get('height'),
                dimensions.get('width'), dimensions.get('thickness'),
                network['name'], source_name,
            ])
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        return layer if features else None

    @staticmethod
    def _pipe_invert(structure, pipe_name):
        for record in structure.get('invert_records', []):
            if record.get('ref_pipe') == pipe_name:
                return record['elev']
        return structure['invert'] if structure['invert'] is not None else 0.0

    @staticmethod
    def _structure_layer(network, target_crs, transform, source_name):
        fields = QgsFields()
        for name, field_type in (
            ('name', QVariant.String), ('type', QVariant.String),
            ('descr', QVariant.String), ('rim_elev', QVariant.Double),
            ('sump_elev', QVariant.Double), ('invert_elev', QVariant.Double),
            ('diameter', QVariant.Double), ('length', QVariant.Double),
            ('width', QVariant.Double), ('thickness', QVariant.Double),
            ('network', QVariant.String), ('src_file', QVariant.String)):
            fields.append(QgsField(name, field_type))

        layer = QgsVectorLayer('PointZ', 'Structures', 'memory')
        layer.setCrs(target_crs)
        layer.dataProvider().addAttributes(fields.toList())
        layer.updateFields()
        features = []
        for structure in network['structures']:
            if structure['x'] is None:
                continue
            x, y = LandXMLImportLogic._network_point(structure, transform)
            z = structure['rim'] if structure['rim'] is not None else (
                structure['invert'] or 0.0)
            dimensions = structure['dimensions']
            feature = QgsFeature(fields)
            feature.setGeometry(QgsGeometry(QgsPoint(x, y, z)))
            feature.setAttributes([
                structure['name'], structure['type'], structure['description'],
                structure['rim'], structure['sump'], structure['invert'],
                dimensions.get('diameter'), dimensions.get('length'),
                dimensions.get('width'), dimensions.get('thickness'),
                network['name'], source_name,
            ])
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        return layer if features else None

    @staticmethod
    def _network_point(structure, transform):
        point = QgsPointXY(structure['x'], structure['y'])
        if transform is not None:
            point = transform.transform(point)
        return point.x(), point.y()

    @staticmethod
    def _style_pipes(layer):
        layer.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple(
            {'color': '30,100,190,255', 'width': '0.8'})))
        LandXMLImportLogic._label_layer(layer, 'name')

    @staticmethod
    def _style_structures(layer):
        layer.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
            {'name': 'circle', 'color': '220,90,45,255',
             'outline_color': '55,30,20,255', 'size': '3.0'})))
        LandXMLImportLogic._label_layer(layer, 'name')

    @staticmethod
    def _label_layer(layer, field_name):
        settings = QgsPalLayerSettings()
        settings.fieldName = field_name
        text_format = QgsTextFormat()
        text_format.setSize(8)
        settings.setFormat(text_format)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        layer.setLabelsEnabled(True)

    # ------------------------------------------------------------------
    # Points
    # ------------------------------------------------------------------

    @staticmethod
    def _import_points(file_path, point_group_keys, target_crs, transform,
                       group, source_name, output_mode, output_path, state,
                       results, report):
        report("Reading points...", 88)
        points = LandXMLParser.parse_points(
            file_path, point_group_keys, results['warnings'])
        if not points:
            results['errors'].append("No points found for the selected groups.")
            return

        fields = QgsFields()
        for name, field_type in (
            ("point_no", QVariant.String),
            ("code", QVariant.String),
            ("descr", QVariant.String),
            ("pnt_group", QVariant.String),
            ("elev", QVariant.Double),
            ("src_file", QVariant.String),
        ):
            fields.append(QgsField(name, field_type))

        layer = QgsVectorLayer("PointZ", "Points", "memory")
        layer.setCrs(target_crs)
        layer.dataProvider().addAttributes(fields.toList())
        layer.updateFields()

        features = []
        for point in points:
            x, y = point['x'], point['y']
            if transform is not None:
                projected = transform.transform(QgsPointXY(x, y))
                x, y = projected.x(), projected.y()
            feature = QgsFeature(fields)
            feature.setGeometry(QgsGeometry(QgsPoint(x, y, point['z'])))
            feature.setAttributes([
                point['number'],
                point['code'],
                point['description'],
                point['groups'],
                point['z'],
                source_name,
            ])
            features.append(feature)

        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        LandXMLImportLogic._store_layer(
            layer, group, output_mode, output_path, state, results,
            style_fn=LandXMLImportLogic._style_points)

    @staticmethod
    def _style_points(layer):
        """Categorise on the point group and label with the point code."""
        values = sorted({(feature['pnt_group'] or '')
                         for feature in layer.getFeatures()})
        categories = []
        for position, value in enumerate(values):
            symbol = QgsMarkerSymbol.createSimple(
                {'name': 'circle', 'size': '2.6', 'outline_color': '35,35,35,255'})
            symbol.setColor(QColor.fromHsv(
                int(360.0 * position / max(len(values), 1)), 200, 225))
            categories.append(QgsRendererCategory(
                value, symbol, value or '(no group)', True))
        if categories:
            layer.setRenderer(
                QgsCategorizedSymbolRenderer('pnt_group', categories))

        settings = QgsPalLayerSettings()
        settings.fieldName = 'code'
        settings.placement = LandXMLImportLogic._point_label_placement()
        settings.dist = 1.5

        text_format = QgsTextFormat()
        text_format.setSize(8)
        buffer_settings = QgsTextBufferSettings()
        buffer_settings.setEnabled(True)
        buffer_settings.setSize(1.0)
        buffer_settings.setColor(QColor(255, 255, 255))
        text_format.setBuffer(buffer_settings)
        settings.setFormat(text_format)

        layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        layer.setLabelsEnabled(True)
        layer.triggerRepaint()

    @staticmethod
    def _point_label_placement():
        placement = getattr(QgsPalLayerSettings, 'AroundPoint', None)
        if placement is not None:
            return placement
        from qgis.core import Qgis
        return Qgis.LabelPlacement.AroundPoint

    # ------------------------------------------------------------------
    # Surfaces
    # ------------------------------------------------------------------

    @staticmethod
    def _import_surfaces(file_path, surface_names, target_crs, transform,
                         base_group, root, output_mode, output_path,
                         include_hidden, generate_contours, minor_interval,
                         major_interval, results, report):
        report("Reading surfaces...", 92)
        surfaces = LandXMLParser.parse_surfaces(
            file_path, surface_names, lambda msg, pct: report(msg, None))

        folder = LandXMLMesh.output_folder(output_mode, output_path, file_path)

        def project(x, y):
            point = transform.transform(QgsPointXY(x, y))
            return point.x(), point.y()

        for surface in surfaces:
            layer = LandXMLMesh.create_layer(
                surface, folder, LandXMLImportLogic._safe_name(surface['name']),
                target_crs, None if transform is None else project,
                results['warnings'], results['errors'],
                include_hidden=include_hidden)
            if layer is None:
                continue

            group = base_group
            if generate_contours:
                parent = base_group if base_group is not None else root
                group = (parent.findGroup(surface['name'])
                         or parent.addGroup(surface['name']))

            LandXMLImportLogic._add_layer(layer, group)
            results['layers'].append(layer.name())

            if not generate_contours:
                continue

            report("Generating contours for '{0}'...".format(surface['name']), None)
            elevations = [pt[2] for pt in surface['points'].values()]
            contours = LandXMLContours.generate(
                layer, minor_interval, major_interval, target_crs,
                min(elevations) if elevations else None,
                max(elevations) if elevations else None,
                results['warnings'], results['errors'])
            if contours is not None:
                LandXMLImportLogic._add_layer(contours, group, at_top=True)
                results['layers'].append(contours.name())

    # ------------------------------------------------------------------
    # Layer construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_fields():
        fields = QgsFields()
        for name, field_type in (
            ("name", QVariant.String),
            ("type", QVariant.String),
            ("profile", QVariant.String),
            ("prof_kind", QVariant.String),
            ("descr", QVariant.String),
            ("sta_start", QVariant.Double),
            ("sta_end", QVariant.Double),
            ("length", QVariant.Double),
            ("min_elev", QVariant.Double),
            ("max_elev", QVariant.Double),
            ("verts", QVariant.Int),
            ("src_file", QVariant.String),
        ):
            fields.append(QgsField(name, field_type))
        return fields

    @staticmethod
    def _new_layer(name, target_crs, fields):
        layer = QgsVectorLayer("LineStringZ", name, "memory")
        layer.setCrs(target_crs)
        layer.dataProvider().addAttributes(fields.toList())
        layer.updateFields()
        return layer

    @staticmethod
    def _alignment_feature(fields, alignment, points, source_name):
        # Horizontal geometry carries no elevation, so Z is flat
        vertices = [QgsPoint(x, y, 0.0) for x, y in points]
        geometry = QgsGeometry.fromPolyline(vertices)
        sta_start = alignment.get('staStart', 0.0)
        feature = QgsFeature(fields)
        feature.setGeometry(geometry)
        feature.setAttributes([
            alignment['name'],
            TYPE_ALIGNMENT,
            None,
            None,
            alignment.get('description', ''),
            sta_start,
            sta_start + geometry.length(),
            geometry.length(),
            None,
            None,
            len(vertices),
            source_name,
        ])
        return feature

    @staticmethod
    def _profile_feature(fields, alignment, profile, points, stations,
                         vertical_tolerance, source_name, warnings):
        alignment_name = alignment['name']
        elements = profile.get('elements') or []
        vertical = VerticalProfile(elements)
        for warning in vertical.warnings:
            warnings.append("{0}/{1}: {2}".format(
                alignment_name, profile['name'], warning))

        if not vertical.is_valid:
            warnings.append(
                "Profile '{0}/{1}' has fewer than two points; skipped.".format(
                    alignment_name, profile['name']))
            return None

        sample_stations = LandXMLImportLogic._profile_sample_stations(
            vertical, stations, vertical_tolerance)

        vertices = []
        for station in sample_stations:
            elevation = vertical.elevation_at(station)
            if elevation is None:
                continue
            position = LandXMLImportLogic._point_at_station(
                points, stations, station)
            if position is None:
                continue
            vertices.append(QgsPoint(position[0], position[1], elevation))

        if len(vertices) < 2:
            warnings.append(
                "Profile '{0}/{1}' could not be draped onto the alignment.".format(
                    alignment_name, profile['name']))
            return None

        geometry = QgsGeometry.fromPolyline(vertices)
        elevations = [pt.z() for pt in vertices]
        feature = QgsFeature(fields)
        feature.setGeometry(geometry)
        feature.setAttributes([
            alignment_name,
            TYPE_PROFILE,
            profile['name'],
            'surface' if profile.get('kind') == 'surf' else 'design',
            alignment.get('description', ''),
            vertical.start_station,
            vertical.end_station,
            geometry.length(),
            min(elevations),
            max(elevations),
            len(vertices),
            source_name,
        ])
        return feature

    @staticmethod
    def _apply_category_style(layer):
        """Categorise on ``type`` with the profile category switched off."""
        alignment_symbol = QgsLineSymbol.createSimple(
            {'color': '227,26,28,255', 'width': '0.66'})
        profile_symbol = QgsLineSymbol.createSimple(
            {'color': '31,120,180,255', 'width': '0.3'})
        categories = [
            QgsRendererCategory(TYPE_ALIGNMENT, alignment_symbol, TYPE_ALIGNMENT, True),
            QgsRendererCategory(TYPE_PROFILE, profile_symbol, TYPE_PROFILE, False),
        ]
        layer.setRenderer(QgsCategorizedSymbolRenderer('type', categories))
        LandXMLImportLogic._label_alignments(layer)
        layer.triggerRepaint()

    @staticmethod
    def _label_alignments(layer):
        """Label the alignment features only, leaving profiles unlabelled."""
        settings = QgsPalLayerSettings()
        settings.fieldName = 'name'
        settings.placement = LandXMLImportLogic._line_label_placement()

        text_format = QgsTextFormat()
        text_format.setSize(9)
        buffer_settings = QgsTextBufferSettings()
        buffer_settings.setEnabled(True)
        buffer_settings.setSize(1.0)
        buffer_settings.setColor(QColor(ALIGNMENT_BUFFER_COLOUR))
        text_format.setBuffer(buffer_settings)
        settings.setFormat(text_format)

        root = QgsRuleBasedLabeling.Rule(None)
        rule = QgsRuleBasedLabeling.Rule(settings)
        rule.setDescription('Alignments')
        rule.setFilterExpression('"type" = \'{0}\''.format(TYPE_ALIGNMENT))
        root.appendChild(rule)

        layer.setLabeling(QgsRuleBasedLabeling(root))
        layer.setLabelsEnabled(True)

    @staticmethod
    def _line_label_placement():
        placement = getattr(QgsPalLayerSettings, 'Line', None)
        if placement is not None:
            return placement
        from qgis.core import Qgis
        return Qgis.LabelPlacement.Line

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    @staticmethod
    def _store_layer(layer, group, output_mode, output_path, state, results,
                     style_fn=None):
        saved = LandXMLImportLogic._write_layer(
            layer, output_mode, output_path, state, results['errors'])
        if saved is None:
            return
        if style_fn is not None:
            style_fn(saved)
        LandXMLImportLogic._add_layer(saved, group)
        results['layers'].append(saved.name())

    @staticmethod
    def _add_layer(layer, group, at_top=False):
        if group is not None:
            QgsProject.instance().addMapLayer(layer, False)
            if at_top:
                group.insertLayer(0, layer)
            else:
                group.addLayer(layer)
        else:
            QgsProject.instance().addMapLayer(layer)

    @staticmethod
    def _safe_name(name):
        """File/table safe version of a layer name."""
        return re.sub(r'[^A-Za-z0-9_\-]+', '_', name).strip('_') or 'layer'

    @staticmethod
    def _write_layer(layer, output_mode, output_path, state, errors):
        """Persist a memory layer to disk and return the reloaded layer."""
        if output_mode == 'memory' or not output_path:
            return layer

        display_name = layer.name()
        safe_name = LandXMLImportLogic._safe_name(display_name)

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.fileEncoding = 'UTF-8'

        if output_mode == 'gpkg':
            options.driverName = 'GPKG'
            options.layerName = safe_name
            if state['gpkg_started'] or os.path.exists(output_path):
                options.actionOnExistingFile = _writer_enum(
                    'ActionOnExistingFile', 'CreateOrOverwriteLayer')
            target = output_path
        else:
            options.driverName = 'ESRI Shapefile'
            target = os.path.join(output_path, safe_name + '.shp')

        try:
            result = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, target, QgsProject.instance().transformContext(), options)
        except AttributeError:
            result = QgsVectorFileWriter.writeAsVectorFormatV2(
                layer, target, QgsProject.instance().transformContext(), options)

        if result[0] != _writer_enum('WriterError', 'NoError'):
            errors.append("Could not write '{0}': {1}".format(
                display_name, result[1]))
            return layer

        if output_mode == 'gpkg':
            state['gpkg_started'] = True
            uri = '{0}|layername={1}'.format(target, safe_name)
        else:
            uri = target

        saved = QgsVectorLayer(uri, display_name, 'ogr')
        if not saved.isValid():
            errors.append(
                "Wrote '{0}' but could not reload it from {1}.".format(
                    display_name, uri))
            return layer
        return saved

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _transform_points(points, transform):
        if transform is None:
            return list(points)
        converted = []
        for x, y in points:
            pt = transform.transform(QgsPointXY(x, y))
            converted.append((pt.x(), pt.y()))
        return converted

    @staticmethod
    def _transform_3d_points(points, transform):
        if transform is None:
            return list(points)
        converted = []
        for x, y, z in points:
            projected = transform.transform(QgsPointXY(x, y))
            converted.append((projected.x(), projected.y(), z))
        return converted

    @staticmethod
    def _station_table(points, sta_start):
        """Cumulative station value for every vertex of the alignment."""
        stations = [sta_start]
        for i in range(1, len(points)):
            stations.append(stations[-1] + math.hypot(
                points[i][0] - points[i - 1][0],
                points[i][1] - points[i - 1][1]))
        return stations

    @staticmethod
    def _profile_sample_stations(vertical, horizontal_stations, vertical_tolerance):
        """Vertical geometry stations merged with the horizontal vertex stations."""
        start = vertical.start_station
        end = vertical.end_station
        sample = set(vertical.critical_stations(vertical_tolerance))
        for station in horizontal_stations:
            if start - 1e-6 <= station <= end + 1e-6:
                sample.add(round(station, 6))
        return sorted(sample)

    @staticmethod
    def _point_at_station(points, stations, station):
        """Interpolate an (x, y) position for a station, clamped to the ends."""
        if not points:
            return None
        if station <= stations[0]:
            return points[0]
        if station >= stations[-1]:
            return points[-1]

        for i in range(1, len(stations)):
            if station <= stations[i]:
                span = stations[i] - stations[i - 1]
                ratio = 0.0 if span <= 0 else (station - stations[i - 1]) / span
                return (
                    points[i - 1][0] + ratio * (points[i][0] - points[i - 1][0]),
                    points[i - 1][1] + ratio * (points[i][1] - points[i - 1][1]),
                )
        return points[-1]

    @staticmethod
    def crs_from_authid(authid):
        return QgsCoordinateReferenceSystem(authid)

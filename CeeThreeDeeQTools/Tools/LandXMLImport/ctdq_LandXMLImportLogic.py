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
    QgsGeometry,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsPoint,
    QgsPointXY,
    QgsProject,
    QgsRendererCategory,
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
        needed = set(alignment_names) | {key[0] for key in profile_keys}

        if not needed and not surface_names and not point_group_keys:
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

        report("Import complete.", 100)
        return results

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

# -*- coding: utf-8 -*-
"""
Turns LandXML TIN surfaces into QGIS mesh layers.

MDAL has no in-memory mesh provider, so the triangulation is written to a
2DM file (SMS mesh format) and loaded from there. Faces with three or four
nodes are supported; anything else is skipped with a warning.

Civil 3D marks faces removed by boundaries and voids with ``i="1"``. Those
are dropped by default, which is exactly what produces concave outlines and
interior holes - a QGIS mesh has no convexity requirement. Vertices left
unreferenced by the retained faces are not written.
"""

import math
import os
import tempfile

from qgis.core import (
    QgsColorRampShader,
    QgsMeshDatasetIndex,
    QgsMeshLayer,
)
from qgis.PyQt.QtGui import QColor

ELEMENT_TAGS = {3: 'E3T', 4: 'E4Q'}
ELEVATION_GROUP_NAME = 'Elevation'
SLOPE_PERCENT_GROUP_NAME = 'Slope (%)'
SLOPE_BREAK_PERCENT = 15.0
SLOPE_FLAT_COLOUR = '#888888'
SLOPE_STEEP_COLOUR = '#565656'


def _enum(cls, scope, name):
    """Enum value tolerant of scoped/unscoped QGIS builds."""
    scoped = getattr(cls, scope, None)
    value = getattr(scoped, name, None) if scoped is not None else None
    return value if value is not None else getattr(cls, name)


class LandXMLMesh:
    """Writes 2DM files and builds mesh layers from parsed surfaces."""

    @staticmethod
    def output_folder(output_mode, output_path, file_path):
        """Folder for the generated .2dm files."""
        if output_mode == 'shp' and output_path:
            return output_path
        if output_mode == 'gpkg' and output_path:
            return os.path.dirname(output_path)
        folder = os.path.join(
            tempfile.gettempdir(), 'ctdq_landxml',
            os.path.splitext(os.path.basename(file_path))[0] or 'surfaces')
        os.makedirs(folder, exist_ok=True)
        return folder

    @staticmethod
    def create_layer(surface, folder, safe_name, target_crs, transform,
                     warnings, errors, include_hidden=False):
        """Write the surface as 2DM and return a :class:`QgsMeshLayer`."""
        points = surface.get('points') or {}
        faces = list(surface.get('faces') or [])
        hidden = surface.get('hidden_faces') or []
        if include_hidden:
            faces.extend(hidden)
        elif hidden:
            warnings.append(
                "Surface '{0}': {1} hidden face(s) omitted (boundaries/voids).".format(
                    surface['name'], len(hidden)))

        if not points or not faces:
            errors.append(
                "Surface '{0}' has no triangulation to import.".format(
                    surface['name']))
            return None

        path = os.path.join(folder, safe_name + '.2dm')
        try:
            nodes, elements = LandXMLMesh._write_2dm(
                path, points, faces, transform, surface['name'], warnings)
        except OSError as exc:
            errors.append("Could not write '{0}': {1}".format(path, exc))
            return None

        if not elements:
            errors.append(
                "Surface '{0}' produced no usable faces.".format(surface['name']))
            return None

        layer = QgsMeshLayer(path, surface['name'], 'mdal')
        if not layer.isValid():
            errors.append(
                "Surface '{0}' was written to {1} but could not be loaded.".format(
                    surface['name'], path))
            return None
        layer.setCrs(target_crs)

        LandXMLMesh._rename_elevation_group(layer, warnings)
        LandXMLMesh._add_slope_dataset(
            layer, path, nodes, elements, surface['name'], warnings)
        LandXMLMesh._style_slope(layer, warnings)
        return layer

    @staticmethod
    def _rename_elevation_group(layer, warnings):
        """MDAL calls the 2DM vertex Z group 'Bed Elevation'."""
        # The setter is setDatasetGroupTreeRootItem on newer QGIS builds
        setter = (getattr(layer, 'setDatasetGroupTreeRootItem', None)
                  or getattr(layer, 'setDatasetGroupTreeItem', None))
        try:
            root = layer.datasetGroupTreeRootItem()
            if root is None or root.childCount() == 0 or setter is None:
                return
            root.child(0).setName(ELEVATION_GROUP_NAME)
            setter(root)
        except Exception as exc:
            warnings.append("Could not rename the elevation dataset: {0}".format(exc))

    @staticmethod
    def _add_slope_dataset(layer, mesh_path, nodes, elements, surface_name,
                           warnings):
        """Write per-face slope as an ASCII .dat dataset and attach it.

        MDAL reads a .dat as element (face) data only when the file name
        contains ``_els``; otherwise values are read per vertex.
        """
        values = LandXMLMesh._face_slopes(nodes, elements)
        dat_path = os.path.splitext(mesh_path)[0] + '_slope_pct_els.dat'

        try:
            LandXMLMesh._write_ascii_dat(
                dat_path, SLOPE_PERCENT_GROUP_NAME, values,
                len(nodes), len(elements))
        except OSError as exc:
            warnings.append("Surface '{0}': slope dataset not written ({1}).".format(
                surface_name, exc))
            return

        try:
            added = layer.addDatasets(dat_path)
        except Exception as exc:
            added = False
            warnings.append("Surface '{0}': slope dataset error ({1}).".format(
                surface_name, exc))
        if not added:
            warnings.append(
                "Surface '{0}': slope dataset could not be attached.".format(
                    surface_name))

    @staticmethod
    def _style_slope(layer, warnings):
        """Show slope with two discrete equal-interval classes split at 15%."""
        try:
            index = LandXMLMesh._group_index(layer, SLOPE_PERCENT_GROUP_NAME)
            if index is None:
                return

            maximum = SLOPE_BREAK_PERCENT * 2.0
            shader = QgsColorRampShader(0.0, maximum)
            shader.setColorRampType(_enum(QgsColorRampShader, 'Type', 'Discrete'))
            shader.setClassificationMode(
                _enum(QgsColorRampShader, 'ClassificationMode', 'EqualInterval'))
            shader.setColorRampItemList([
                QgsColorRampShader.ColorRampItem(
                    SLOPE_BREAK_PERCENT, QColor(SLOPE_FLAT_COLOUR),
                    '<= {0:g}%'.format(SLOPE_BREAK_PERCENT)),
                QgsColorRampShader.ColorRampItem(
                    maximum, QColor(SLOPE_STEEP_COLOUR),
                    '> {0:g}%'.format(SLOPE_BREAK_PERCENT)),
            ])

            settings = layer.rendererSettings()
            scalar_settings = settings.scalarSettings(index)
            scalar_settings.setClassificationMinimumMaximum(0.0, maximum)
            scalar_settings.setColorRampShader(shader)
            settings.setScalarSettings(index, scalar_settings)
            settings.setActiveScalarDatasetGroup(index)
            layer.setRendererSettings(settings)
            layer.setStaticScalarDatasetIndex(QgsMeshDatasetIndex(index, 0))
        except Exception as exc:
            warnings.append("Could not style the slope dataset: {0}".format(exc))

    @staticmethod
    def _group_index(layer, name):
        for index in layer.datasetGroupsIndexes():
            metadata = layer.datasetGroupMetadata(QgsMeshDatasetIndex(index, 0))
            if metadata.name() == name:
                return index
        return None

    @staticmethod
    def _write_ascii_dat(path, group_name, values, node_count, element_count):
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write("DATASET\n")
            handle.write('OBJTYPE "mesh2d"\n')
            handle.write("BEGSCL\n")
            handle.write("ND {0}\n".format(node_count))
            handle.write("NC {0}\n".format(element_count))
            handle.write('NAME "{0}"\n'.format(group_name))
            handle.write("TS 0 0.000000\n")
            for value in values:
                handle.write("{0:.6f}\n".format(value))
            handle.write("ENDDS\n")

    @staticmethod
    def _face_slopes(nodes, elements):
        """Dip of each face (rise/run as a percentage).

        The face normal is the cross product of two edges; the plane's dip
        against horizontal is ``|n_xy| / |n_z|``, which is winding independent.
        """
        slopes = []
        for face in elements:
            a, b, c = (nodes[face[0] - 1], nodes[face[1] - 1], nodes[face[2] - 1])
            ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
            vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            slopes.append(0.0 if abs(nz) < 1e-12
                          else math.hypot(nx, ny) / abs(nz) * 100.0)
        return slopes

    @staticmethod
    def _write_2dm(path, points, faces, transform, surface_name, warnings):
        usable = []
        skipped = 0
        for face in faces:
            if len(face) in ELEMENT_TAGS and all(pid in points for pid in face):
                usable.append(face)
            else:
                skipped += 1

        used_ids = {pid for face in usable for pid in face}
        index = {}
        nodes = []

        with open(path, 'w', encoding='utf-8') as handle:
            handle.write("MESH2D\n")
            for point_id, (x, y, z) in points.items():
                if point_id not in used_ids:
                    continue
                index[point_id] = len(index) + 1
                if transform is not None:
                    x, y = transform(x, y)
                nodes.append((x, y, z))
                handle.write("ND {0} {1:.6f} {2:.6f} {3:.6f}\n".format(
                    index[point_id], x, y, z))

            elements = []
            for number, face in enumerate(usable, start=1):
                nodes_of_face = tuple(index[pid] for pid in face)
                elements.append(nodes_of_face)
                handle.write("{0} {1} {2} 1\n".format(
                    ELEMENT_TAGS[len(face)], number,
                    " ".join(str(n) for n in nodes_of_face)))

        if skipped:
            warnings.append(
                "Surface '{0}': {1} face(s) skipped (unsupported shape or "
                "missing points).".format(surface_name, skipped))
        return nodes, elements

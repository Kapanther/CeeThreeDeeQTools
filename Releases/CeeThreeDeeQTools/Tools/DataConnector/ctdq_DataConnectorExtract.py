"""
***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""

import os
import re

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsCoordinateReferenceSystem,
    QgsFeatureRequest,
    QgsFeature,
    QgsGeometry,
    QgsRectangle,
    QgsWkbTypes,
    QgsMapLayer,
)

from .ctdq_DataConnectorLogic import DataConnectorLogic
from .ctdq_DataConnectorStyle import DataConnectorStyle

# Output format / mode identifiers shared with the Add dialog.
FORMAT_GPKG = 'gpkg'
FORMAT_SHP = 'shp'
MODE_COMBINED = 'combined'
MODE_SEPARATE = 'separate'
MODE_SINGLE_FILE = 'single'
MODE_FOLDER = 'folder'


class DataConnectorExtractor:
    """Clips a streamed source to an extent and writes it to disk. UI-free."""

    @staticmethod
    def extract_layers(
        source_layers: list,
        extent_geometry: QgsGeometry,
        extent_crs: QgsCoordinateReferenceSystem,
        target_crs: QgsCoordinateReferenceSystem,
        output_format: str,
        output_mode: str,
        output_path: str,
        clip_to_geometry: bool = False,
        replace_source: bool = False,
        add_to_project: bool = True,
        progress_callback=None,
    ) -> dict:
        """
        Extract each streamed layer, write it out, tag it with connection metadata.

        Args:
            source_layers: streamed QgsVectorLayer objects to extract
            extent_geometry: extent/mask geometry used to limit the extraction
            extent_crs: CRS the extent geometry is expressed in
            target_crs: CRS to write the extracted data in
            output_format: FORMAT_GPKG or FORMAT_SHP
            output_mode: MODE_COMBINED/MODE_SEPARATE (gpkg) or MODE_SINGLE_FILE/MODE_FOLDER (shp)
            output_path: destination file or folder, depending on format/mode
            clip_to_geometry: intersect geometries with the extent instead of bbox filtering only
            replace_source: remove the streamed layer once extraction succeeds
            add_to_project: load the extracted layer into the current project

        Returns:
            dict with 'extracted', 'errors', 'warnings' and 'layers'
        """
        results = {'extracted': 0, 'errors': [], 'warnings': [], 'layers': []}

        if not source_layers:
            results['errors'].append("No source layers selected.")
            return results

        transform_context = QgsProject.instance().transformContext()
        total = len(source_layers)
        first_write = True

        for index, source_layer in enumerate(source_layers):
            base_percent = int((index / total) * 100)
            DataConnectorExtractor._report(
                progress_callback, f"Extracting '{source_layer.name()}'...", base_percent
            )

            try:
                destination, layer_name = DataConnectorExtractor._resolve_destination(
                    source_layer.name(), output_format, output_mode, output_path
                )

                extracted = DataConnectorExtractor._extract_single(
                    source_layer,
                    extent_geometry,
                    extent_crs,
                    target_crs,
                    destination,
                    layer_name,
                    output_format,
                    clip_to_geometry,
                    overwrite_file=(output_format != FORMAT_GPKG or output_mode != MODE_COMBINED or first_write),
                    transform_context=transform_context,
                    progress_callback=progress_callback,
                    base_percent=base_percent,
                    step_percent=int(100 / total),
                    results=results,
                )

                if extracted is None:
                    continue

                first_write = False
                results['extracted'] += 1
                results['layers'].append(extracted)

                DataConnectorExtractor._finalise_layer(
                    extracted, source_layer, target_crs, extent_geometry, extent_crs,
                    add_to_project, replace_source, results
                )

            except Exception as exc:
                results['errors'].append(
                    f"Failed to extract '{source_layer.name()}': {exc}"
                )

        DataConnectorExtractor._report(progress_callback, "Extraction complete", 100)
        return results

    # ------------------------------------------------------------- internals

    @staticmethod
    def _report(progress_callback, message, percent):
        if progress_callback:
            progress_callback(message, percent)

    @staticmethod
    def _safe_name(name: str) -> str:
        """Filesystem-safe version of a layer name."""
        cleaned = re.sub(r'[\\/:*?"<>|]+', '_', name).strip()
        return cleaned or 'layer'

    @staticmethod
    def _resolve_destination(layer_name, output_format, output_mode, output_path):
        """Return (destination_file, layer_name_in_file) for one source layer."""
        safe_name = DataConnectorExtractor._safe_name(layer_name)

        if output_format == FORMAT_GPKG:
            if output_mode == MODE_COMBINED:
                return output_path, layer_name
            return os.path.join(output_path, f"{safe_name}.gpkg"), layer_name

        if output_mode == MODE_FOLDER:
            return os.path.join(output_path, f"{safe_name}.shp"), safe_name
        return output_path, safe_name

    @staticmethod
    def _extract_single(
        source_layer, extent_geometry, extent_crs, target_crs, destination, layer_name,
        output_format, clip_to_geometry, overwrite_file, transform_context,
        progress_callback, base_percent, step_percent, results
    ):
        """Clip one layer and write it out. Returns the loaded output layer or None."""
        source_crs = source_layer.crs()

        # Extent -> source CRS for server-side/bbox filtering
        request_geometry = QgsGeometry(extent_geometry)
        if extent_crs.isValid() and source_crs.isValid() and extent_crs != source_crs:
            to_source = QgsCoordinateTransform(extent_crs, source_crs, transform_context)
            request_geometry.transform(to_source)

        request = QgsFeatureRequest().setFilterRect(request_geometry.boundingBox())

        # Clip geometry expressed in the target CRS, where output geometries live
        clip_geometry = QgsGeometry(extent_geometry)
        if extent_crs.isValid() and target_crs.isValid() and extent_crs != target_crs:
            clip_geometry.transform(QgsCoordinateTransform(extent_crs, target_crs, transform_context))

        to_target = None
        if source_crs.isValid() and target_crs.isValid() and source_crs != target_crs:
            to_target = QgsCoordinateTransform(source_crs, target_crs, transform_context)

        memory_layer = DataConnectorExtractor._build_memory_layer(source_layer, target_crs, layer_name)
        provider = memory_layer.dataProvider()

        features = []
        count = 0
        for feature in source_layer.getFeatures(request):
            count += 1
            if count % 500 == 0:
                DataConnectorExtractor._report(
                    progress_callback,
                    f"Reading '{source_layer.name()}' - {count} features...",
                    base_percent,
                )

            new_feature = QgsFeature(memory_layer.fields())
            new_feature.setAttributes(feature.attributes())

            geometry = feature.geometry()
            if geometry and not geometry.isEmpty():
                if to_target:
                    geometry = QgsGeometry(geometry)
                    geometry.transform(to_target)
                if clip_to_geometry:
                    geometry = geometry.intersection(clip_geometry)
                    if geometry.isEmpty():
                        continue
                new_feature.setGeometry(geometry)

            features.append(new_feature)

        if not features:
            results['warnings'].append(
                f"'{source_layer.name()}': no features found in the selected extent - skipped."
            )
            return None

        provider.addFeatures(features)
        memory_layer.updateExtents()

        DataConnectorExtractor._report(
            progress_callback,
            f"Writing '{source_layer.name()}' ({len(features)} features)...",
            base_percent + max(step_percent // 2, 1),
        )

        DataConnectorExtractor._ensure_parent_dir(destination)

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.layerName = layer_name
        options.fileEncoding = 'UTF-8'
        if output_format == FORMAT_GPKG:
            options.driverName = 'GPKG'
            options.actionOnExistingFile = (
                QgsVectorFileWriter.CreateOrOverwriteFile if overwrite_file
                else QgsVectorFileWriter.CreateOrOverwriteLayer
            )
        else:
            options.driverName = 'ESRI Shapefile'
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

        write_result = QgsVectorFileWriter.writeAsVectorFormatV3(
            memory_layer, destination, transform_context, options
        )

        if write_result[0] != QgsVectorFileWriter.NoError:
            results['errors'].append(
                f"'{source_layer.name()}': write failed - {write_result[1]}"
            )
            return None

        return DataConnectorExtractor._load_output_layer(
            destination, layer_name, output_format, source_layer.name(), results
        )

    @staticmethod
    def _build_memory_layer(source_layer, target_crs, layer_name):
        """Create an in-memory layer matching the source schema in the target CRS."""
        geometry_name = QgsWkbTypes.displayString(source_layer.wkbType()) or 'Unknown'
        uri = f"{geometry_name}?crs={target_crs.authid()}"
        memory_layer = QgsVectorLayer(uri, layer_name, 'memory')
        memory_layer.dataProvider().addAttributes(source_layer.fields().toList())
        memory_layer.updateFields()
        return memory_layer

    @staticmethod
    def _ensure_parent_dir(destination):
        parent = os.path.dirname(destination)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

    @staticmethod
    def _load_output_layer(destination, layer_name, output_format, display_name, results):
        """Open the freshly written layer so it can be tagged and added to the project."""
        if output_format == FORMAT_GPKG:
            uri = f"{destination}|layername={layer_name}"
        else:
            uri = destination

        layer = QgsVectorLayer(uri, display_name, 'ogr')
        if not layer.isValid():
            results['errors'].append(
                f"'{display_name}': written to {destination} but the result could not be opened."
            )
            return None
        return layer

    @staticmethod
    def _finalise_layer(
        extracted_layer, source_layer, target_crs, extent_geometry, extent_crs,
        add_to_project, replace_source, results
    ):
        """Copy styling, tag with connection metadata, and place the layer in the project."""
        DataConnectorStyle.copy_style(source_layer, extracted_layer, results)

        extent_rect = extent_geometry.boundingBox()
        DataConnectorLogic.write_connection_info(
            extracted_layer,
            source_uri=source_layer.dataProvider().dataSourceUri(),
            service=DataConnectorLogic.service_name_for_provider(source_layer.dataProvider().name()),
            provider_key=source_layer.dataProvider().name(),
            source_crs=source_layer.crs().authid(),
            target_crs=target_crs.authid(),
            extent=f"{extent_rect.xMinimum()},{extent_rect.yMinimum()},"
                   f"{extent_rect.xMaximum()},{extent_rect.yMaximum()}",
            extent_crs=extent_crs.authid(),
        )

        if not add_to_project:
            return

        project = QgsProject.instance()
        project.addMapLayer(extracted_layer)

        if replace_source:
            try:
                project.removeMapLayer(source_layer.id())
            except Exception as exc:
                results['warnings'].append(
                    f"Could not remove streamed layer '{extracted_layer.name()}': {exc}"
                )

    # ------------------------------------------------------------ extent help

    @staticmethod
    def build_extent_geometry(mode, iface, extent_layer=None, mask_layer=None):
        """
        Resolve the chosen extent option into (geometry, crs, clip_to_geometry).

        Raises ValueError when the required layer is missing.
        """
        from .ctdq_ExtentWidget import (
            EXTENT_MODE_CANVAS, EXTENT_MODE_LAYER, EXTENT_MODE_MASK
        )

        if mode == EXTENT_MODE_LAYER:
            if extent_layer is None:
                raise ValueError("No extent layer selected.")
            return QgsGeometry.fromRect(extent_layer.extent()), extent_layer.crs(), False

        if mode == EXTENT_MODE_MASK:
            if mask_layer is None:
                raise ValueError("No mask layer selected.")
            geometries = [f.geometry() for f in mask_layer.getFeatures() if f.hasGeometry()]
            if not geometries:
                raise ValueError(f"Mask layer '{mask_layer.name()}' has no geometries.")
            combined = QgsGeometry.unaryUnion(geometries)
            if combined.isEmpty():
                raise ValueError(f"Mask layer '{mask_layer.name()}' produced an empty mask.")
            return combined, mask_layer.crs(), True

        canvas = iface.mapCanvas()
        return QgsGeometry.fromRect(canvas.extent()), canvas.mapSettings().destinationCrs(), False

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
import shutil

from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsGeometry,
    QgsRectangle,
    QgsCoordinateReferenceSystem,
    QgsDataProvider,
)

from .ctdq_DataConnectorLogic import DataConnectorLogic
from .ctdq_RasterTileMath import RasterTileMath
from .ctdq_DataConnectorRasterExtract import (
    DataConnectorRasterExtractor,
    RASTER_FORMAT_GPKG,
    RASTER_FORMAT_GTIFF,
)


class DataConnectorRasterRefresh:
    """Re-renders connected raster layers from their stored tile service."""

    @staticmethod
    def refresh_layers(
        layers: list,
        override_extent_geometry: QgsGeometry = None,
        override_extent_crs: QgsCoordinateReferenceSystem = None,
        override_zoom: int = None,
        progress_callback=None,
    ) -> dict:
        """
        Reload each connected raster layer from its originating service.

        Stored extent and zoom are reused unless overrides are supplied.
        """
        results = {'refreshed': 0, 'errors': [], 'warnings': []}

        if not layers:
            results['errors'].append("No connected raster layers to refresh.")
            return results

        total = len(layers)
        for index, layer in enumerate(layers):
            percent = int((index / total) * 100)
            DataConnectorRasterRefresh._report(
                progress_callback, f"Refreshing '{layer.name()}'...", percent
            )

            try:
                DataConnectorRasterRefresh._refresh_one(
                    layer, override_extent_geometry, override_extent_crs,
                    override_zoom, progress_callback, percent, results
                )
            except Exception as exc:
                results['errors'].append(f"'{layer.name()}': {exc}")

        DataConnectorRasterRefresh._report(progress_callback, "Refresh complete", 100)
        return results

    # ------------------------------------------------------------- internals

    @staticmethod
    def _report(progress_callback, message, percent):
        if progress_callback:
            progress_callback(message, percent)

    @staticmethod
    def _refresh_one(
        layer, override_geometry, override_crs, override_zoom,
        progress_callback, percent, results
    ):
        info = DataConnectorLogic.read_connection_info(layer)
        if not info:
            results['warnings'].append(f"'{layer.name()}': no connection metadata - skipped.")
            return

        source_layer = DataConnectorRasterRefresh._open_source(info, layer.name())

        extent_geometry, extent_crs = DataConnectorRasterRefresh._resolve_extent(
            info, override_geometry, override_crs
        )
        zoom = DataConnectorRasterRefresh._resolve_zoom(info, override_zoom)
        target_crs = layer.crs()

        output_path, table_name, output_format = (
            DataConnectorRasterRefresh._describe_output(layer)
        )

        estimate = RasterTileMath.estimate(
            extent_geometry.boundingBox(), extent_crs, zoom
        )
        DataConnectorRasterRefresh._report(
            progress_callback,
            f"Downloading approx {estimate['tiles']} tile(s) for '{layer.name()}'...",
            percent,
        )

        temp_path = f"{output_path}.ctdqrefresh{os.path.splitext(output_path)[1]}"
        DataConnectorRasterRefresh._remove_quietly(temp_path)

        output_extent = DataConnectorRasterExtractor._extent_in_crs(
            extent_geometry.boundingBox(), extent_crs, target_crs
        )
        DataConnectorRasterExtractor._write_raster(
            source_layer, temp_path, output_format, table_name,
            estimate['width'], estimate['height'], output_extent, target_crs
        )

        if output_format == RASTER_FORMAT_GPKG:
            DataConnectorRasterExtractor._build_overviews(
                temp_path, table_name, estimate['width'], estimate['height'], results
            )

        DataConnectorRasterRefresh._report(
            progress_callback, f"Replacing '{layer.name()}' data...", percent
        )
        DataConnectorRasterRefresh._swap_in(
            layer, output_path, temp_path, table_name, output_format
        )

        stored_extent, stored_extent_crs = DataConnectorRasterRefresh._extent_for_metadata(
            info, extent_geometry, extent_crs, override_geometry is not None
        )
        DataConnectorLogic.write_connection_info(
            layer,
            source_uri=info.get('source_uri', ''),
            service=info.get('service', ''),
            provider_key=info.get('provider_key', ''),
            source_crs=info.get('source_crs', ''),
            target_crs=target_crs.authid(),
            extent=stored_extent,
            extent_crs=stored_extent_crs,
            zoom=zoom,
        )

        layer.triggerRepaint()
        results['refreshed'] += 1

    @staticmethod
    def _open_source(info, display_name):
        uri = info.get('source_uri', '')
        provider = info.get('provider_key', '')
        if not uri or not provider:
            raise ValueError("stored connection is incomplete.")

        source_layer = QgsRasterLayer(uri, f"{display_name} (source)", provider)
        if not source_layer.isValid():
            raise ValueError("could not connect to the original data source.")
        return source_layer

    @staticmethod
    def _resolve_extent(info, override_geometry, override_crs):
        if override_geometry is not None:
            return override_geometry, override_crs

        parts = [part for part in info.get('extent', '').split(',') if part.strip()]
        if len(parts) != 4:
            raise ValueError("stored extent is missing or invalid.")

        try:
            xmin, ymin, xmax, ymax = (float(part) for part in parts)
        except ValueError:
            raise ValueError("stored extent could not be read.")

        crs = QgsCoordinateReferenceSystem(info.get('extent_crs', ''))
        if not crs.isValid():
            crs = QgsProject.instance().crs()

        return QgsGeometry.fromRect(QgsRectangle(xmin, ymin, xmax, ymax)), crs

    @staticmethod
    def _resolve_zoom(info, override_zoom):
        if override_zoom is not None:
            return int(override_zoom)

        stored = info.get('zoom')
        if stored is None:
            raise ValueError("no stored zoom level - choose a zoom level to refresh with.")
        return int(stored)

    @staticmethod
    def _extent_for_metadata(info, extent_geometry, extent_crs, extent_changed):
        if not extent_changed:
            return info.get('extent', ''), info.get('extent_crs', '')

        rect = extent_geometry.boundingBox()
        return (
            f"{rect.xMinimum()},{rect.yMinimum()},{rect.xMaximum()},{rect.yMaximum()}",
            extent_crs.authid() if extent_crs else '',
        )

    @staticmethod
    def _describe_output(layer):
        """Split the layer's source into (file path, raster table, format)."""
        source = layer.source()

        if source.startswith('GPKG:'):
            # GPKG:<path>:<table>, where the path may itself contain a drive colon
            remainder = source[len('GPKG:'):]
            separator = remainder.rfind(':')
            if separator <= 1:
                raise ValueError("could not read the GeoPackage source path.")
            return remainder[:separator], remainder[separator + 1:], RASTER_FORMAT_GPKG

        path = source.split('|')[0]
        if path.lower().endswith('.gpkg'):
            return path, os.path.splitext(os.path.basename(path))[0], RASTER_FORMAT_GPKG

        return path, os.path.splitext(os.path.basename(path))[0], RASTER_FORMAT_GTIFF

    @staticmethod
    def _swap_in(layer, output_path, temp_path, table_name, output_format):
        """
        Replace the layer's file with the freshly rendered one.

        The layer is pointed at the temp file first so the original is released,
        then pointed back once the original has been overwritten.
        """
        temp_uri = DataConnectorRasterRefresh._uri_for(temp_path, table_name, output_format)
        original_uri = DataConnectorRasterRefresh._uri_for(output_path, table_name, output_format)
        name = layer.name()

        DataConnectorRasterRefresh._set_source(layer, temp_uri, name)

        try:
            DataConnectorRasterRefresh._remove_quietly(output_path)
            shutil.copyfile(temp_path, output_path)
        finally:
            DataConnectorRasterRefresh._set_source(layer, original_uri, name)

        DataConnectorRasterRefresh._remove_quietly(temp_path)

        if not layer.isValid():
            raise ValueError("refreshed raster could not be reopened.")

    @staticmethod
    def _uri_for(path, table_name, output_format):
        if output_format == RASTER_FORMAT_GPKG:
            return f"GPKG:{path}:{table_name}"
        return path

    @staticmethod
    def _set_source(layer, uri, name):
        try:
            layer.setDataSource(uri, name, 'gdal', QgsDataProvider.ProviderOptions())
        except TypeError:
            layer.setDataSource(uri, name, 'gdal')

    @staticmethod
    def _remove_quietly(path):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

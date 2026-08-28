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
    QgsRasterLayer,
    QgsRasterPipe,
    QgsRasterProjector,
    QgsRasterFileWriter,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsRectangle,
)

from .ctdq_DataConnectorLogic import DataConnectorLogic
from .ctdq_RasterTileMath import RasterTileMath, TILE_SIZE

RASTER_FORMAT_GPKG = 'gpkg'
RASTER_FORMAT_GTIFF = 'gtiff'


class DataConnectorRasterExtractor:
    """Renders a tiled raster service to a local GeoPackage or GeoTIFF."""

    @staticmethod
    def extract_layer(
        source_layer,
        extent_geometry,
        extent_crs: QgsCoordinateReferenceSystem,
        target_crs: QgsCoordinateReferenceSystem,
        zoom: int,
        output_format: str,
        output_path: str,
        build_overviews: bool = True,
        replace_source: bool = False,
        add_to_project: bool = True,
        progress_callback=None,
    ) -> dict:
        """
        Extract one streamed raster layer at the given zoom level.

        Returns dict with 'extracted', 'errors', 'warnings' and 'layers'.
        """
        results = {'extracted': 0, 'errors': [], 'warnings': [], 'layers': []}

        if source_layer is None:
            results['errors'].append("No source raster layer selected.")
            return results

        try:
            DataConnectorRasterExtractor._report(
                progress_callback, f"Preparing '{source_layer.name()}'...", 5
            )

            estimate = RasterTileMath.estimate(
                extent_geometry.boundingBox(), extent_crs, zoom
            )
            output_extent = DataConnectorRasterExtractor._extent_in_crs(
                extent_geometry.boundingBox(), extent_crs, target_crs
            )

            DataConnectorRasterExtractor._ensure_parent_dir(output_path)

            DataConnectorRasterExtractor._report(
                progress_callback,
                f"Downloading approx {estimate['tiles']} tile(s) "
                f"({estimate['width']} x {estimate['height']} px)...",
                20,
            )

            layer_name = DataConnectorRasterExtractor._safe_name(source_layer.name())
            DataConnectorRasterExtractor._write_raster(
                source_layer, output_path, output_format, layer_name,
                estimate['width'], estimate['height'], output_extent, target_crs
            )

            if output_format == RASTER_FORMAT_GPKG and build_overviews:
                DataConnectorRasterExtractor._report(
                    progress_callback, "Building tile zoom levels...", 80
                )
                DataConnectorRasterExtractor._build_overviews(
                    output_path, layer_name, estimate['width'], estimate['height'], results
                )

            DataConnectorRasterExtractor._report(progress_callback, "Loading result...", 90)

            extracted = DataConnectorRasterExtractor._load_output_layer(
                output_path, layer_name, output_format, source_layer.name(), results
            )
            if extracted is None:
                return results

            results['extracted'] = 1
            results['layers'].append(extracted)

            DataConnectorRasterExtractor._finalise_layer(
                extracted, source_layer, target_crs, extent_geometry, extent_crs,
                zoom, add_to_project, replace_source, results
            )

        except Exception as exc:
            results['errors'].append(f"Failed to extract '{source_layer.name()}': {exc}")

        DataConnectorRasterExtractor._report(progress_callback, "Extraction complete", 100)
        return results

    # ------------------------------------------------------------- internals

    @staticmethod
    def _report(progress_callback, message, percent):
        if progress_callback:
            progress_callback(message, percent)

    @staticmethod
    def _safe_name(name: str) -> str:
        """Filesystem/table-safe version of a layer name."""
        cleaned = re.sub(r'[^A-Za-z0-9_]+', '_', name).strip('_')
        return cleaned or 'raster'

    @staticmethod
    def _ensure_parent_dir(destination):
        parent = os.path.dirname(destination)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

    @staticmethod
    def _extent_in_crs(extent, source_crs, target_crs) -> QgsRectangle:
        if not source_crs.isValid() or not target_crs.isValid() or source_crs == target_crs:
            return extent
        transform = QgsCoordinateTransform(
            source_crs, target_crs, QgsProject.instance().transformContext()
        )
        return transform.transformBoundingBox(extent)

    @staticmethod
    def _write_raster(
        source_layer, output_path, output_format, layer_name,
        width, height, output_extent, target_crs
    ):
        """Render the service through a raster pipe into the chosen file format."""
        provider = source_layer.dataProvider()
        transform_context = QgsProject.instance().transformContext()

        pipe = QgsRasterPipe()
        if not pipe.set(provider.clone()):
            raise ValueError("could not read from the raster source.")

        if provider.crs() != target_crs:
            projector = QgsRasterProjector()
            try:
                projector.setCrs(provider.crs(), target_crs, transform_context)
            except TypeError:
                projector.setCrs(provider.crs(), target_crs)
            if not pipe.insert(2, projector):
                raise ValueError("could not reproject the raster source.")

        writer = QgsRasterFileWriter(output_path)
        if output_format == RASTER_FORMAT_GPKG:
            writer.setOutputFormat('GPKG')
            writer.setCreateOptions([
                f'RASTER_TABLE={layer_name}',
                'APPEND_SUBDATASET=YES',
                'TILE_FORMAT=PNG_JPEG',
            ])
        else:
            writer.setOutputFormat('GTiff')
            writer.setCreateOptions(['COMPRESS=DEFLATE', 'TILED=YES'])

        try:
            error = writer.writeRaster(
                pipe, width, height, output_extent, target_crs, transform_context
            )
        except TypeError:
            error = writer.writeRaster(pipe, width, height, output_extent, target_crs)

        if error != QgsRasterFileWriter.NoError:
            raise ValueError(f"raster write failed (code {error}).")

    @staticmethod
    def _overview_factors(width, height, minimum_size=TILE_SIZE):
        """Halving factors down to roughly one tile, giving one zoom level each."""
        factors = []
        factor = 2
        while max(width, height) / factor >= minimum_size:
            factors.append(factor)
            factor *= 2
            if len(factors) >= 12:
                break
        return factors

    @staticmethod
    def _build_overviews(output_path, layer_name, width, height, results):
        """Add reduced zoom levels, stored by GeoPackage as extra tile matrix rows."""
        try:
            from osgeo import gdal
        except ImportError:
            results['warnings'].append("GDAL bindings unavailable - zoom levels not built.")
            return

        factors = DataConnectorRasterExtractor._overview_factors(width, height)
        if not factors:
            results['warnings'].append(
                "Extract is smaller than one tile - only a single zoom level was created."
            )
            return

        dataset = None
        try:
            # Address the raster table directly; a gpkg may hold several of them
            dataset = gdal.Open(f"GPKG:{output_path}:{layer_name}", gdal.GA_Update)
            if dataset is None:
                dataset = gdal.Open(output_path, gdal.GA_Update)
            if dataset is None:
                results['warnings'].append("Could not reopen output to build zoom levels.")
                return

            if dataset.BuildOverviews('AVERAGE', factors) != 0:
                results['warnings'].append("GDAL reported an error building zoom levels.")
                return

            results['warnings'].append(
                f"Created {len(factors) + 1} zoom level(s) in the GeoPackage tile pyramid."
            )
        except Exception as exc:
            results['warnings'].append(f"Could not build zoom levels: {exc}")
        finally:
            dataset = None

    @staticmethod
    def _load_output_layer(output_path, layer_name, output_format, display_name, results):
        if output_format == RASTER_FORMAT_GPKG:
            uri = f"GPKG:{output_path}:{layer_name}"
        else:
            uri = output_path

        layer = QgsRasterLayer(uri, display_name, 'gdal')
        if not layer.isValid():
            results['errors'].append(
                f"'{display_name}': written to {output_path} but the result could not be opened."
            )
            return None
        return layer

    @staticmethod
    def _finalise_layer(
        extracted_layer, source_layer, target_crs, extent_geometry, extent_crs,
        zoom, add_to_project, replace_source, results
    ):
        """Tag with connection metadata and place the layer in the project."""
        extent_rect = extent_geometry.boundingBox()
        DataConnectorLogic.write_connection_info(
            extracted_layer,
            source_uri=source_layer.dataProvider().dataSourceUri(),
            service=DataConnectorLogic.service_name_for_provider(
                source_layer.dataProvider().name()
            ),
            provider_key=source_layer.dataProvider().name(),
            source_crs=source_layer.crs().authid(),
            target_crs=target_crs.authid(),
            extent=f"{extent_rect.xMinimum()},{extent_rect.yMinimum()},"
                   f"{extent_rect.xMaximum()},{extent_rect.yMaximum()}",
            extent_crs=extent_crs.authid(),
            zoom=zoom,
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

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

import math

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRectangle,
)

# Web Mercator tile pyramid constants (GoogleMapsCompatible scheme)
TILE_SIZE = 256
EARTH_CIRCUMFERENCE = 40075016.68557849
ZOOM_0_RESOLUTION = EARTH_CIRCUMFERENCE / TILE_SIZE  # metres per pixel at zoom 0
# OGC standardised rendering pixel size, used to convert a scale to a resolution
OGC_PIXEL_SIZE_M = 0.00028

WEB_MERCATOR = 'EPSG:3857'

MAX_ZOOM = 24
TILE_WARNING_THRESHOLD = 100


class RasterTileMath:
    """Zoom level / resolution / tile count helpers for Web Mercator tiled services."""

    @staticmethod
    def resolution_for_zoom(zoom: int) -> float:
        """Metres per pixel at a given zoom level."""
        return ZOOM_0_RESOLUTION / (2 ** zoom)

    @staticmethod
    def zoom_for_resolution(resolution: float) -> int:
        """Nearest zoom level that provides at least the requested resolution."""
        if resolution <= 0:
            return MAX_ZOOM
        zoom = math.log2(ZOOM_0_RESOLUTION / resolution)
        return max(0, min(MAX_ZOOM, int(round(zoom))))

    @staticmethod
    def zoom_for_scale(scale: float) -> int:
        """Zoom level matching a map scale denominator (1:scale)."""
        if scale <= 0:
            return MAX_ZOOM
        return RasterTileMath.zoom_for_resolution(scale * OGC_PIXEL_SIZE_M)

    @staticmethod
    def scale_for_zoom(zoom: int) -> float:
        """Approximate map scale denominator represented by a zoom level."""
        return RasterTileMath.resolution_for_zoom(zoom) / OGC_PIXEL_SIZE_M

    @staticmethod
    def canvas_zoom(canvas) -> int:
        """Current zoom level of the map canvas, measured in Web Mercator."""
        try:
            settings = canvas.mapSettings()
            resolution = settings.mapUnitsPerPixel()
            crs = settings.destinationCrs()

            if crs.authid() != WEB_MERCATOR:
                # Convert the canvas resolution into metres by measuring the visible
                # extent in Web Mercator instead of the project CRS.
                extent = RasterTileMath.to_web_mercator(canvas.extent(), crs)
                width_px = max(canvas.width(), 1)
                resolution = extent.width() / width_px

            return RasterTileMath.zoom_for_resolution(resolution)
        except Exception:
            return 0

    @staticmethod
    def to_web_mercator(extent: QgsRectangle, source_crs: QgsCoordinateReferenceSystem) -> QgsRectangle:
        """Reproject an extent into Web Mercator for zoom/tile calculations."""
        target = QgsCoordinateReferenceSystem(WEB_MERCATOR)
        if not source_crs.isValid() or source_crs == target:
            return extent

        transform = QgsCoordinateTransform(
            source_crs, target, QgsProject.instance().transformContext()
        )
        return transform.transformBoundingBox(extent)

    @staticmethod
    def estimate(extent: QgsRectangle, extent_crs: QgsCoordinateReferenceSystem, zoom: int) -> dict:
        """
        Pixel dimensions and tile count needed to cover an extent at a zoom level.

        Returns {'width', 'height', 'tiles', 'resolution'}.
        """
        mercator_extent = RasterTileMath.to_web_mercator(extent, extent_crs)
        resolution = RasterTileMath.resolution_for_zoom(zoom)

        width = max(1, int(math.ceil(mercator_extent.width() / resolution)))
        height = max(1, int(math.ceil(mercator_extent.height() / resolution)))
        tiles = math.ceil(width / TILE_SIZE) * math.ceil(height / TILE_SIZE)

        return {
            'width': width,
            'height': height,
            'tiles': int(tiles),
            'resolution': resolution,
        }

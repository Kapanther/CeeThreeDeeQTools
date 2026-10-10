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

import json
import logging
from datetime import datetime

from qgis.core import QgsProject, QgsMapLayer, QgsWkbTypes, QgsAbstractMetadataBase

LOGGER = logging.getLogger(__name__)


# Provider types considered "streamed" services that can be extracted/clipped.
STREAMED_VECTOR_PROVIDERS = {
    'wfs': 'WFS',
    'arcgisfeatureserver': 'REST (FeatureServer)',
    'afs': 'REST (FeatureServer)',
    'oapif': 'OGC API - Features',
}

STREAMED_RASTER_PROVIDERS = {
    'wms': 'WMS',
    'wcs': 'WCS',
    'arcgismapserver': 'REST (MapServer)',
    'ams': 'REST (MapServer)',
}

# Marks the metadata link that carries the Data Connector connection details.
LINK_NAME = 'CeeThreeDee Data Connector'
LINK_FORMAT = 'ctdq-dataconnector'

# Mirror of the link payload kept as a custom property for the current session.
CUSTOM_PROPERTY_KEY = 'ctdq/dataconnector'


class DataConnectorLogic:
    """Detection and connection-metadata handling for the Data Connector tool."""

    # ------------------------------------------------------------- detection

    @staticmethod
    def service_name_for_provider(provider_key: str) -> str:
        """Return a friendly service name for a provider key, or empty string if not streamed."""
        key = (provider_key or '').lower()
        return STREAMED_VECTOR_PROVIDERS.get(key) or STREAMED_RASTER_PROVIDERS.get(key) or ''

    @staticmethod
    def is_streamed_layer(layer, include_raster: bool = False) -> bool:
        """Whether a layer comes from a supported streaming service."""
        if layer is None or not layer.isValid():
            return False

        try:
            provider_key = layer.dataProvider().name().lower()
        except Exception:
            return False

        if layer.type() == QgsMapLayer.LayerType.VectorLayer:
            return provider_key in STREAMED_VECTOR_PROVIDERS
        if include_raster and layer.type() == QgsMapLayer.LayerType.RasterLayer:
            return provider_key in STREAMED_RASTER_PROVIDERS
        return False

    @staticmethod
    def get_streamed_layers(include_raster: bool = False) -> list:
        """Return all streamed layers currently loaded in the project."""
        return [
            layer for layer in QgsProject.instance().mapLayers().values()
            if DataConnectorLogic.is_streamed_layer(layer, include_raster)
        ]

    @staticmethod
    def get_streamed_raster_layers() -> list:
        """Return only the streamed raster layers loaded in the project."""
        return [
            layer for layer in QgsProject.instance().mapLayers().values()
            if layer.type() == QgsMapLayer.LayerType.RasterLayer
            and DataConnectorLogic.is_streamed_layer(layer, include_raster=True)
        ]

    @staticmethod
    def geometry_type_label(layer) -> str:
        """Human readable geometry/layer type, e.g. 'Vector Polygon' or 'Raster'."""
        if layer is None:
            return ''
        if layer.type() == QgsMapLayer.LayerType.RasterLayer:
            return 'Raster'
        if layer.type() != QgsMapLayer.LayerType.VectorLayer:
            return ''

        try:
            geom_name = QgsWkbTypes.geometryDisplayString(layer.geometryType())
        except Exception:
            geom_name = 'Unknown'
        return f"Vector {geom_name}"

    @staticmethod
    def get_connected_layers() -> list:
        """Return layers in the project that carry Data Connector metadata."""
        return [
            layer for layer in QgsProject.instance().mapLayers().values()
            if DataConnectorLogic.read_connection_info(layer)
        ]

    # -------------------------------------------------------------- metadata

    @staticmethod
    def write_connection_info(
        layer,
        source_uri: str,
        service: str,
        provider_key: str,
        source_crs: str,
        target_crs: str,
        extent: str,
        extent_crs: str,
        last_updated: str = None,
        zoom: int = None,
    ) -> bool:
        """
        Store the originating connection on the layer as a metadata link.

        The link is written into the layer's own metadata store (e.g. gpkg_metadata)
        so the connection survives outside the QGIS project file.
        """
        if layer is None:
            return False

        payload = {
            'source_uri': source_uri,
            'service': service,
            'provider_key': provider_key,
            'source_crs': source_crs,
            'target_crs': target_crs,
            'extent': extent,
            'extent_crs': extent_crs,
            'zoom': zoom,
            'last_updated': last_updated or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

        link = QgsAbstractMetadataBase.Link()
        link.name = LINK_NAME
        link.type = service or 'Streamed service'
        link.url = source_uri
        link.format = LINK_FORMAT
        link.description = json.dumps(payload)

        metadata = layer.metadata()
        links = [existing for existing in metadata.links() if existing.format != LINK_FORMAT]
        links.append(link)
        metadata.setLinks(links)
        layer.setMetadata(metadata)

        layer.setCustomProperty(CUSTOM_PROPERTY_KEY, json.dumps(payload))

        try:
            layer.saveDefaultMetadata()
        except Exception:
            # Metadata still lives on the layer/project even if the provider can't store it.
            return False
        return True

    @staticmethod
    def read_connection_info(layer) -> dict:
        """
        Read stored connection info from a layer's metadata links.

        Falls back to the session custom property. Returns {} when not a connected layer.
        """
        if layer is None:
            return {}

        try:
            for link in layer.metadata().links():
                if link.format == LINK_FORMAT:
                    return DataConnectorLogic._parse_payload(link.description, link.url)
        except Exception:
            LOGGER.debug("Could not read connected-layer metadata links", exc_info=True)

        try:
            raw = layer.customProperty(CUSTOM_PROPERTY_KEY, '')
            if raw:
                return DataConnectorLogic._parse_payload(raw, '')
        except Exception:
            LOGGER.debug("Could not read connected-layer custom properties", exc_info=True)

        return {}

    @staticmethod
    def touch_last_updated(layer) -> bool:
        """Rewrite the stored metadata with the current timestamp after a refresh."""
        info = DataConnectorLogic.read_connection_info(layer)
        if not info:
            return False

        return DataConnectorLogic.write_connection_info(
            layer,
            source_uri=info.get('source_uri', ''),
            service=info.get('service', ''),
            provider_key=info.get('provider_key', ''),
            source_crs=info.get('source_crs', ''),
            target_crs=info.get('target_crs', ''),
            extent=info.get('extent', ''),
            extent_crs=info.get('extent_crs', ''),
            zoom=info.get('zoom'),
        )

    @staticmethod
    def _parse_payload(raw, fallback_url) -> dict:
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            return {'source_uri': fallback_url} if fallback_url else {}

        if not isinstance(payload, dict) or not payload.get('source_uri'):
            return {}
        return payload

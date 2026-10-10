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
import xml.etree.ElementTree as ElementTree

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import (
    QgsBlockingNetworkRequest,
    QgsDataSourceUri,
    QgsVectorLayer,
    QgsProject,
)

SERVICE_WFS = 'wfs'
SERVICE_ARCGIS = 'arcgisfeatureserver'

REQUEST_TIMEOUT_MS = 20000


class ServiceDiscoveryError(Exception):
    """Raised when a service URL cannot be reached or understood."""


class DataConnectorSources:
    """Discovers layers published by a WFS or ArcGIS FeatureServer endpoint."""

    @staticmethod
    def detect_service(url: str) -> str:
        """Guess the service type from the URL shape."""
        lowered = (url or '').lower()
        if '/featureserver' in lowered or '/mapserver' in lowered:
            return SERVICE_ARCGIS
        return SERVICE_WFS

    @staticmethod
    def discover_layers(url: str, service: str = None) -> list:
        """
        Query the endpoint and return [{'name', 'title', 'service', 'url'}, ...].

        Raises ServiceDiscoveryError when the endpoint is unreachable or unsupported.
        """
        url = (url or '').strip()
        if not url:
            raise ServiceDiscoveryError("No URL provided.")

        service = service or DataConnectorSources.detect_service(url)

        if service == SERVICE_ARCGIS:
            return DataConnectorSources._discover_arcgis(url)
        return DataConnectorSources._discover_wfs(url)

    @staticmethod
    def build_layer(descriptor: dict, target_crs_authid: str = ''):
        """Create an (unregistered) streamed QgsVectorLayer from a discovery descriptor."""
        service = descriptor.get('service')
        uri = QgsDataSourceUri()

        if service == SERVICE_ARCGIS:
            uri.setParam('url', descriptor['url'])
            if target_crs_authid:
                uri.setParam('crs', target_crs_authid)
            provider = 'arcgisfeatureserver'
        else:
            uri.setParam('url', descriptor['url'])
            uri.setParam('typename', descriptor['name'])
            uri.setParam('version', 'auto')
            uri.setParam('pagingEnabled', 'true')
            if target_crs_authid:
                uri.setParam('srsname', target_crs_authid)
            provider = 'WFS'

        layer = QgsVectorLayer(uri.uri(False), descriptor.get('title') or descriptor['name'], provider)
        if not layer.isValid():
            raise ServiceDiscoveryError(
                f"Could not open '{descriptor.get('title') or descriptor['name']}' from the service."
            )
        return layer

    # ------------------------------------------------------------- internals

    @staticmethod
    def _fetch(url: str) -> bytes:
        """GET a URL through the QGIS network stack so proxy/auth settings apply."""
        request = QNetworkRequest(QUrl(url))
        blocking = QgsBlockingNetworkRequest()
        blocking.setTimeout(REQUEST_TIMEOUT_MS)

        error = blocking.get(request)
        if error != QgsBlockingNetworkRequest.NoError:
            raise ServiceDiscoveryError(blocking.errorMessage() or "Request failed.")

        reply = blocking.reply()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status and int(status) >= 400:
            raise ServiceDiscoveryError(f"Server returned HTTP {status}.")

        return bytes(reply.content())

    @staticmethod
    def _append_query(url: str, query: str) -> str:
        separator = '&' if '?' in url else '?'
        return f"{url}{separator}{query}"

    @staticmethod
    def _discover_wfs(url: str) -> list:
        """Read GetCapabilities and return the advertised feature types."""
        base_url = url.split('?')[0]
        capabilities_url = DataConnectorSources._append_query(
            url, 'service=WFS&request=GetCapabilities'
        )

        content = DataConnectorSources._fetch(capabilities_url)

        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as exc:
            raise ServiceDiscoveryError(f"Response was not valid WFS XML: {exc}")

        # Namespaces vary between WFS versions, so match on the local tag name.
        layers = []
        for element in root.iter():
            if not element.tag.endswith('FeatureType'):
                continue

            name = DataConnectorSources._child_text(element, 'Name')
            if not name:
                continue
            title = DataConnectorSources._child_text(element, 'Title') or name
            layers.append({
                'name': name,
                'title': title,
                'service': SERVICE_WFS,
                'url': base_url,
            })

        if not layers:
            raise ServiceDiscoveryError("No feature types advertised by this WFS endpoint.")
        return layers

    @staticmethod
    def _child_text(element, local_name: str) -> str:
        for child in element:
            if child.tag.endswith(local_name) and child.text:
                return child.text.strip()
        return ''

    @staticmethod
    def _discover_arcgis(url: str) -> list:
        """Read the ArcGIS service JSON and return its queryable layers."""
        base_url = url.split('?')[0].rstrip('/')
        content = DataConnectorSources._fetch(
            DataConnectorSources._append_query(base_url, 'f=json')
        )

        try:
            payload = json.loads(content.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ServiceDiscoveryError(f"Response was not valid ArcGIS JSON: {exc}")

        if 'error' in payload:
            message = payload['error'].get('message', 'Unknown service error')
            raise ServiceDiscoveryError(f"Service error: {message}")

        # A URL ending in a layer id points at a single layer rather than a service.
        if 'layers' not in payload and payload.get('name'):
            return [{
                'name': str(payload.get('id', '')),
                'title': payload['name'],
                'service': SERVICE_ARCGIS,
                'url': base_url,
            }]

        layers = []
        for entry in payload.get('layers', []):
            if entry.get('subLayerIds'):
                continue  # group layers cannot be queried directly
            layer_id = entry.get('id')
            layers.append({
                'name': str(layer_id),
                'title': entry.get('name', f"Layer {layer_id}"),
                'service': SERVICE_ARCGIS,
                'url': f"{base_url}/{layer_id}",
            })

        if not layers:
            raise ServiceDiscoveryError("No queryable layers found at this endpoint.")
        return layers

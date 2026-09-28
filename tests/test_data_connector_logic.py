import json

import pytest

from qgis.core import (
    QgsAbstractMetadataBase,
    QgsCoordinateReferenceSystem,
)

from CeeThreeDeeQTools.Tools.DataConnector.ctdq_DataConnectorLogic import (
    CUSTOM_PROPERTY_KEY,
    LINK_FORMAT,
    DataConnectorLogic,
)
from CeeThreeDeeQTools.Tools.DataConnector.ctdq_DataConnectorRasterExtract import (
    RASTER_FORMAT_GPKG,
    RASTER_FORMAT_GTIFF,
)
from CeeThreeDeeQTools.Tools.DataConnector.ctdq_DataConnectorRasterRefresh import (
    DataConnectorRasterRefresh,
)


class MetadataDouble:
    def __init__(self, links):
        self._links = links

    def links(self):
        return self._links

    def setLinks(self, links):
        self._links = links


class LayerDouble:
    def __init__(self, metadata):
        self._metadata = metadata
        self._properties = {}

    def metadata(self):
        return self._metadata

    def setMetadata(self, metadata):
        self._metadata = metadata

    def setCustomProperty(self, key, value):
        self._properties[key] = value

    def customProperty(self, key, default=""):
        return self._properties.get(key, default)

    def saveDefaultMetadata(self):
        return True


def test_service_name_for_provider_handles_aliases_and_unknown_providers():
    assert DataConnectorLogic.service_name_for_provider("WFS") == "WFS"
    assert (
        DataConnectorLogic.service_name_for_provider("afs")
        == "REST (FeatureServer)"
    )
    assert DataConnectorLogic.service_name_for_provider("wms") == "WMS"
    assert DataConnectorLogic.service_name_for_provider("ogr") == ""
    assert DataConnectorLogic.service_name_for_provider(None) == ""


@pytest.mark.parametrize(
    ("raw", "fallback_url", "expected"),
    [
        ('{"source_uri":"https://example.test/wfs"}', "", {
            "source_uri": "https://example.test/wfs"
        }),
        ("not-json", "https://example.test/wfs", {
            "source_uri": "https://example.test/wfs"
        }),
        ('["not", "an object"]', "https://example.test/wfs", {}),
        ('{"service":"WFS"}', "https://example.test/wfs", {}),
    ],
)
def test_parse_payload_validates_connection_metadata(raw, fallback_url, expected):
    assert DataConnectorLogic._parse_payload(raw, fallback_url) == expected


def test_write_and_read_connection_info_preserves_other_metadata_links():
    unrelated_link = QgsAbstractMetadataBase.Link()
    unrelated_link.name = "Documentation"
    unrelated_link.url = "https://example.test/docs"
    unrelated_link.format = "text/html"
    layer = LayerDouble(MetadataDouble([unrelated_link]))

    expected = {
        "source_uri": "https://example.test/wfs",
        "service": "WFS",
        "provider_key": "wfs",
        "source_crs": "EPSG:4326",
        "target_crs": "EPSG:26910",
        "extent": "1,2,3,4",
        "extent_crs": "EPSG:4326",
        "zoom": 12,
        "last_updated": "2026-09-28 10:30:00",
    }

    assert DataConnectorLogic.write_connection_info(
        layer,
        source_uri=expected["source_uri"],
        service=expected["service"],
        provider_key=expected["provider_key"],
        source_crs=expected["source_crs"],
        target_crs=expected["target_crs"],
        extent=expected["extent"],
        extent_crs=expected["extent_crs"],
        last_updated=expected["last_updated"],
        zoom=expected["zoom"],
    )

    assert DataConnectorLogic.read_connection_info(layer) == expected
    assert json.loads(layer.customProperty(CUSTOM_PROPERTY_KEY)) == expected

    links = layer.metadata().links()
    assert sum(link.format == LINK_FORMAT for link in links) == 1
    assert any(link.format == "text/html" for link in links)


def test_raster_refresh_resolves_stored_extent_and_crs():
    extent, crs = DataConnectorRasterRefresh._resolve_extent(
        {"extent": "1,2,3,4", "extent_crs": "EPSG:4326"}, None, None
    )

    bounds = extent.boundingBox()
    assert (bounds.xMinimum(), bounds.yMinimum()) == (1.0, 2.0)
    assert (bounds.xMaximum(), bounds.yMaximum()) == (3.0, 4.0)
    assert crs == QgsCoordinateReferenceSystem("EPSG:4326")


@pytest.mark.parametrize(
    ("info", "message"),
    [
        ({"extent": "1,2,3"}, "stored extent is missing or invalid."),
        ({"extent": "1,2,nope,4"}, "stored extent could not be read."),
    ],
)
def test_raster_refresh_rejects_invalid_stored_extents(info, message):
    with pytest.raises(ValueError, match=message):
        DataConnectorRasterRefresh._resolve_extent(info, None, None)


def test_raster_refresh_describes_windows_geopackage_source():
    layer = type(
        "Layer", (), {"source": lambda self: "GPKG:C:/data/tiles.gpkg:basemap"}
    )()

    assert DataConnectorRasterRefresh._describe_output(layer) == (
        "C:/data/tiles.gpkg",
        "basemap",
        RASTER_FORMAT_GPKG,
    )


@pytest.mark.parametrize(
    ("source", "expected_format"),
    [
        ("C:/data/tiles.gpkg|layername=basemap", RASTER_FORMAT_GPKG),
        ("C:/data/tiles.tif", RASTER_FORMAT_GTIFF),
    ],
)
def test_raster_refresh_describes_file_source(source, expected_format):
    layer = type("Layer", (), {"source": lambda self: source})()

    path, table_name, output_format = DataConnectorRasterRefresh._describe_output(layer)

    assert path == source.split("|")[0]
    assert table_name == "tiles"
    assert output_format == expected_format
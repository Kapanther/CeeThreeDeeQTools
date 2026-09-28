import numpy as np

from qgis.core import (
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsMarkerSymbol,
    QgsProject,
    QgsRendererCategory,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.PyQt.QtWidgets import QTreeWidget, QTreeWidgetItem
from qgis.PyQt.QtCore import Qt, QVariant
import pytest

from processing.core.Processing import Processing

from CeeThreeDeeQTools.Processing.ctdq_AlgoSymbology import (
    PostRasterSymbology,
    PostVectorSymbology,
)
from CeeThreeDeeQTools.Functions.ctdq_raster_functions import CtdqRasterFunctions
from CeeThreeDeeQTools.Tools.DataConnector.ctdq_DataConnectorSources import (
    DataConnectorSources,
    SERVICE_ARCGIS,
    SERVICE_WFS,
    ServiceDiscoveryError,
)
from CeeThreeDeeQTools.Tools.DataConnector.ctdq_DataConnectorStyle import (
    DataConnectorStyle,
)
from CeeThreeDeeQTools.Tools.DataConnector.ctdq_RasterTileMath import (
    RasterTileMath,
    TILE_SIZE,
)
from CeeThreeDeeQTools.Tools.LayersAdvanced.services.layer_operations_service import (
    LayerOperationsService,
)
from CeeThreeDeeQTools.Tools.LayersAdvanced.services.layer_service import LayerService
from CeeThreeDeeQTools.Tools.LayersAdvanced.services.visibility_service import (
    VisibilityService,
)
from CeeThreeDeeQTools.Tools.LayersAdvanced.ui.filter_widget import FilterService


_QGIS_APP = None


def _ensure_qgis_application():
    global _QGIS_APP
    _QGIS_APP = QgsApplication.instance()
    if _QGIS_APP is None:
        _QGIS_APP = QgsApplication([], False)
        _QGIS_APP.initQgis()
    Processing.initialize()


def _make_layer(name="features"):
    layer = QgsVectorLayer("Point?crs=EPSG:3857", name, "memory")
    layer.dataProvider().addAttributes([
        QgsField("kind", QVariant.String),
        QgsField("value", QVariant.Double),
    ])
    layer.updateFields()
    return layer


def _add_feature(layer, kind, value, x=0, y=0):
    feature = QgsFeature(layer.fields())
    feature.setGeometry(QgsGeometry.fromWkt(f"POINT ({x} {y})"))
    feature.setAttributes([kind, value])
    layer.dataProvider().addFeature(feature)
    layer.updateExtents()


def test_post_symbology_builders_create_expected_renderers_and_labels():
    _ensure_qgis_application()
    vector = PostVectorSymbology().set_simple_outline().set_labeling(
        '"kind" || \' label\'', buffer_enabled=False
    )
    assert vector.get_renderer().type() == "singleSymbol"
    assert vector.labeling.settings().fieldName == '"kind" || \' label\''
    assert vector.labeling.settings().isExpression

    categorized = PostVectorSymbology().set_categorized_renderer("kind")
    assert categorized.get_renderer().classAttribute() == "kind"
    assert categorized.get_renderer().categories() == []

    raster = PostRasterSymbology().set_color_ramp("Viridis", 1, 9).set_classification(
        "equalInterval"
    )
    assert (raster.color_ramp_name, raster.min_value, raster.max_value) == (
        "Viridis",
        1,
        9,
    )
    assert raster.classification_method == "equalInterval"


def test_raster_tile_math_round_trips_and_estimates_tiles():
    _ensure_qgis_application()
    assert RasterTileMath.resolution_for_zoom(0) > RasterTileMath.resolution_for_zoom(1)
    assert RasterTileMath.zoom_for_resolution(0) == 24
    assert RasterTileMath.zoom_for_resolution(10**20) == 0
    assert RasterTileMath.zoom_for_scale(0) == 24
    assert RasterTileMath.scale_for_zoom(2) > RasterTileMath.scale_for_zoom(3)

    estimate = RasterTileMath.estimate(
        QgsRectangle(0, 0, 1000, 1000),
        QgsCoordinateReferenceSystem("EPSG:3857"),
        10,
    )
    assert estimate["width"] > 0
    assert estimate["height"] > 0
    assert estimate["tiles"] >= 1
    assert estimate["tiles"] == (
        -(-estimate["width"] // TILE_SIZE) * -(-estimate["height"] // TILE_SIZE)
    )


def test_service_discovery_parses_wfs_and_arcgis_payloads(monkeypatch):
    wfs_xml = b"""
    <wfs:WFS_Capabilities xmlns:wfs='urn:wfs' xmlns:ows='urn:ows'>
      <wfs:FeatureType><wfs:Name>roads</wfs:Name><wfs:Title>Roads</wfs:Title></wfs:FeatureType>
    </wfs:WFS_Capabilities>
    """
    monkeypatch.setattr(DataConnectorSources, "_fetch", lambda url: wfs_xml)
    assert DataConnectorSources.detect_service("https://example.test/mapserver") == SERVICE_ARCGIS
    assert DataConnectorSources.discover_layers("https://example.test/wfs") == [{
        "name": "roads",
        "title": "Roads",
        "service": SERVICE_WFS,
        "url": "https://example.test/wfs",
    }]

    monkeypatch.setattr(
        DataConnectorSources,
        "_fetch",
        lambda url: b'{"layers":[{"id":1,"name":"Roads"},{"id":2,"name":"Group","subLayerIds":[3]}]}',
    )
    assert DataConnectorSources.discover_layers(
        "https://example.test/MapServer", SERVICE_ARCGIS
    )[0]["url"] == "https://example.test/MapServer/1"

    with pytest.raises(ServiceDiscoveryError, match="No URL"):
        DataConnectorSources.discover_layers("")


def test_data_connector_style_prunes_unused_categories_but_keeps_catch_all():
    _ensure_qgis_application()
    layer = _make_layer()
    _add_feature(layer, "used", 1)
    symbol = QgsMarkerSymbol.createSimple({"color": "red"})
    renderer = QgsCategorizedSymbolRenderer(
        "kind",
        [
            QgsRendererCategory("used", symbol.clone(), "Used"),
            QgsRendererCategory("unused", symbol.clone(), "Unused"),
            QgsRendererCategory(None, symbol.clone(), "Other"),
        ],
    )
    layer.setRenderer(renderer)

    assert DataConnectorStyle.prune_unused_classes(layer) == 1
    values = [category.value() for category in layer.renderer().categories()]
    assert values == ["used", None]


def test_layers_advanced_services_report_and_change_tree_state():
    _ensure_qgis_application()
    project = QgsProject.instance()
    project.clear()
    first = _make_layer("first")
    second = _make_layer("second")
    project.addMapLayer(first)
    project.addMapLayer(second)
    try:
        assert LayerService.get_all_layers(project) == [first, second]
        assert LayerService.get_layer_type_string(first) == "Vector (Point)"
        assert LayerService.get_layer_info(first) == "0 features"

        assert VisibilityService.is_layer_visible(first)
        VisibilityService.set_layer_visibility(first.id(), False)
        assert not VisibilityService.is_layer_visible(first)
        VisibilityService.set_layer_visibility(first.id(), True)

        assert LayerOperationsService.move_layer_up(first.id())
        assert [node.layer().name() for node in project.layerTreeRoot().children()] == [
            "first",
            "second",
        ]
        assert LayerOperationsService.move_layer_down(first.id())
    finally:
        project.clear()


def test_filter_service_hides_nonmatching_layers_and_restores_all():
    _ensure_qgis_application()
    tree = QTreeWidget()
    group = QTreeWidgetItem(tree, ["Roads"])
    road = QTreeWidgetItem(group, ["Main road"])
    road.setData(0, Qt.ItemDataRole.UserRole + 1, "layer")
    water = QTreeWidgetItem(group, ["River"])
    water.setData(0, Qt.ItemDataRole.UserRole + 1, "layer")

    assert FilterService.filter_tree(tree, "road") == (2, 1)
    assert not road.isHidden()
    assert water.isHidden()
    assert FilterService.filter_tree(tree, "") == (2, 0)
    assert not water.isHidden()


def test_raster_functions_fill_mask_and_copy_synthetic_dem(tmp_path):
    _ensure_qgis_application()
    feedback = __import__("qgis").core.QgsProcessingFeedback()
    source_array = np.array(
        [[5.0, 5.0, 5.0], [5.0, 1.0, 5.0], [5.0, 5.0, 5.0]],
        dtype=np.float32,
    )
    extent = QgsRectangle(0, 0, 3, 3)
    crs = QgsCoordinateReferenceSystem("EPSG:3857")
    source_path = CtdqRasterFunctions.ctdq_raster_fromNumpy(
        source_array, 3, 3, extent, crs, feedback
    )
    source = __import__("qgis").core.QgsRasterLayer(source_path, "dem", "gdal")
    assert source.isValid()
    assert np.array_equal(CtdqRasterFunctions.ctdq_raster_asnumpy(source, feedback), source_array)

    filled = CtdqRasterFunctions.ctdq_raster_fillsinks(source, feedback)
    assert filled[1, 1] == 5.0

    mask_path = CtdqRasterFunctions.ctdq_raster_create_depression_mask(
        source, filled, feedback
    )
    mask = __import__("qgis").core.QgsRasterLayer(mask_path, "mask", "gdal")
    assert mask.isValid()
    assert CtdqRasterFunctions.ctdq_raster_asnumpy(mask, feedback)[1, 1] == 1.0

    copied_path = tmp_path / "copied.tif"
    assert CtdqRasterFunctions.ctdq_raster_copy(source_path, str(copied_path), feedback)
    assert __import__("qgis").core.QgsRasterLayer(
        str(copied_path), "copy", "gdal"
    ).isValid()

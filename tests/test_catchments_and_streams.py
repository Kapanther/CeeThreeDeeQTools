from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsProcessingFeedback,
    QgsVectorLayer,
)
from processing.core.Processing import Processing

from CeeThreeDeeQTools.Processing.ctdq_CatchmentsAndStreams import (
    CatchmentsAndStreams,
)

_QGIS_APP = None


def _branched_stream_layer():
    layer = QgsVectorLayer("LineString?crs=EPSG:3857", "streams", "memory")
    provider = layer.dataProvider()
    features = []
    for wkt in (
        "LINESTRING (0 0, 5 5)",
        "LINESTRING (0 10, 5 5)",
        "LINESTRING (5 5, 10 5)",
    ):
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()
    return layer


def test_catchments_and_streams_registers_expected_parameters():
    algorithm = CatchmentsAndStreams()
    algorithm.initAlgorithm()

    assert {
        parameter.name() for parameter in algorithm.parameterDefinitions()
    } == {
        "INPUT_DEM",
        "INPUT_THRESHOLD",
        "INPUT_WATERSHED_THRESHOLD",
        "IGNORE_DEPRESSIONS",
        "ignoreSmallDepressions",
        "BREACH_MAX_LENGTH",
        "DEPRESSION_MIN_DEPTH",
        "SMOOTH_ITERATIONS",
        "SMOOTH_OFFSET",
        "OUTPUT_CATCHMENTS",
        "OUTPUT_STREAMS",
        "OUTPUT_NETWORKS",
        "OUTPUT_DEPRESSION_RASTER",
    }

    assert algorithm.parameterDefinition("INPUT_THRESHOLD").defaultValue() == 4000
    assert algorithm.parameterDefinition("INPUT_WATERSHED_THRESHOLD").defaultValue() == 10000
    assert algorithm.parameterDefinition("IGNORE_DEPRESSIONS").defaultValue()
    assert algorithm.parameterDefinition("SMOOTH_ITERATIONS").defaultValue() == 3


def test_catchments_and_streams_reads_single_and_multipart_endpoints():
    algorithm = CatchmentsAndStreams()
    single = QgsGeometry.fromWkt("LINESTRING (1 2, 3 4)")
    multi = QgsGeometry.fromWkt(
        "MULTILINESTRING ((1 2, 3 4), (5 6, 7 8))"
    )

    assert algorithm.get_start_point(single) == single.asPolyline()[0]
    assert algorithm.get_end_point(single) == single.asPolyline()[-1]
    assert algorithm.get_start_point(multi) == multi.asMultiPolyline()[0][0]
    assert algorithm.get_end_point(multi) == multi.asMultiPolyline()[-1][-1]
    assert algorithm.get_start_point(QgsGeometry.fromWkt("POINT (1 2)")) is None


def test_catchments_and_streams_calculates_branched_stream_orders():
    global _QGIS_APP
    _QGIS_APP = QgsApplication.instance()
    if _QGIS_APP is None:
        _QGIS_APP = QgsApplication([], False)
        _QGIS_APP.initQgis()
    Processing.initialize()
    algorithm = CatchmentsAndStreams()
    streams = _branched_stream_layer()

    ordered = algorithm.calculate_stream_orders(
        streams, None, QgsProcessingFeedback()
    )

    assert ordered.fields().indexFromName("Strahler") >= 0
    assert ordered.fields().indexFromName("Shreve") >= 0

    orders_by_start = {
        (
            round(feature.geometry().asPolyline()[0].x()),
            round(feature.geometry().asPolyline()[0].y()),
        ): (feature["Strahler"], feature["Shreve"])
        for feature in ordered.getFeatures()
    }
    assert orders_by_start[(0, 0)] == (1, 1)
    assert orders_by_start[(0, 10)] == (1, 1)
    assert orders_by_start[(5, 5)] == (2, 2)
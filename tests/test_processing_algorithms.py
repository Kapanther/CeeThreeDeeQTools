from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant
from osgeo import gdal, osr

from processing.core.Processing import Processing

from CeeThreeDeeQTools.Processing.ctdq_PointsAlongPaths import PointsAlongPaths
from CeeThreeDeeQTools.Processing.ctdq_StageStorage import CalculateStageStoragePond


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "test_raster.tif"
_QGIS_APP = None


def _ensure_qgis_application():
    global _QGIS_APP
    _QGIS_APP = QgsApplication.instance()
    if _QGIS_APP is None:
        _QGIS_APP = QgsApplication([], False)
        _QGIS_APP.initQgis()
    Processing.initialize()


def _copy_raster_with_crs(source_path, destination_path):
    gdal.Translate(str(destination_path), str(source_path))
    dataset = gdal.Open(str(destination_path), gdal.GA_Update)
    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromEPSG(3857)
    dataset.SetProjection(spatial_ref.ExportToWkt())
    dataset = None


def test_points_along_paths_generates_interval_and_offset_points():
    algorithm = PointsAlongPaths()
    line = QgsGeometry.fromWkt("LINESTRING (0 0, 10 0)")

    points = algorithm._generate_points_along_line(
        line,
        keep_vertices=False,
        interval=5.0,
        offset=2.0,
        start_modifier=100.0,
    )

    assert [point_data["distance"] for point_data in points] == [100.0, 105.0, 110.0]
    assert [(point_data["point"].x(), point_data["point"].y()) for point_data in points] == [
        (0.0, 2.0),
        (5.0, 2.0),
        (10.0, 2.0),
    ]


def test_points_along_paths_writes_points_and_copies_attributes(tmp_path):
    _ensure_qgis_application()
    source = QgsVectorLayer("LineString?crs=EPSG:3857", "lines", "memory")
    source.dataProvider().addAttributes([QgsField("route", QVariant.String)])
    source.updateFields()
    feature = QgsFeature(source.fields())
    feature.setGeometry(QgsGeometry.fromWkt("LINESTRING (0 0, 10 0)"))
    feature.setAttribute("route", "A")
    source.dataProvider().addFeature(feature)
    source.updateExtents()

    algorithm = PointsAlongPaths()
    algorithm.initAlgorithm()
    context = QgsProcessingContext()
    context.setProject(QgsProject.instance())
    output_path = tmp_path / "points.gpkg"

    result = algorithm.processAlgorithm(
        {
            "INPUT_LINES": source,
            "KEEP_EXISTING_VERTICES": False,
            "INTERVAL_DISTANCE": 5.0,
            "INTERVAL_DISTANCE_FIELD": "",
            "OFFSET_DISTANCE": 0.0,
            "OFFSET_DISTANCE_FIELD": "",
            "START_DISTANCE_MODIFIER": 10.0,
            "START_DISTANCE_MODIFIER_FIELD": "",
            "OUTPUT_POINTS": str(output_path),
        },
        context,
        QgsProcessingFeedback(),
    )

    output = QgsVectorLayer(result[algorithm.OUTPUT_POINTS], "points", "ogr")
    assert output.isValid()
    assert output.featureCount() == 3
    assert "distance" in output.fields().names()
    assert [feature["distance"] for feature in output.getFeatures()] == [10.0, 15.0, 20.0]
    assert {feature["route"] for feature in output.getFeatures()} == {"A"}


def test_stage_storage_registers_expected_parameters():
    algorithm = CalculateStageStoragePond()
    algorithm.initAlgorithm()

    assert {
        parameter.name() for parameter in algorithm.parameterDefinitions()
    } == {
        "INPUT_RASTER",
        "INPUT_PONDS_VECTOR",
        "INPUT_PONDS_RL_FIELD",
        "POND_ID_FIELD",
        "STORAGE_INTERVAL",
        "OUTPUT_HTML_REPORT",
        "OUTPUT_STAGE_STORAGE",
    }
    assert algorithm.parameterDefinition("STORAGE_INTERVAL").defaultValue() == 1


def test_stage_storage_writes_stage_slices_for_fixture_raster(tmp_path):
    _ensure_qgis_application()
    raster_path = tmp_path / "ground_epsg3857.tif"
    _copy_raster_with_crs(FIXTURE_PATH, raster_path)
    raster = QgsRasterLayer(str(raster_path), "ground", "gdal")
    assert raster.isValid()

    ponds = QgsVectorLayer("Polygon?crs=EPSG:3857", "ponds", "memory")
    ponds.dataProvider().addAttributes([
        QgsField("PONDid", QVariant.String),
        QgsField("PONDRLmax", QVariant.Double),
    ])
    ponds.updateFields()
    pond = QgsFeature(ponds.fields())
    pond.setGeometry(QgsGeometry.fromRect(raster.extent()))
    pond.setAttributes(["P1", 144.46000671387])
    ponds.dataProvider().addFeature(pond)
    ponds.updateExtents()

    algorithm = CalculateStageStoragePond()
    algorithm.initAlgorithm()
    context = QgsProcessingContext()
    context.setProject(QgsProject.instance())
    output_path = tmp_path / "stage_storage.gpkg"
    report_path = tmp_path / "stage_storage.html"

    result = algorithm.processAlgorithm(
        {
            "INPUT_RASTER": raster,
            "INPUT_PONDS_VECTOR": ponds,
            "INPUT_PONDS_RL_FIELD": "PONDRLmax",
            "POND_ID_FIELD": "PONDid",
            "STORAGE_INTERVAL": 5.0,
            "OUTPUT_HTML_REPORT": str(report_path),
            "OUTPUT_STAGE_STORAGE": str(output_path),
        },
        context,
        QgsProcessingFeedback(),
    )

    assert result[algorithm.OUTPUT_STAGE_STORAGE] == str(output_path)
    assert output_path.exists()
    assert report_path.exists()

    output = QgsVectorLayer(str(output_path), "stage storage", "ogr")
    assert output.isValid()
    assert output.featureCount() > 0
    assert {
        "PONDid",
        "PONDRLmax",
        "ssMIN",
        "ssMAX",
        "ssAREA",
        "ssINCVOL",
        "ssCUMVOL",
        "ssMINDPTH",
        "ssMAXDPTH",
    }.issubset(set(output.fields().names()))
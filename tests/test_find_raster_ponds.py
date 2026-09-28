from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)

from processing.core.Processing import Processing

from CeeThreeDeeQTools.Processing.ctdq_FindRasterPonds import FindRasterPonds


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "test_raster.tif"
_QGIS_APP = None


def test_find_raster_ponds_registers_expected_parameters():
    algorithm = FindRasterPonds()
    algorithm.initAlgorithm()

    assert {
        parameter.name() for parameter in algorithm.parameterDefinitions()
    } == {
        "GROUND_RASTER",
        "MIN_DEPTH",
        "MIN_AREA",
        "OUTPUT_POND_OUTLINES",
        "GENERALIZE_OUTLINES",
        "OUTPUT_FILLED_RASTER",
        "OUTPUT_POND_DEPTH_RASTER",
        "OUTPUT_POND_DEPTH_RASTER_VALID",
    }

    assert algorithm.parameterDefinition("MIN_DEPTH").defaultValue() == 0.2
    assert algorithm.parameterDefinition("MIN_AREA").defaultValue() == 2000.0
    assert algorithm.parameterDefinition("GENERALIZE_OUTLINES").defaultValue()


def test_find_raster_ponds_writes_outputs_when_fixture_has_no_qualifying_ponds(tmp_path):
    global _QGIS_APP
    _QGIS_APP = QgsApplication.instance()
    if _QGIS_APP is None:
        _QGIS_APP = QgsApplication([], False)
        _QGIS_APP.initQgis()
    Processing.initialize()

    input_raster = QgsRasterLayer(str(FIXTURE_PATH), "test_raster", "gdal")
    assert input_raster.isValid()

    algorithm = FindRasterPonds()
    algorithm.initAlgorithm()
    context = QgsProcessingContext()
    context.setProject(QgsProject.instance())
    output_ponds = tmp_path / "ponds.gpkg"

    result = algorithm.processAlgorithm(
        {
            "GROUND_RASTER": input_raster,
            "MIN_DEPTH": 0.2,
            "MIN_AREA": 2000.0,
            "GENERALIZE_OUTLINES": False,
            "OUTPUT_POND_OUTLINES": str(output_ponds),
            "OUTPUT_FILLED_RASTER": str(tmp_path / "filled.tif"),
            "OUTPUT_POND_DEPTH_RASTER": str(tmp_path / "depth.tif"),
            "OUTPUT_POND_DEPTH_RASTER_VALID": str(tmp_path / "valid.tif"),
        },
        context,
        QgsProcessingFeedback(),
    )

    assert set(result) == {
        "OUTPUT_FILLED_RASTER",
        "OUTPUT_POND_DEPTH_RASTER",
        "OUTPUT_POND_DEPTH_RASTER_VALID",
        "OUTPUT_POND_OUTLINES",
    }
    assert result["OUTPUT_POND_OUTLINES"] == str(output_ponds)
    assert output_ponds.exists()

    for key in (
        "OUTPUT_FILLED_RASTER",
        "OUTPUT_POND_DEPTH_RASTER",
        "OUTPUT_POND_DEPTH_RASTER_VALID",
    ):
        raster = QgsRasterLayer(result[key], key, "gdal")
        assert raster.isValid()
        assert raster.width() == input_raster.width()
        assert raster.height() == input_raster.height()

    pond_layer = QgsVectorLayer(str(output_ponds), "ponds", "ogr")
    assert pond_layer.isValid()
    assert pond_layer.featureCount() == 0
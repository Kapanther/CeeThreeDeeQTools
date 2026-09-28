import xml.etree.ElementTree as ET
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

from processing.core.Processing import Processing

import CeeThreeDeeQTools.Processing.ctdq_ExportDataSourcesMap as export_map_module
from CeeThreeDeeQTools.Processing.ctdq_ExportDataSourcesMap import ExportDataSourcesMap
from CeeThreeDeeQTools.Processing.ctdq_ExportProjectLayerStyles import (
    ExportProjectLayerStyles,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "test_raster.tif"
_QGIS_APP = None


class _HeadlessInterface:
    def mapCanvas(self):
        return None


def _ensure_qgis_application():
    global _QGIS_APP
    _QGIS_APP = QgsApplication.instance()
    if _QGIS_APP is None:
        _QGIS_APP = QgsApplication([], False)
        _QGIS_APP.initQgis()
    Processing.initialize()


def _make_point_layer():
    layer = QgsVectorLayer("Point?crs=EPSG:3857", "survey_points", "memory")
    layer.dataProvider().addAttributes([QgsField("code", QVariant.String)])
    layer.updateFields()

    feature = QgsFeature(layer.fields())
    feature.setGeometry(QgsGeometry.fromWkt("POINT (10 20)"))
    feature.setAttribute("code", "P1")
    layer.dataProvider().addFeature(feature)
    layer.updateExtents()
    return layer


def test_export_data_sources_map_registers_output_parameter():
    algorithm = ExportDataSourcesMap()
    algorithm.initAlgorithm()

    assert [parameter.name() for parameter in algorithm.parameterDefinitions()] == [
        algorithm.OUTPUT
    ]
    assert algorithm.parameterDefinition(algorithm.OUTPUT).typeName() == "vectorDestination"


def test_export_data_sources_map_writes_vector_and_raster_metadata(tmp_path, monkeypatch):
    _ensure_qgis_application()
    monkeypatch.setattr(export_map_module, "iface", _HeadlessInterface())

    project = QgsProject.instance()
    project.clear()
    project.setCrs(_make_point_layer().crs())
    point_layer = _make_point_layer()
    raster_layer = QgsRasterLayer(str(FIXTURE_PATH), "elevation", "gdal")
    assert raster_layer.isValid()
    project.addMapLayer(point_layer)
    project.addMapLayer(raster_layer)

    try:
        algorithm = ExportDataSourcesMap()
        algorithm.initAlgorithm()
        context = QgsProcessingContext()
        context.setProject(project)
        output_path = tmp_path / "data_sources.gpkg"

        result = algorithm.processAlgorithm(
            {algorithm.OUTPUT: str(output_path)},
            context,
            QgsProcessingFeedback(),
        )

        assert result[algorithm.OUTPUT] == str(output_path)
        output = QgsVectorLayer(str(output_path), "data sources", "ogr")
        assert output.isValid()
        assert output.featureCount() == 2
        records = {
            feature["layer_name"]: feature for feature in output.getFeatures()
        }
        assert records["survey_points"]["geom_type"] == "Point"
        assert records["survey_points"]["feature_count"] == 1
        assert records["elevation"]["geom_type"] == "Raster"
        assert records["elevation"]["feature_count"] == 0
        raster_bounds = records["elevation"].geometry().boundingBox()
        source_bounds = raster_layer.extent()
        assert raster_bounds.xMinimum() == source_bounds.xMinimum()
        assert raster_bounds.yMinimum() == source_bounds.yMinimum()
        assert raster_bounds.xMaximum() == source_bounds.xMaximum()
        assert raster_bounds.yMaximum() == source_bounds.yMaximum()
    finally:
        project.clear()


def test_export_project_layer_styles_writes_by_layer_xml_and_qml(tmp_path):
    _ensure_qgis_application()
    project = QgsProject.instance()
    project.clear()
    layer = _make_point_layer()
    project.addMapLayer(layer)

    try:
        algorithm = ExportProjectLayerStyles()
        algorithm.initAlgorithm()
        context = QgsProcessingContext()
        context.setProject(project)
        output_path = tmp_path / "styles.xml"
        qml_dir = tmp_path / "qml"

        result = algorithm.processAlgorithm(
            {
                algorithm.EXPORT_MODE: 1,
                algorithm.OUTPUT: str(output_path),
                algorithm.QML_OUTPUT_DIR: str(qml_dir),
            },
            context,
            QgsProcessingFeedback(),
        )

        assert result[algorithm.OUTPUT] == str(output_path)
        assert output_path.exists()
        assert (qml_dir / "survey_points.qml").exists()

        root = ET.parse(output_path).getroot()
        layer_element = root.find("Layer")
        assert layer_element is not None
        assert layer_element.attrib["name"] == "survey_points"
        assert layer_element.find("vectorStyle").attrib["geometryType"] == "Point"
        assert layer_element.find("vectorStyle/labels/NoLabels") is not None
    finally:
        project.clear()

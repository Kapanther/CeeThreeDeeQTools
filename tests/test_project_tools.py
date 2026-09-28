from datetime import datetime

from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from processing.core.Processing import Processing

from CeeThreeDeeQTools.Tools.MirrorProject.ctdq_MirrorProjectLogic import (
    MirrorProjectLogic,
)
from CeeThreeDeeQTools.Tools.PackageLayerUpdater.ctdq_PackageLayerUpdaterLogic import (
    PackageLayerUpdaterLogic,
)
from CeeThreeDeeQTools.Tools.ValidateProjectReport.ctdq_ValidateProjectReportDialog import (
    ValidateProjectReportDialog,
)


_QGIS_APP = None


def _ensure_qgis_application():
    global _QGIS_APP
    _QGIS_APP = QgsApplication.instance()
    if _QGIS_APP is None:
        _QGIS_APP = QgsApplication([], False)
        _QGIS_APP.initQgis()
    Processing.initialize()


def _make_layer(name="roads", include_fid=False):
    fields = []
    if include_fid:
        fields.append(QgsField("FID", QVariant.Int))
    fields.append(QgsField("label", QVariant.String))
    layer = QgsVectorLayer("Point?crs=EPSG:3857", name, "memory")
    layer.dataProvider().addAttributes(fields)
    layer.updateFields()
    return layer


def _add_feature(layer, point, label, fid=None):
    feature = QgsFeature(layer.fields())
    feature.setGeometry(QgsGeometry.fromWkt(f"POINT ({point[0]} {point[1]})"))
    if fid is not None:
        feature.setAttribute("FID", fid)
    feature.setAttribute("label", label)
    layer.dataProvider().addFeature(feature)
    layer.updateExtents()


def test_mirror_project_clones_layer_into_target_project(tmp_path):
    _ensure_qgis_application()
    source_memory = _make_layer()
    _add_feature(source_memory, (1, 2), "A")
    source_path = tmp_path / "source.gpkg"
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = "roads"
    error = QgsVectorFileWriter.writeAsVectorFormatV3(
        source_memory,
        str(source_path),
        QgsProject.instance().transformContext(),
        options,
    )
    assert error[0] == QgsVectorFileWriter.NoError
    source = QgsVectorLayer(f"{source_path}|layername=roads", "roads", "ogr")
    assert source.isValid()
    target = QgsProject()
    results = {"errors": [], "warnings": []}

    assert MirrorProjectLogic._clone_layer_to_project(
        source,
        target,
        copy_symbology=True,
        results=results,
    )

    cloned = MirrorProjectLogic._find_layer_by_name(target, "roads")
    assert cloned is not None
    assert cloned.isValid()
    assert cloned.featureCount() == 1
    assert cloned.fields().names() == source.fields().names()
    assert not results["errors"]


def test_package_layer_updater_parses_history_and_detects_duplicate_fids():
    _ensure_qgis_application()
    parsed = PackageLayerUpdaterLogic._parse_history_entry(
        "Updated;2026-09-29@12-00-00;User;tester;DateModified;2026-09-28@11-30-00;Source;C:/data/roads.gpkg"
    )
    assert parsed["timestamp"] == datetime(2026, 9, 29, 12, 0)
    assert parsed["date_modified"] == datetime(2026, 9, 28, 11, 30)
    assert parsed["source"] == "C:/data/roads.gpkg"

    layer = _make_layer(include_fid=True)
    _add_feature(layer, (1, 1), "A", fid=1)
    _add_feature(layer, (2, 2), "B", fid=1)
    result = PackageLayerUpdaterLogic._check_and_fix_duplicate_fids(layer, False)

    assert result["can_proceed"] is False
    assert result["fixed_count"] == 0
    assert "duplicate FID" in result["message"]


def test_package_layer_updater_discovers_geopackage_vector_layer(tmp_path):
    _ensure_qgis_application()
    source = _make_layer(name="roads")
    _add_feature(source, (1, 2), "A")
    gpkg_path = tmp_path / "layers.gpkg"
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = "roads"
    error = QgsVectorFileWriter.writeAsVectorFormatV3(
        source, str(gpkg_path), QgsProject.instance().transformContext(), options
    )
    assert error[0] == QgsVectorFileWriter.NoError

    assert "roads" in PackageLayerUpdaterLogic._get_geopackage_layers(str(gpkg_path))


def test_validate_project_report_normalizes_paths_and_provider_suffixes():
    dialog = ValidateProjectReportDialog.__new__(ValidateProjectReportDialog)

    assert dialog.normalize_path(
        "FILE:///C:/Data/My%20Layer.gpkg|layername=roads", False
    ) == "c:/data/my layer.gpkg"
    assert dialog.normalize_path(
        "C:\\Data\\My Layer.gpkg|layername=roads", True
    ) == "C:/Data/My Layer.gpkg"
    assert dialog.normalize_path("", False) == ""

from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from threading import Thread

from openpyxl import Workbook
import pytest
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
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTableWidget,
)

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
from CeeThreeDeeQTools.Tools.ValidateProjectReport.ctdq_ValidateProjectReportJsonSource import (
    JsonSourceError,
    ValidateProjectReportJsonSource,
)
from CeeThreeDeeQTools.Tools.ValidateProjectReport.ctdq_ValidateProjectReportSettings import (
    ValidateProjectReportSettingsMixin,
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


def test_validate_project_report_default_path_uses_project_or_temp_directory(tmp_path):
    project_path = tmp_path / "Survey.qgz"
    assert ValidateProjectReportDialog.default_report_path(
        str(project_path), str(tmp_path / "temp")
    ) == str(tmp_path / "Survey_ValidationReport.html")
    assert ValidateProjectReportDialog.default_report_path(
        "", str(tmp_path / "temp")
    ) == str(tmp_path / "temp" / "ValidateProjectReport.html")
    assert ValidateProjectReportSettingsMixin.decode_cached_categories(
        '["value, with comma", "another value"]'
    ) == ["value, with comma", "another value"]
    assert ValidateProjectReportSettingsMixin.decode_cached_categories(
        "legacy one,legacy two"
    ) == ["legacy one", "legacy two"]


def test_validate_project_report_json_restore_skips_stale_excel_settings(
    tmp_path, monkeypatch
):
    _ensure_qgis_application()
    cached_values = {
        "source_mode": "Online JSON Source",
        "excel_file": str(tmp_path / "no-longer-used.xlsx"),
        "sheet": "Old worksheet",
    }
    monkeypatch.setattr(
        ValidateProjectReportSettingsMixin,
        "get_cached_value",
        lambda _self, key, default: cached_values.get(key, default),
    )
    loaded_excel_files = []
    monkeypatch.setattr(
        ValidateProjectReportDialog,
        "load_sheets",
        lambda _self, path: loaded_excel_files.append(path),
    )

    dialog = ValidateProjectReportDialog()
    try:
        assert dialog.source_mode_combo.currentText() == "Online JSON Source"
        assert loaded_excel_files == []
        assert dialog.sheet_combo.count() == 0
    finally:
        dialog.close()


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


def test_validate_project_report_reads_attributes_from_geometryless_layer():
    _ensure_qgis_application()
    project = QgsProject.instance()
    layer = QgsVectorLayer("None", "report rows", "memory")
    assert layer.isValid()
    layer.dataProvider().addAttributes(
        [
            QgsField("Layer Name", QVariant.String),
            QgsField("Source Path", QVariant.String),
            QgsField("Category", QVariant.String),
        ]
    )
    layer.updateFields()
    feature = QgsFeature(layer.fields())
    feature.setAttributes(["roads", "C:/data/roads.gpkg", "Transport"])
    layer.dataProvider().addFeature(feature)
    project.addMapLayer(layer)

    dialog = ValidateProjectReportDialog.__new__(ValidateProjectReportDialog)
    dialog.project = project
    dialog.source_mode_combo = QComboBox()
    dialog.source_mode_combo.addItem("Project Layer")
    dialog.project_layer_combo = QComboBox()
    dialog.project_layer_combo.addItem(layer.name(), layer.id())

    try:
        assert dialog.get_selected_field_values("Layer Name") == ["roads"]
        assert dialog.get_selected_field_values("Source Path") == ["C:/data/roads.gpkg"]
        assert dialog.get_filter_categories("Category") == {"Transport"}
    finally:
        project.removeMapLayer(layer.id())


def test_validate_project_report_reads_excel_fields_and_filter_categories(tmp_path):
    _ensure_qgis_application()
    workbook_path = tmp_path / "validation.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Validation"
    sheet.append(["Layer Name", "Source Path", "Category"])
    sheet.append(["roads", "C:/data/roads.gpkg", "Transport"])
    workbook.save(workbook_path)

    dialog = ValidateProjectReportDialog.__new__(ValidateProjectReportDialog)
    dialog.source_mode_combo = QComboBox()
    dialog.source_mode_combo.addItem("Excel Workbook")
    dialog.excel_file_edit = QLineEdit(str(workbook_path))
    dialog.sheet_combo = QComboBox()
    dialog.sheet_combo.addItem("Validation")
    dialog.header_row_spin = QSpinBox()
    dialog.header_row_spin.setValue(1)

    assert dialog.get_selected_field_values("Layer Name") == ["roads"]
    assert dialog.get_selected_field_values("Source Path") == ["C:/data/roads.gpkg"]
    assert dialog.get_filter_categories("Category") == {"Transport"}


def test_validate_project_report_generates_report_from_geometryless_layer(
    tmp_path, monkeypatch
):
    _ensure_qgis_application()
    project = QgsProject.instance()
    validation_layer = QgsVectorLayer("None", "validation rows", "memory")
    validation_layer.dataProvider().addAttributes(
        [
            QgsField("Layer Name", QVariant.String),
            QgsField("Source Path", QVariant.String),
        ]
    )
    validation_layer.updateFields()
    target_layer = _make_layer(name="roads")
    feature = QgsFeature(validation_layer.fields())
    feature.setAttributes(
        ["roads", target_layer.dataProvider().dataSourceUri()]
    )
    validation_layer.dataProvider().addFeature(feature)
    project.addMapLayer(validation_layer)
    project.addMapLayer(target_layer)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)

    try:
        dialog = ValidateProjectReportDialog()
        dialog.source_mode_combo.setCurrentText("Project Layer")
        assert not dialog.layer_name_combo.isEnabled()
        dialog.project_layer_combo.setCurrentIndex(
            dialog.project_layer_combo.findData(validation_layer.id())
        )
        assert dialog.layer_name_combo.isEnabled()
        dialog.layer_name_combo.setCurrentText("Layer Name")
        dialog.source_path_combo.setCurrentText("Source Path")
        dialog.use_filter_category_checkbox1.setChecked(False)
        dialog.use_filter_category_checkbox2.setChecked(False)
        html_report_path = tmp_path / "validation.html"
        dialog.report_path_widget.setFilePath(str(html_report_path))

        dialog.validate_project()

        report = (tmp_path / "validation.csv").read_text(encoding="utf-8")
        assert html_report_path.exists()
        assert "ValidationSourceType=Project Layer" in report
        assert "ValidationProjectLayerName=validation rows" in report
        assert "roads,MATCHED," in report
        assert "DATASOURCES_MATCHED=1" in report
        assert project.readEntry(
            "ValidateProjectReportDialog", "report_path"
        ) == (str(html_report_path), True)
        assert project.readEntry(
            "ValidateProjectReportDialog", "generate_csv_report"
        ) == ("True", True)
    finally:
        project.removeMapLayer(validation_layer.id())
        project.removeMapLayer(target_layer.id())


def test_validate_project_report_json_source_parses_common_record_shapes():
    assert ValidateProjectReportJsonSource.records_from_payload(
        [{"name": "roads", "meta": {"group": "Transport"}}]
    ) == [{"name": "roads", "meta.group": "Transport"}]
    assert ValidateProjectReportJsonSource.records_from_payload(
        {"data": {"results": [{"name": "roads"}]}}
    ) == [{"name": "roads"}]
    assert ValidateProjectReportJsonSource.records_from_payload(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": None,
                    "properties": {"name": "roads"},
                }
            ],
        }
    ) == [{"name": "roads"}]

    with pytest.raises(JsonSourceError, match="valid HTTP or HTTPS URL"):
        ValidateProjectReportJsonSource.validate_url("file:///tmp/data.json")
    with pytest.raises(JsonSourceError, match="Credentials must be selected"):
        ValidateProjectReportJsonSource.validate_url(
            "https://user:password@example.test/data.json"
        )
    assert ValidateProjectReportJsonSource.redact_url_for_report(
        "https://example.test/data?X-API-Key=secret&limit=20#token"
    ) == "https://example.test/data?X-API-Key=%2A%2A%2A&limit=20"


def test_validate_project_report_fetches_json_and_checks_connection(
    tmp_path, monkeypatch
):
    _ensure_qgis_application()
    target_layer = _make_layer(name="roads")
    source_records = [
        {
            "Layer Name": "roads",
            "Source Path": target_layer.dataProvider().dataSourceUri(),
        }
    ]

    class JsonHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            content = json.dumps(source_records).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, _format, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), JsonHandler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    project = QgsProject.instance()
    project.addMapLayer(target_layer)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)

    try:
        dialog = ValidateProjectReportDialog()
        assert (
            dialog.source_mode_label.text()
            == "Validation Project Layer Index Table:"
        )
        assert "How to use" in dialog.intro_panel.toPlainText()
        assert dialog.filter_group_box.layout().count() == 2
        assert dialog.filter_category_scroll1.minimumHeight() >= 120
        assert dialog.filter_category_scroll2.minimumHeight() >= 120
        assert dialog.report_path_widget.filePath().lower().endswith(".html")
        assert "last row" in dialog.duplicate_match_info_button.toolTip()
        assert (
            dialog.report_options_layout.itemAt(0).widget()
            is dialog.generate_csv_checkbox
        )
        assert (
            dialog.report_options_layout.itemAt(1).widget()
            is dialog.verbose_console_checkbox
        )
        dialog.source_mode_combo.setCurrentText("Online JSON Source")
        assert not dialog.layer_name_combo.isEnabled()
        assert not dialog.json_preview_button.isEnabled()
        dialog.json_url_edit.setText(f"http://127.0.0.1:{server.server_port}/records")
        dialog.check_json_connection()
        assert dialog.layer_name_combo.isEnabled()
        assert dialog.json_preview_button.isEnabled()
        preview_dialogs = []

        def capture_preview(preview_dialog):
            preview_dialogs.append(preview_dialog)
            return 0

        monkeypatch.setattr(QDialog, "exec", capture_preview)
        dialog.json_preview_button.click()
        preview_table = preview_dialogs[0].findChild(QTableWidget)
        assert preview_table.columnCount() == 2
        assert preview_table.horizontalHeaderItem(0).text() == "Layer Name"
        assert preview_table.horizontalHeaderItem(1).text() == "Source Path"
        assert preview_table.item(0, 0).text() == "roads"
        assert (
            preview_table.item(0, 1).text()
            == target_layer.dataProvider().dataSourceUri()
        )
        dialog.filter_category_combo1.setCurrentText("Layer Name")
        restored_filter_options = {
            "use_filter_category1": "True",
            "filter_category_field1": "Source Path",
            "filter_categories1": json.dumps(
                [target_layer.dataProvider().dataSourceUri()]
            ),
            "use_filter_category2": "False",
        }
        monkeypatch.setattr(
            dialog,
            "get_cached_value",
            lambda key, default: restored_filter_options.get(key, default),
        )
        dialog.restore_cached_filter_categories()
        restored_checkboxes = dialog.filter_category_widget1.findChildren(QCheckBox)
        assert [checkbox.text() for checkbox in restored_checkboxes] == [
            target_layer.dataProvider().dataSourceUri()
        ]
        assert restored_checkboxes[0].isChecked()
        dialog.filter_category_combo1.setCurrentText("Layer Name")
        assert [
            checkbox.text()
            for checkbox in dialog.filter_category_widget1.findChildren(QCheckBox)
        ] == ["roads"]
        dialog.filter_category_combo1.setCurrentText("Source Path")
        assert [
            checkbox.text()
            for checkbox in dialog.filter_category_widget1.findChildren(QCheckBox)
        ] == [target_layer.dataProvider().dataSourceUri()]
        dialog.layer_name_combo.setCurrentText("Layer Name")
        dialog.source_path_combo.setCurrentText("Source Path")
        dialog.use_filter_category_checkbox1.setChecked(False)
        dialog.use_filter_category_checkbox2.setChecked(False)
        dialog.generate_csv_checkbox.setChecked(False)
        dialog.report_path_widget.setFilePath(str(tmp_path / "json-validation.html"))

        dialog.validate_project()

        html_report = (tmp_path / "json-validation.html").read_text(encoding="utf-8")
        assert not (tmp_path / "json-validation.csv").exists()
        assert "<b>Validation JSON URL:</b>" in html_report
        assert "class='matched'" in html_report
        assert project.readEntry(
            "ValidateProjectReportDialog", "json_url"
        ) == (f"http://127.0.0.1:{server.server_port}/records", True)
        assert project.readEntry(
            "ValidateProjectReportDialog", "generate_csv_report"
        ) == ("False", True)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
        project.removeMapLayer(target_layer.id())

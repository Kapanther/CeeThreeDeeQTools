from qgis.PyQt.QtWidgets import QAbstractItemView, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QFileDialog, QMessageBox, QTextEdit, QSpinBox, QScrollArea, QWidget, QCheckBox, QGroupBox, QToolButton, QFrame, QTextBrowser, QTableWidget, QTableWidgetItem, QHeaderView
import openpyxl
from openpyxl import load_workbook
from qgis.core import QgsApplication, QgsProject, QgsVectorLayer
from qgis.gui import QgsFileWidget
import traceback  # Import traceback for detailed error information
from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
import os
import tempfile
from qgis.gui import QgsAuthConfigSelect, QgsCollapsibleGroupBox
from CeeThreeDeeQTools.Tools.ValidateProjectReport.ctdq_ValidateProjectReportJsonSource import (
    JsonSourceError,
    ValidateProjectReportJsonSource,
)
from CeeThreeDeeQTools.Tools.ValidateProjectReport.ctdq_ValidateProjectReportLogic import (
    ValidateProjectReportLogic,
)
from CeeThreeDeeQTools.Tools.ValidateProjectReport.ctdq_ValidateProjectReportReportWriter import (
    ValidateProjectReportReportWriter,
)
from CeeThreeDeeQTools.Tools.ValidateProjectReport.ctdq_ValidateProjectReportSettings import (
    ValidateProjectReportSettingsMixin,
)

class CustomTextBrowser(QTextBrowser):
    def setSource(self, url: QUrl, type=None):
        """
        Override the default behavior of QTextBrowser to prevent clearing the console.
        """
        if url.isLocalFile():
            QDesktopServices.openUrl(url)  # Open the local file in the default application
        else:
            super().setSource(url, type)

class ValidateProjectReportDialog(ValidateProjectReportSettingsMixin, QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Validate Project Report")
        self.setMinimumWidth(850)

        # Load cached selections from QGIS project variables
        self.project = QgsProject.instance()
        self.cache_prefix = "ValidateProjectReportDialog"
        self._json_records_cache_key = None
        self._json_records_cache = []
        self._report_path_is_temporary = False
        self._updating_report_path = False

        outer_layout = QHBoxLayout(self)
        content_widget = QWidget(self)
        layout = QVBoxLayout(content_widget)
        outer_layout.addWidget(content_widget, 4)

        self.intro_panel = QTextBrowser(self)
        self.intro_panel.setReadOnly(True)
        self.intro_panel.setMinimumWidth(250)
        self.intro_panel.setMaximumWidth(340)
        self.intro_panel.setFrameShape(QFrame.Shape.StyledPanel)
        self.intro_panel.setHtml(
            "<h2>About this tool</h2>"
            "<p>Checks the layers in the current QGIS project against a "
            "validation index and reports matching names, data sources, and "
            "missing index entries.</p>"
            "<h3>How to use</h3>"
            "<ol>"
            "<li>Select an Excel workbook, a project layer index table, or an "
            "online JSON source.</li>"
            "<li>Choose the layer-name and source-path fields. Enable either "
            "filter category when needed, then select the values to include.</li>"
            "<li>Set any layer-name delimiter and matching options, choose an "
            "output path, and select <b>Create Report</b>.</li>"
            "</ol>"
            "<p>For online JSON, enter the endpoint URL, optionally choose a "
            "saved QGIS authentication configuration, then use "
            "<b>Check Connection</b> to load its fields.</p>"
            "<p>Project-layer index tables need attributes only; geometry is "
            "not used.</p>"
            "<p>An HTML report is always created. A CSV copy and verbose console "
            "logging are optional.</p>"
        )
        outer_layout.addWidget(self.intro_panel, 2)

        # Validation input source
        source_mode_layout = QHBoxLayout()
        self.source_mode_combo = QComboBox(self)
        self.source_mode_combo.addItems(
            ["Excel Workbook", "Project Layer", "Online JSON Source"]
        )
        self.source_mode_label = QLabel(
            "Validation Project Layer Index Table:", self
        )
        source_mode_layout.addWidget(self.source_mode_label)
        source_mode_layout.addWidget(self.source_mode_combo)
        layout.addLayout(source_mode_layout)

        self.project_layer_widget = QWidget(self)
        project_layer_layout = QHBoxLayout(self.project_layer_widget)
        project_layer_layout.setContentsMargins(0, 0, 0, 0)
        self.project_layer_combo = QComboBox(self.project_layer_widget)
        project_layer_layout.addWidget(QLabel("Project Layer:", self.project_layer_widget))
        project_layer_layout.addWidget(self.project_layer_combo)
        layout.addWidget(self.project_layer_widget)

        self.json_source_widget = QWidget(self)
        json_source_layout = QVBoxLayout(self.json_source_widget)
        json_source_layout.setContentsMargins(0, 0, 0, 0)
        json_url_layout = QHBoxLayout()
        self.json_url_edit = QLineEdit(self.json_source_widget)
        self.json_url_edit.setText(self.get_cached_value("json_url", ""))
        json_url_layout.addWidget(QLabel("JSON URL:", self.json_source_widget))
        json_url_layout.addWidget(self.json_url_edit)
        json_source_layout.addLayout(json_url_layout)

        json_auth_layout = QHBoxLayout()
        self.json_auth_config_select = QgsAuthConfigSelect(self)
        self.json_auth_config_select.setConfigId(
            self.get_cached_value("json_auth_config_id", "")
        )
        json_auth_layout.addWidget(QLabel("Authentication:", self.json_source_widget))
        json_auth_layout.addWidget(self.json_auth_config_select)
        json_source_layout.addLayout(json_auth_layout)

        json_actions_layout = QHBoxLayout()
        self.check_json_connection_button = QPushButton(
            "Check Connection", self.json_source_widget
        )
        self.check_json_connection_button.clicked.connect(self.check_json_connection)
        self.json_preview_button = QPushButton(
            "Preview Data Table", self.json_source_widget
        )
        self.json_preview_button.setEnabled(False)
        self.json_preview_button.clicked.connect(self.preview_json_data)
        json_actions_layout.addWidget(self.check_json_connection_button)
        json_actions_layout.addWidget(self.json_preview_button)
        json_source_layout.addLayout(json_actions_layout)
        layout.addWidget(self.json_source_widget)

        # Excel file selection
        self.excel_options_widget = QWidget(self)
        excel_options_layout = QVBoxLayout(self.excel_options_widget)
        excel_options_layout.setContentsMargins(0, 0, 0, 0)
        excel_file_layout = QHBoxLayout()
        self.excel_file_edit = QLineEdit(self)
        self.excel_file_edit.setText(self.get_cached_value("excel_file", ""))
        browse_button = QPushButton("Browse", self)
        browse_button.clicked.connect(self.browse_excel_file)
        excel_file_layout.addWidget(QLabel("Excel File:", self))
        excel_file_layout.addWidget(self.excel_file_edit)
        excel_file_layout.addWidget(browse_button)
        excel_options_layout.addLayout(excel_file_layout)

        # Worksheet selection
        self.sheet_combo = QComboBox(self)
        self.sheet_combo.currentIndexChanged.connect(self.populate_headers)
        excel_options_layout.addWidget(QLabel("Select Worksheet:"))
        excel_options_layout.addWidget(self.sheet_combo)

        # Header row selection
        header_row_layout = QHBoxLayout()
        self.header_row_spin = QSpinBox(self)
        self.header_row_spin.setMinimum(1)
        self.header_row_spin.setValue(int(self.get_cached_value("header_row", "1")))
        self.header_row_spin.valueChanged.connect(self.populate_headers)
        header_row_layout.addWidget(QLabel("Header Row:"))
        header_row_layout.addWidget(self.header_row_spin)
        excel_options_layout.addLayout(header_row_layout)

        # Max columns selection
        max_columns_layout = QHBoxLayout()
        self.max_columns_spin = QSpinBox(self)
        self.max_columns_spin.setMinimum(1)
        self.max_columns_spin.setValue(int(self.get_cached_value("max_columns", "20")))
        self.max_columns_spin.valueChanged.connect(self.populate_headers)
        max_columns_layout.addWidget(QLabel("Max Columns:"))
        max_columns_layout.addWidget(self.max_columns_spin)
        excel_options_layout.addLayout(max_columns_layout)
        layout.addWidget(self.excel_options_widget)

        self.source_mode_combo.currentTextChanged.connect(self.toggle_source_mode)
        self.source_mode_combo.currentTextChanged.connect(
            lambda mode: self.save_cached_value("source_mode", mode)
        )
        self.json_url_edit.textChanged.connect(self.invalidate_json_cache)
        self.json_url_edit.editingFinished.connect(self.save_json_settings)
        self.json_url_edit.editingFinished.connect(self.load_json_fields)
        self.json_auth_config_select.selectedConfigIdChanged.connect(
            self.on_json_auth_config_changed
        )
        removed_config_signal = getattr(
            self.json_auth_config_select, "selectedConfigIdRemoved", None
        )
        if removed_config_signal is not None:
            removed_config_signal.connect(self.on_json_auth_config_changed)

        # Layer name field selection
        self.layer_name_combo = QComboBox(self)
        (
            self.layer_name_field_label,
            self.layer_name_info_button,
        ) = self.add_info_label(
            layout,
            "Layer Name Field:",
            "Choose the field containing the exact layer name shown in the Layers panel. "
            "If a descriptor delimiter is set, text after the delimiter is ignored "
            "when matching.",
        )
        layout.addWidget(self.layer_name_combo)

        # Source path field selection
        self.source_path_combo = QComboBox(self)
        (
            self.source_path_field_label,
            self.source_path_info_button,
        ) = self.add_info_label(
            layout,
            "Source Path Field:",
            "Choose the field containing the expected data source path. The tool "
            "compares it with the source path used by each project layer.",
        )
        layout.addWidget(self.source_path_combo)

        # Layer Name Descriptor Delimiter
        layer_name_delimiter_layout = QHBoxLayout()
        self.layer_name_delimiter_edit = QLineEdit(self)
        self.layer_name_delimiter_edit.setText(self.get_cached_value("layer_name_delimiter", "_"))  # Default to "_"
        self.layer_name_delimiter_label = QLabel(
            "Layer Name Descriptor Delimiter:", self
        )
        self.layer_name_delimiter_info_button = self.create_info_button(
            "Text in project layer names after this delimiter is ignored during matching."
        )
        layer_name_delimiter_layout.addWidget(self.layer_name_delimiter_label)
        layer_name_delimiter_layout.addWidget(
            self.layer_name_delimiter_info_button
        )
        layer_name_delimiter_layout.addWidget(self.layer_name_delimiter_edit)
        layout.addLayout(layer_name_delimiter_layout)

        # Case-Sensitive Layer Matching
        self.case_sensitive_checkbox = QCheckBox("Case-Sensitive Layer Matching", self)
        self.case_sensitive_checkbox.setChecked(False)  # Default to unchecked
        layout.addWidget(self.case_sensitive_checkbox)

        # Collapsible panel for filter categories
        self.filter_group_box = QgsCollapsibleGroupBox(self)
        self.filter_group_box.setTitle("Filter Categories")
        self.filter_group_box.setCollapsed(False)  # Default to expanded
        filter_layout = QHBoxLayout(self.filter_group_box)
        first_filter_column = QWidget(self.filter_group_box)
        first_filter_layout = QVBoxLayout(first_filter_column)
        first_filter_layout.setContentsMargins(0, 0, 0, 0)
        second_filter_column = QWidget(self.filter_group_box)
        second_filter_layout = QVBoxLayout(second_filter_column)
        second_filter_layout.setContentsMargins(0, 0, 0, 0)

        # First filter category
        self.use_filter_category_checkbox1 = QCheckBox("Enable First Filter Category", self)
        self.use_filter_category_checkbox1.setChecked(True)
        self.use_filter_category_checkbox1.stateChanged.connect(self.toggle_filter_category1)
        first_filter_layout.addWidget(self.use_filter_category_checkbox1)

        self.filter_category_combo1 = QComboBox(self)
        self.filter_category_combo1.currentIndexChanged.connect(self.populate_filter_categories1)
        first_filter_layout.addWidget(QLabel("First Filter Category Field:"))
        first_filter_layout.addWidget(self.filter_category_combo1)

        self.filter_category_scroll1 = QScrollArea(self)
        self.filter_category_scroll1.setWidgetResizable(True)
        self.filter_category_scroll1.setMinimumHeight(120)
        self.filter_category_widget1 = QWidget()
        self.filter_category_layout1 = QVBoxLayout(self.filter_category_widget1)
        self.filter_category_scroll1.setWidget(self.filter_category_widget1)
        first_filter_layout.addWidget(QLabel("Select First Filter Categories:"))
        first_filter_layout.addWidget(self.filter_category_scroll1)

        # Second filter category
        self.use_filter_category_checkbox2 = QCheckBox("Enable Second Filter Category", self)
        self.use_filter_category_checkbox2.setChecked(False)
        self.use_filter_category_checkbox2.stateChanged.connect(self.toggle_filter_category2)
        second_filter_layout.addWidget(self.use_filter_category_checkbox2)

        self.filter_category_combo2 = QComboBox(self)
        self.filter_category_combo2.currentIndexChanged.connect(self.populate_filter_categories2)
        second_filter_layout.addWidget(QLabel("Second Filter Category Field:"))
        second_filter_layout.addWidget(self.filter_category_combo2)

        self.filter_category_scroll2 = QScrollArea(self)
        self.filter_category_scroll2.setWidgetResizable(True)
        self.filter_category_scroll2.setMinimumHeight(120)
        self.filter_category_widget2 = QWidget()
        self.filter_category_layout2 = QVBoxLayout(self.filter_category_widget2)
        self.filter_category_scroll2.setWidget(self.filter_category_widget2)
        second_filter_layout.addWidget(QLabel("Select Second Filter Categories:"))
        second_filter_layout.addWidget(self.filter_category_scroll2)
        filter_layout.addWidget(first_filter_column)
        filter_layout.addWidget(second_filter_column)

        filter_group_row = QHBoxLayout()
        filter_group_row.addWidget(self.filter_group_box, 1)
        self.filter_info_button = self.create_info_button(
            "Use these categories to narrow the index rows before matching, "
            "especially when layer names repeat. Duplicate Match Mode is saved "
            "but does not currently change matching results."
        )
        filter_group_row.addWidget(
            self.filter_info_button, 0, Qt.AlignmentFlag.AlignTop
        )
        layout.addLayout(filter_group_row)
        self.refresh_project_layers()
        self.project_layer_combo.currentIndexChanged.connect(self.populate_project_layer_fields)
        self.project_layer_combo.currentIndexChanged.connect(self.save_selected_project_layer)

        # Duplicate match mode selection
        duplicate_match_layout = QHBoxLayout()
        self.duplicate_match_combo = QComboBox(self)
        self.duplicate_match_combo.addItems(["STOP ON FIRST SOURCE MATCH", "STOP ON FIRST LAYER MATCH"])
        self.duplicate_match_combo.setCurrentText(self.get_cached_value("duplicate_match_mode", "STOP ON FIRST SOURCE MATCH"))
        self.duplicate_match_label = QLabel("Duplicate Match Mode:", self)
        self.duplicate_match_info_button = self.create_info_button(
            "The selected mode is saved but is not currently applied by the matching "
            "logic. When duplicate index rows have the same normalized layer name, "
            "the last row replaces earlier rows."
        )
        duplicate_match_layout.addWidget(self.duplicate_match_label)
        duplicate_match_layout.addWidget(self.duplicate_match_info_button)
        duplicate_match_layout.addWidget(self.duplicate_match_combo)
        layout.addLayout(duplicate_match_layout)

        # HTML report output path
        report_path_layout = QHBoxLayout()
        self.report_path_widget = QgsFileWidget(self)
        self.report_path_widget.setStorageMode(QgsFileWidget.StorageMode.SaveFile)
        self.report_path_widget.setFilter("HTML files (*.html)")
        cached_report_path = self.get_cached_value("report_path", "")
        if cached_report_path:
            report_path = self.html_report_path(cached_report_path)
            self.report_path_widget.setFilePath(report_path)
            self._report_path_is_temporary = False
        else:
            self.set_report_path(
                self.default_report_path(),
                temporary=False,
            )
        self.report_path_widget.fileChanged.connect(self.on_report_path_changed)
        report_path_layout.addWidget(QLabel("HTML Report Output:", self))
        report_path_layout.addWidget(self.report_path_widget)
        layout.addLayout(report_path_layout)

        # Optional CSV output and console settings
        self.report_options_layout = QHBoxLayout()
        self.generate_csv_checkbox = QCheckBox("Also Generate CSV Report", self)
        self.generate_csv_checkbox.setChecked(True)
        self.report_options_layout.addWidget(self.generate_csv_checkbox)
        self.verbose_console_checkbox = QCheckBox("Verbose Console", self)
        self.verbose_console_checkbox.setChecked(
            self.get_cached_value("verbose_console", "False") == "True"
        )
        self.report_options_layout.addWidget(self.verbose_console_checkbox)
        self.report_options_layout.addStretch()
        layout.addLayout(self.report_options_layout)

        # Debug console log (use CustomTextBrowser for clickable links)
        self.log_console = CustomTextBrowser(self)
        self.log_console.setOpenExternalLinks(False)  # Disable automatic handling of external links
        layout.addWidget(QLabel("Console:"))
        layout.addWidget(self.log_console)

        # OK and Cancel buttons
        button_layout = QHBoxLayout()
        ok_button = QPushButton("Create Report", self)
        ok_button.clicked.connect(self.validate_project)
        cancel_button = QPushButton("Exit", self)
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        self.validation_selection_widgets = [
            self.layer_name_field_label,
            self.layer_name_info_button,
            self.layer_name_combo,
            self.source_path_field_label,
            self.source_path_info_button,
            self.source_path_combo,
            self.layer_name_delimiter_label,
            self.layer_name_delimiter_info_button,
            self.layer_name_delimiter_edit,
            self.case_sensitive_checkbox,
            self.filter_group_box,
            self.duplicate_match_label,
            self.duplicate_match_info_button,
            self.duplicate_match_combo,
        ]
        self.set_validation_selections_enabled(False)

        # Show the dialog immediately and restore cached selections in the background
        self.show()
        self.restore_cached_selections_with_progress()

    def create_info_button(self, tooltip):
        button = QToolButton(self)
        button.setIcon(QgsApplication.getThemeIcon("/mIconInfo.svg"))
        button.setAutoRaise(True)
        button.setToolTip(tooltip)
        button.setAccessibleName("More information")
        button.setFixedSize(20, 20)
        return button

    def add_info_label(self, layout, label_text, tooltip):
        row_layout = QHBoxLayout()
        label = QLabel(label_text, self)
        info_button = self.create_info_button(tooltip)
        row_layout.addWidget(label)
        row_layout.addWidget(info_button)
        row_layout.addStretch()
        layout.addLayout(row_layout)
        return label, info_button

    def set_validation_selections_enabled(self, enabled):
        for widget in getattr(self, "validation_selection_widgets", []):
            widget.setEnabled(enabled)

    @staticmethod
    def html_report_path(path):
        path = path.strip()
        root, extension = os.path.splitext(path)
        if extension.lower() == ".html":
            return path
        if extension:
            return f"{root}.html"
        return f"{path}.html"

    @staticmethod
    def default_report_path(project_path=None, temp_directory=None):
        """Choose a report path beside the saved project or in the temp folder."""
        if project_path is None:
            project_path = QgsProject.instance().fileName()
        if project_path:
            project_directory = os.path.dirname(os.path.abspath(project_path))
            project_name = os.path.splitext(os.path.basename(project_path))[0]
            return os.path.join(
                project_directory, f"{project_name}_ValidationReport.html"
            )
        return os.path.join(
            temp_directory or tempfile.gettempdir(),
            "ValidateProjectReport.html",
        )

    def set_report_path(self, path, temporary=False):
        self._updating_report_path = True
        try:
            self.report_path_widget.setFilePath(path)
        finally:
            self._updating_report_path = False
        self._report_path_is_temporary = temporary

    def on_report_path_changed(self, path):
        if self._updating_report_path:
            return
        path = path.strip()
        self._report_path_is_temporary = not bool(path)
        self.save_cached_value("report_path", path)

    def selected_html_report_path(self):
        path = self.report_path_widget.filePath().strip()
        temporary = self._report_path_is_temporary
        if not path:
            path = self.default_report_path()
            temporary = False
        path = self.html_report_path(path)
        if path != self.report_path_widget.filePath():
            self.set_report_path(path, temporary=temporary)
        if not temporary:
            self.save_cached_value("report_path", path)
        return path

    def refresh_project_layers(self, selected_layer_id=""):
        """Populate the source-layer selector with project vector layers."""
        self.project_layer_combo.clear()
        self.project_layer_combo.addItem("Select a project layer...", "")
        for layer in self.project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                self.project_layer_combo.addItem(layer.name(), layer.id())

        if selected_layer_id:
            index = self.project_layer_combo.findData(selected_layer_id)
            if index >= 0:
                self.project_layer_combo.setCurrentIndex(index)

    def selected_project_layer(self):
        """Return the currently selected project vector layer, if it still exists."""
        layer_id = self.project_layer_combo.currentData()
        layer = self.project.mapLayer(layer_id) if layer_id else None
        return layer if isinstance(layer, QgsVectorLayer) else None

    def invalidate_json_cache(self, _text=None):
        self._json_records_cache_key = None
        self._json_records_cache = []
        if (
            self.source_mode_combo.currentText() == "Online JSON Source"
            and hasattr(self, "layer_name_combo")
        ):
            self.clear_source_fields()

    def save_json_settings(self):
        self.save_cached_value("json_url", self.json_url_edit.text().strip())
        self.save_cached_value(
            "json_auth_config_id", self.json_auth_config_select.configId()
        )

    def on_json_auth_config_changed(self, _auth_config_id=""):
        self.invalidate_json_cache()
        self.save_cached_value(
            "json_auth_config_id", self.json_auth_config_select.configId()
        )
        if self.source_mode_combo.currentText() == "Online JSON Source":
            self.populate_json_fields(show_errors=True)

    def get_json_records(self, force_refresh=False):
        url = self.json_url_edit.text().strip()
        auth_config_id = self.json_auth_config_select.configId()
        cache_key = (url, auth_config_id)
        if force_refresh or self._json_records_cache_key != cache_key:
            self._json_records_cache = ValidateProjectReportJsonSource.fetch_records(
                url, auth_config_id
            )
            self._json_records_cache_key = cache_key
        return self._json_records_cache

    def clear_source_fields(self):
        self.json_preview_button.setEnabled(False)
        self.set_validation_selections_enabled(False)
        for combo in (
            self.layer_name_combo,
            self.source_path_combo,
            self.filter_category_combo1,
            self.filter_category_combo2,
        ):
            combo.clear()
        self.clear_filter_category_layout1()
        self.clear_filter_category_layout2()

    def set_source_fields(self, fields):
        self.set_validation_selections_enabled(False)
        for combo in (
            self.layer_name_combo,
            self.source_path_combo,
            self.filter_category_combo1,
            self.filter_category_combo2,
        ):
            previous_value = combo.currentText()
            signals_were_blocked = combo.blockSignals(True)
            try:
                combo.clear()
                combo.addItems(fields)
                if previous_value in fields:
                    combo.setCurrentText(previous_value)
            finally:
                combo.blockSignals(signals_were_blocked)
        self.populate_filter_categories1()
        self.populate_filter_categories2()
        self.set_validation_selections_enabled(bool(fields))

    def populate_json_fields(self, force_refresh=False, show_errors=False):
        if not self.json_url_edit.text().strip():
            self.clear_source_fields()
            return False
        try:
            records = self.get_json_records(force_refresh=force_refresh)
        except JsonSourceError as exc:
            self.clear_source_fields()
            self.log_message(f"Failed to load JSON source: {exc}")
            if show_errors:
                QMessageBox.critical(self, "JSON Source Error", str(exc))
            return False

        fields = list(
            dict.fromkeys(
                field_name
                for record in records
                for field_name in record
            )
        )
        if not fields:
            self.clear_source_fields()
            return False
        self.set_source_fields(fields)
        self.json_preview_button.setEnabled(True)
        self.log_message(
            f"JSON source loaded: {len(records)} records, {len(fields)} fields.",
            debug=True,
        )
        return True

    def load_json_fields(self):
        if self.source_mode_combo.currentText() == "Online JSON Source":
            self.save_json_settings()
            self.populate_json_fields(show_errors=True)

    def check_json_connection(self):
        self.save_json_settings()
        if self.populate_json_fields(force_refresh=True, show_errors=True):
            records = self._json_records_cache
            field_count = len(
                {
                    field_name
                    for record in records
                    for field_name in record
                }
            )
            QMessageBox.information(
                self,
                "Connection Successful",
                f"Loaded {len(records)} JSON records with {field_count} fields.",
            )

    def preview_json_data(self):
        if self.source_mode_combo.currentText() != "Online JSON Source":
            return
        if not self.populate_json_fields(force_refresh=True, show_errors=True):
            return

        records = self._json_records_cache
        fields = list(dict.fromkeys(field for record in records for field in record))
        if not records or not fields:
            QMessageBox.information(
                self, "JSON Data Preview", "The JSON source contains no previewable data."
            )
            return

        preview_dialog = QDialog(self)
        preview_dialog.setWindowTitle("JSON Data Preview")
        preview_dialog.resize(900, 600)
        preview_layout = QVBoxLayout(preview_dialog)
        preview_layout.addWidget(
            QLabel(f"Previewing {len(records)} records across {len(fields)} fields.")
        )

        table = QTableWidget(len(records), len(fields), preview_dialog)
        table.setHorizontalHeaderLabels(fields)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        for row_index, record in enumerate(records):
            for column_index, field in enumerate(fields):
                value = record.get(field)
                table.setItem(
                    row_index,
                    column_index,
                    QTableWidgetItem("" if value is None else str(value)),
                )
        table.resizeColumnsToContents()
        for column_index in range(len(fields)):
            if table.columnWidth(column_index) > 400:
                table.setColumnWidth(column_index, 400)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        preview_layout.addWidget(table)

        close_button = QPushButton("Close", preview_dialog)
        close_button.clicked.connect(preview_dialog.accept)
        preview_layout.addWidget(close_button)
        preview_dialog.exec()

    def save_selected_project_layer(self, _index=None):
        layer = self.selected_project_layer()
        self.save_cached_value("project_layer_id", layer.id() if layer else "")
        self.save_cached_value("project_layer_name", layer.name() if layer else "")

    def toggle_source_mode(self, mode):
        """Show source-specific controls and populate fields for the selected source."""
        use_project_layer = mode == "Project Layer"
        use_json_source = mode == "Online JSON Source"
        self.project_layer_widget.setVisible(use_project_layer)
        self.excel_options_widget.setVisible(
            mode == "Excel Workbook"
        )
        self.json_source_widget.setVisible(use_json_source)
        if not use_json_source:
            self.json_preview_button.setEnabled(False)
        if use_project_layer:
            self.populate_project_layer_fields()
        elif use_json_source:
            self.populate_json_fields(show_errors=False)
        else:
            self.populate_headers()

    def toggle_filter_category1(self, state):
        """
        Enable or disable the first filter category dropdown and scrollable box based on the checkbox state.
        """
        enabled = state == Qt.CheckState.Checked
        self.filter_category_combo1.setEnabled(enabled)
        self.filter_category_scroll1.setEnabled(enabled)
        self.log_message(f"First filter category {'enabled' if enabled else 'disabled'}.", debug=True)

    def toggle_filter_category2(self, state):
        """
        Enable or disable the second filter category dropdown and scrollable box based on the checkbox state.
        """
        enabled = state == Qt.CheckState.Checked
        self.filter_category_combo2.setEnabled(enabled)
        self.filter_category_scroll2.setEnabled(enabled)
        self.log_message(f"Second filter category {'enabled' if enabled else 'disabled'}.", debug=True)

    def log_message(self, message, debug=False):
        """
        Append a message to the debug console log.
        If `debug` is True, the message will only be logged if "Verbose Console" is enabled.
        """
        if debug and not self.verbose_console_checkbox.isChecked():
            return  # Skip debug messages if "Verbose Console" is disabled
        self.log_console.append(message)
        self.log_console.ensureCursorVisible()  # Ensure the console scrolls to the bottom

    def log_message_link(self, message, link):
        """
        Append a clickable link to the debug console log.
        :param message: The display text for the link.
        :param link: The actual link (file path or URL).
        """
        file_url = QUrl.fromLocalFile(link).toString()
        format_message = message + f" ({link})"
        self.log_console.append(f'<a href="{file_url}">{format_message}</a>')
        self.log_console.ensureCursorVisible()  # Ensure the console scrolls to the bottom

    def open_link(self, url: QUrl):
        """
        Open the clicked link in the default application.
        """
        self.log_console.append(f"DEBUG: Clicked URL: {url.toString()}")  # Debugging log
        if url.isLocalFile():
            QDesktopServices.openUrl(url)  # Open the local file in the default application
        else:
            self.log_message(f"Invalid link: {url.toString()}")  # Log invalid links for debugging

    def browse_excel_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Excel File", "", "Excel files (*.xlsx *.xlsm)")
        if file_path:
            self.excel_file_edit.setText(file_path)
            self.save_cached_value("excel_file", file_path)
            self.log_message(f"Selected Excel file: {file_path}")
            self.load_sheets(file_path)

    def load_sheets(self, file_path):
        """
        Populate the worksheet combo box based on the selected Excel file.
        """
        try:
            workbook = load_workbook(file_path, data_only=True)
            self.sheet_combo.clear()
            self.sheet_combo.addItems(workbook.sheetnames)
            self.log_message(f"Worksheets loaded: {', '.join(workbook.sheetnames)}",debug=True)
        except Exception as e:
            self.sheet_combo.clear()
            QMessageBox.critical(self, "Error", f"Failed to load worksheets: {e}")
            self.log_message(f"Error loading worksheets: {e}")

    def populate_headers(self):
        """
        Populate the Layer Name, Source Path, and Filter Category field combo boxes based on the selected worksheet and header row.
        """
        if self.source_mode_combo.currentText() == "Project Layer":
            self.populate_project_layer_fields()
            return
        if self.source_mode_combo.currentText() == "Online JSON Source":
            self.populate_json_fields(show_errors=False)
            return

        file_path = self.excel_file_edit.text()
        sheet_name = self.sheet_combo.currentText()
        header_row = self.header_row_spin.value()
        max_columns = self.max_columns_spin.value()

        if not file_path or not sheet_name:
            self.clear_source_fields()
            return

        try:
            workbook = load_workbook(file_path, data_only=True, read_only=True)
            sheet = workbook[sheet_name]

            # Read the header row
            headers = [
                cell.value for cell in sheet[header_row][:max_columns]
                if cell.value is not None
            ]

            self.set_source_fields(headers)

            self.log_message(f"Headers populated from row {header_row}: {', '.join(headers)}",debug=True)
        except Exception as e:
            self.clear_source_fields()
            QMessageBox.critical(self, "Error", f"Failed to populate headers: {e}")
            self.log_message(f"Error populating headers: {e}")

    def populate_project_layer_fields(self, _index=None):
        """Populate shared field selectors from the selected layer's attributes."""
        layer = self.selected_project_layer()
        fields = layer.fields().names() if layer else []
        self.set_source_fields(fields)

        if layer:
            self.log_message(
                f"Fields populated from project layer '{layer.name()}': {', '.join(fields)}",
                debug=True,
            )

    def get_selected_field_values(self, field_name):
        """Read a field's values from the selected validation source."""
        return list(self.iter_selected_field_values(field_name))

    def iter_selected_field_values(self, field_name):
        """Iterate a field's values without loading the entire source into memory."""
        if self.source_mode_combo.currentText() == "Project Layer":
            layer = self.selected_project_layer()
            if layer is None:
                return
            if field_name not in layer.fields().names():
                raise ValueError(f"Selected field '{field_name}' is not present in the project layer.")
            for feature in layer.getFeatures():
                yield feature[field_name]
            return
        if self.source_mode_combo.currentText() == "Online JSON Source":
            for record in self.get_json_records():
                yield record.get(field_name)
            return

        file_path = self.excel_file_edit.text()
        sheet_name = self.sheet_combo.currentText()
        if not file_path or not sheet_name or not field_name:
            return

        workbook = load_workbook(file_path, data_only=True, read_only=True)
        try:
            sheet = workbook[sheet_name]
            headers = {
                cell.value: index
                for index, cell in enumerate(sheet[self.header_row_spin.value()], start=0)
            }
            if field_name not in headers:
                raise ValueError(f"Selected field '{field_name}' is not present in the worksheet header.")
            column = headers[field_name]
            for row in sheet.iter_rows(
                min_row=self.header_row_spin.value() + 1,
                max_row=sheet.max_row,
            ):
                yield row[column].value
        finally:
            workbook.close()

    def populate_filter_categories1(self):
        """
        Populate the first filter category selection box based on the selected filter category field.
        """
        file_path = self.excel_file_edit.text()
        sheet_name = self.sheet_combo.currentText()
        filter_category_field1 = self.filter_category_combo1.currentText()

        if not filter_category_field1 or (
            self.source_mode_combo.currentText() == "Excel Workbook"
            and (not file_path or not sheet_name)
        ) or (
            self.source_mode_combo.currentText() == "Project Layer"
            and self.selected_project_layer() is None
        ):
            self.clear_filter_category_layout1()
            return

        self.clear_filter_category_layout1()
        try:
            categories = self.get_filter_categories(filter_category_field1)
            for category in sorted(categories):
                checkbox = QCheckBox(category)
                self.filter_category_layout1.addWidget(checkbox)

            self.log_message(f"Filter categories populated: {', '.join(categories)}",debug=True)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to populate filter categories: {e}")
            self.log_message(f"Error populating filter categories: {e}")

    def populate_filter_categories2(self):
        """
        Populate the second filter category selection box based on the selected second filter category field.
        """
        file_path = self.excel_file_edit.text()
        sheet_name = self.sheet_combo.currentText()
        filter_category_field2 = self.filter_category_combo2.currentText()

        if not filter_category_field2 or (
            self.source_mode_combo.currentText() == "Excel Workbook"
            and (not file_path or not sheet_name)
        ) or (
            self.source_mode_combo.currentText() == "Project Layer"
            and self.selected_project_layer() is None
        ):
            self.clear_filter_category_layout2()
            return

        self.clear_filter_category_layout2()
        try:
            categories = self.get_filter_categories(filter_category_field2)
            for category in sorted(categories):
                checkbox = QCheckBox(category)
                self.filter_category_layout2.addWidget(checkbox)

            self.log_message(f"Second filter categories populated: {', '.join(categories)}",debug=True)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to populate second filter categories: {e}")
            self.log_message(f"Error populating second filter categories: {e}")

    def get_filter_categories(self, field_name):
        categories = set()
        for value in self.iter_selected_field_values(field_name):
            if value is not None and str(value):
                categories.add(str(value))
            if len(categories) >= 20:
                break
        return categories

    def clear_filter_category_layout1(self):
        """
        Clear all widgets from the first filter category layout and force a UI update.
        """
        self.log_message("Clearing filter category layout...", debug=True)
        for i in reversed(range(self.filter_category_layout1.count())):
            item = self.filter_category_layout1.itemAt(i)
            widget = item.widget()
            if widget:
                self.log_message(f"Removing widget: {widget.text()}", debug=True)
                self.filter_category_layout1.removeWidget(widget)
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.filter_category_layout1.update()  # Force the layout to update
        self.filter_category_widget1.update()  # Force the parent widget to update
        self.log_message("Filter category layout cleared.", debug=True)

    def clear_filter_category_layout2(self):
        """
        Clear all widgets from the second filter category layout and force a UI update.
        """
        self.log_message("Clearing second filter category layout...", debug=True)
        for i in reversed(range(self.filter_category_layout2.count())):
            item = self.filter_category_layout2.itemAt(i)
            widget = item.widget()
            if widget:
                self.log_message(f"Removing widget: {widget.text()}", debug=True)
                self.filter_category_layout2.removeWidget(widget)
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.filter_category_layout2.update()  # Force the layout to update
        self.filter_category_widget2.update()  # Force the parent widget to update
        self.log_message("Second filter category layout cleared.", debug=True)

    def normalize_path(self, path, case_sensitive):
        return ValidateProjectReportLogic.normalize_path(path, case_sensitive)

    def validate_project(self):
        """
        Perform the validation logic and write the validation report.
        """
        # Save user selections to project variables
        self.save_cached_value("header_row", self.header_row_spin.value())
        self.save_cached_value("max_columns", self.max_columns_spin.value())
        self.save_cached_value("excel_file", self.excel_file_edit.text())
        self.save_cached_value("duplicate_match_mode", self.duplicate_match_combo.currentText())
        self.save_cached_value("sheet", self.sheet_combo.currentText())
        self.save_cached_value("layer_name_field", self.layer_name_combo.currentText())
        self.save_cached_value("source_path_field", self.source_path_combo.currentText())
        self.save_cached_value("use_filter_category1", str(self.use_filter_category_checkbox1.isChecked()))
        self.save_cached_value("filter_category_field1", self.filter_category_combo1.currentText())
        selected_categories1 = [
            checkbox.text() for i in range(self.filter_category_layout1.count())
            if isinstance((checkbox := self.filter_category_layout1.itemAt(i).widget()), QCheckBox) and checkbox.isChecked()
        ]
        self.save_cached_value(
            "filter_categories1",
            self.encode_cached_categories(selected_categories1),
        )

        self.save_cached_value("use_filter_category2", str(self.use_filter_category_checkbox2.isChecked()))
        self.save_cached_value("filter_category_field2", self.filter_category_combo2.currentText())
        selected_categories2 = [
            checkbox.text() for i in range(self.filter_category_layout2.count())
            if isinstance((checkbox := self.filter_category_layout2.itemAt(i).widget()), QCheckBox) and checkbox.isChecked()
        ]
        self.save_cached_value(
            "filter_categories2",
            self.encode_cached_categories(selected_categories2),
        )

        self.save_cached_value("layer_name_delimiter", self.layer_name_delimiter_edit.text())
        self.save_cached_value("case_sensitive_matching", str(self.case_sensitive_checkbox.isChecked()))
        self.save_cached_value(
            "generate_csv_report", str(self.generate_csv_checkbox.isChecked())
        )
        self.save_cached_value("verbose_console", str(self.verbose_console_checkbox.isChecked()))
        self.save_cached_value("source_mode", self.source_mode_combo.currentText())
        self.save_json_settings()
        self.save_selected_project_layer()
        layer_name_delimiter = self.layer_name_delimiter_edit.text()
        case_sensitive_matching = self.case_sensitive_checkbox.isChecked()

        source_mode = self.source_mode_combo.currentText()
        excel_file = self.excel_file_edit.text()
        sheet_name = self.sheet_combo.currentText()
        header_row = self.header_row_spin.value()
        validation_layer = self.selected_project_layer() if source_mode == "Project Layer" else None
        layer_name_field = self.layer_name_combo.currentText()
        source_path_field = self.source_path_combo.currentText()
        filter_category_field1 = self.filter_category_combo1.currentText()
        report_path = self.selected_html_report_path()
        use_filter1_category = self.use_filter_category_checkbox1.isChecked()
        use_filter2_category = self.use_filter_category_checkbox2.isChecked()
        filter_category_field2 = self.filter_category_combo2.currentText()

        if source_mode == "Excel Workbook":
            missing_source = not excel_file or not sheet_name
        elif source_mode == "Project Layer":
            missing_source = validation_layer is None
        else:
            missing_source = not self.json_url_edit.text().strip()
        if missing_source or not layer_name_field or not source_path_field:
            QMessageBox.warning(self, "Missing Input", "Please fill in all fields before proceeding.")
            self.log_message("Validation aborted: Missing input fields.")
            return

        try:
            if source_mode == "Excel Workbook":
                workbook = load_workbook(excel_file, data_only=True, read_only=True)
                sheet = workbook[sheet_name]
                headers = {
                    cell.value: idx
                    for idx, cell in enumerate(sheet[header_row], start=0)
                }
                if (
                    layer_name_field not in headers
                    or source_path_field not in headers
                    or (use_filter1_category and filter_category_field1 not in headers)
                    or (use_filter2_category and filter_category_field2 not in headers)
                ):
                    raise ValueError("Selected fields not found in the header row.")

                layer_name_col = headers[layer_name_field]
                source_path_col = headers[source_path_field]
                filter_category_col1 = headers[filter_category_field1] if use_filter1_category else None
                filter_category_col2 = headers[filter_category_field2] if use_filter2_category else None
                source_rows = (
                    (
                        row[layer_name_col].value,
                        row[source_path_col].value,
                        row[filter_category_col1].value if use_filter1_category else None,
                        row[filter_category_col2].value if use_filter2_category else None,
                    )
                    for row in sheet.iter_rows(
                        min_row=header_row + 1,
                        max_row=sheet.max_row,
                    )
                )
            elif source_mode == "Project Layer":
                if validation_layer is None:
                    raise ValueError("The selected project layer is no longer available.")
                layer_fields = validation_layer.fields().names()
                if (
                    layer_name_field not in layer_fields
                    or source_path_field not in layer_fields
                    or (use_filter1_category and filter_category_field1 not in layer_fields)
                    or (use_filter2_category and filter_category_field2 not in layer_fields)
                ):
                    raise ValueError("Selected fields not found in the project layer.")
                source_rows = (
                    (
                        feature[layer_name_field],
                        feature[source_path_field],
                        feature[filter_category_field1] if use_filter1_category else None,
                        feature[filter_category_field2] if use_filter2_category else None,
                    )
                    for feature in validation_layer.getFeatures()
                )
            else:
                records = self.get_json_records(force_refresh=True)
                json_fields = {
                    field_name
                    for record in records
                    for field_name in record
                }
                if (
                    layer_name_field not in json_fields
                    or source_path_field not in json_fields
                    or (use_filter1_category and filter_category_field1 not in json_fields)
                    or (use_filter2_category and filter_category_field2 not in json_fields)
                ):
                    raise ValueError("Selected fields not found in the JSON response.")
                source_rows = (
                    (
                        record.get(layer_name_field),
                        record.get(source_path_field),
                        record.get(filter_category_field1) if use_filter1_category else None,
                        record.get(filter_category_field2) if use_filter2_category else None,
                    )
                    for record in records
                )

            possible_layers = ValidateProjectReportLogic.build_possible_layers(
                source_rows,
                use_filter1_category,
                selected_categories1,
                use_filter2_category,
                selected_categories2,
                case_sensitive_matching,
            )

            self.log_message(f"Possible layers extracted: {possible_layers}", debug=True)

            (
                html_rows,
                unmatched_layers,
                matched_count,
                wrong_source_count,
                layer_name_not_found_count,
                total_count,
            ) = ValidateProjectReportLogic.validate_project_layers(
                QgsProject.instance().mapLayers(),
                possible_layers,
                layer_name_delimiter,
                case_sensitive_matching,
                progress_callback=lambda message: self.log_message(
                    message, debug=True
                ),
            )

            self.log_message(f"Unmatched layers after validation: {unmatched_layers}", debug=True)

            # Collect validation details
            from datetime import datetime
            import getpass
            report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            report_user = getpass.getuser()
            qgis_project_path = QgsProject.instance().fileName()
            validation_excel_date_modified = ""
            validation_project_layer_name = ""
            validation_project_layer_source = ""
            validation_json_url = ""
            validation_json_auth_config_id = ""
            if source_mode == "Excel Workbook":
                validation_excel_date_modified = datetime.fromtimestamp(
                    os.path.getmtime(excel_file)
                ).strftime("%Y-%m-%d %H:%M:%S")
            elif source_mode == "Project Layer" and validation_layer is not None:
                validation_project_layer_name = validation_layer.name()
                validation_project_layer_source = validation_layer.dataProvider().dataSourceUri()
            else:
                validation_json_url = (
                    ValidateProjectReportJsonSource.redact_url_for_report(
                        self.json_url_edit.text().strip()
                    )
                )
                validation_json_auth_config_id = self.json_auth_config_select.configId()
            validation_filter_categories1 = ";".join(selected_categories1)
            validation_filter_categories2 = ";".join(selected_categories2)

            report_details = {
                "report_date": report_date,
                "report_user": report_user,
                "qgis_project_path": qgis_project_path,
                "source_mode": source_mode,
                "excel_file": excel_file,
                "sheet_name": sheet_name,
                "excel_date_modified": validation_excel_date_modified,
                "project_layer_name": validation_project_layer_name,
                "project_layer_source": validation_project_layer_source,
                "json_url": validation_json_url,
                "json_auth_config_id": validation_json_auth_config_id,
                "layer_name_field": layer_name_field,
                "source_path_field": source_path_field,
                "filter_categories1": validation_filter_categories1,
                "filter_categories2": validation_filter_categories2,
            }
            html_report_path, csv_report_path = ValidateProjectReportReportWriter.write_reports(
                report_path,
                report_details,
                html_rows,
                unmatched_layers,
                matched_count,
                wrong_source_count,
                layer_name_not_found_count,
                total_count,
                self.generate_csv_checkbox.isChecked(),
            )
            self.log_message_link("HTML report written to:", html_report_path)
            if csv_report_path:
                self.log_message_link("CSV report written to:", csv_report_path)

            QMessageBox.information(self, "Validation Complete", "Validation report generated successfully.")
        except Exception as e:
            # Capture the traceback details
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Error", f"Validation failed: {e}\n\nDetails:\n{tb}")
            self.log_message(f"Validation failed: {e}\nTraceback:\n{tb}", debug=True)

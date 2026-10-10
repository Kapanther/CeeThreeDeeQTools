from qgis.PyQt.QtWidgets import QCheckBox, QProgressDialog
from qgis.PyQt.QtCore import Qt


class ValidateProjectReportSettingsMixin:
    """Restores and persists the validation dialog's project settings."""

    def restore_cached_selections_with_progress(self):
        tasks = [
            ("Restoring input source", self.restore_cached_source),
            ("Loading Excel file", self.load_cached_excel_file),
            ("Loading worksheet", self.load_cached_worksheet),
            ("Populating headers", self.populate_cached_headers),
            ("Restoring filter categories", self.restore_cached_filter_categories),
            ("Restoring other settings", self.restore_other_cached_settings),
        ]

        progress_dialog = QProgressDialog(
            "Restoring cached selections...", "Cancel", 0, len(tasks), self
        )
        progress_dialog.setWindowTitle("Loading")
        progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dialog.setMinimumDuration(0)

        for index, (description, task) in enumerate(tasks):
            if progress_dialog.wasCanceled():
                break
            progress_dialog.setLabelText(description)
            progress_dialog.setValue(index)
            task()
        progress_dialog.setValue(len(tasks))

    def restore_cached_source(self):
        cached_mode = self.get_cached_value("source_mode", "Excel Workbook")
        if cached_mode not in (
            "Excel Workbook",
            "Project Layer",
            "Online JSON Source",
        ):
            cached_mode = "Excel Workbook"
        self.source_mode_combo.setCurrentText(cached_mode)
        cached_layer_id = self.get_cached_value("project_layer_id", "")
        if not cached_layer_id:
            cached_layer_name = self.get_cached_value("project_layer_name", "")
            for index in range(self.project_layer_combo.count()):
                if self.project_layer_combo.itemText(index) == cached_layer_name:
                    cached_layer_id = self.project_layer_combo.itemData(index)
                    break
        self.refresh_project_layers(cached_layer_id)
        self.toggle_source_mode(cached_mode)

    def load_cached_excel_file(self):
        excel_file = self.get_cached_value("excel_file", "")
        if excel_file:
            self.excel_file_edit.setText(excel_file)
            self.load_sheets(excel_file)

    def load_cached_worksheet(self):
        cached_sheet = self.get_cached_value("sheet", "")
        if cached_sheet and cached_sheet in [
            self.sheet_combo.itemText(index)
            for index in range(self.sheet_combo.count())
        ]:
            self.sheet_combo.setCurrentText(cached_sheet)

    def populate_cached_headers(self):
        self.populate_headers()
        cached_layer_name = self.get_cached_value("layer_name_field", "")
        cached_source_path = self.get_cached_value("source_path_field", "")
        if cached_layer_name and cached_layer_name in [
            self.layer_name_combo.itemText(index)
            for index in range(self.layer_name_combo.count())
        ]:
            self.layer_name_combo.setCurrentText(cached_layer_name)
        if cached_source_path and cached_source_path in [
            self.source_path_combo.itemText(index)
            for index in range(self.source_path_combo.count())
        ]:
            self.source_path_combo.setCurrentText(cached_source_path)

    def restore_cached_filter_categories(self):
        use_filter_category1 = (
            self.get_cached_value("use_filter_category1", "True") == "True"
        )
        self.use_filter_category_checkbox1.setChecked(use_filter_category1)
        cached_filter_field1 = self.get_cached_value("filter_category_field1", "")
        if (
            use_filter_category1
            and cached_filter_field1
            and cached_filter_field1
            in [
                self.filter_category_combo1.itemText(index)
                for index in range(self.filter_category_combo1.count())
            ]
        ):
            self.filter_category_combo1.setCurrentText(cached_filter_field1)
            self.populate_filter_categories1()
            cached_categories1 = self.get_cached_value(
                "filter_categories1", ""
            ).split(",")
            for index in range(self.filter_category_layout1.count()):
                checkbox = self.filter_category_layout1.itemAt(index).widget()
                if (
                    isinstance(checkbox, QCheckBox)
                    and checkbox.text() in cached_categories1
                ):
                    checkbox.setChecked(True)

        use_filter_category2 = (
            self.get_cached_value("use_filter_category2", "False") == "True"
        )
        self.use_filter_category_checkbox2.setChecked(use_filter_category2)
        cached_filter_field2 = self.get_cached_value("filter_category_field2", "")
        if (
            use_filter_category2
            and cached_filter_field2
            and cached_filter_field2
            in [
                self.filter_category_combo2.itemText(index)
                for index in range(self.filter_category_combo2.count())
            ]
        ):
            self.filter_category_combo2.setCurrentText(cached_filter_field2)
            self.populate_filter_categories2()
            cached_categories2 = self.get_cached_value(
                "filter_categories2", ""
            ).split(",")
            for index in range(self.filter_category_layout2.count()):
                checkbox = self.filter_category_layout2.itemAt(index).widget()
                if (
                    isinstance(checkbox, QCheckBox)
                    and checkbox.text() in cached_categories2
                ):
                    checkbox.setChecked(True)

    def restore_other_cached_settings(self):
        cached_report_path = self.get_cached_value("report_path", "")
        if cached_report_path:
            migrated_report_path = self.html_report_path(cached_report_path)
            if migrated_report_path != cached_report_path:
                self.set_report_path(migrated_report_path, temporary=False)
                self.save_cached_value("report_path", migrated_report_path)
        self.layer_name_delimiter_edit.setText(
            self.get_cached_value("layer_name_delimiter", "_")
        )
        self.case_sensitive_checkbox.setChecked(
            self.get_cached_value("case_sensitive_matching", "False") == "True"
        )
        self.generate_csv_checkbox.setChecked(
            self.get_cached_value("generate_csv_report", "True") == "True"
        )
        self.verbose_console_checkbox.setChecked(
            self.get_cached_value("verbose_console", "False") == "True"
        )

    def get_cached_value(self, key, default):
        value, ok = self.project.readEntry(self.cache_prefix, key)
        if not ok or not value:
            return default
        return value

    def save_cached_value(self, key, value):
        try:
            self.project.writeEntry(self.cache_prefix, key, str(value))
            self.log_message(
                f"Saved project variable: {self.cache_prefix}/{key} = {value}",
                debug=True,
            )
        except Exception as exc:
            self.log_message(
                f"Failed to save project variable: {self.cache_prefix}/{key}. "
                f"Error: {exc}"
            )

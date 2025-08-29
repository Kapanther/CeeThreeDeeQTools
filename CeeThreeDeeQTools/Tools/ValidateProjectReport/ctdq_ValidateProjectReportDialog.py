from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QFileDialog, QMessageBox, QTextEdit, QSpinBox, QScrollArea, QWidget, QCheckBox, QGroupBox, QVBoxLayout, QToolButton, QFrame, QTextBrowser
import openpyxl
from openpyxl import load_workbook
from qgis.core import QgsProject
import traceback  # Import traceback for detailed error information
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
import os

class CustomTextBrowser(QTextBrowser):
    def setSource(self, url: QUrl, type=None):
        """
        Override the default behavior of QTextBrowser to prevent clearing the console.
        """
        if url.isLocalFile():
            QDesktopServices.openUrl(url)  # Open the local file in the default application
        else:
            super().setSource(url, type)

class ValidateProjectReportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Validate Project Report")
        self.setMinimumWidth(400)

        # Load cached selections from QGIS project variables
        self.project = QgsProject.instance()
        self.cache_prefix = "ValidateProjectReportDialog"

        layout = QVBoxLayout(self)

        # Excel file selection
        excel_file_layout = QHBoxLayout()
        self.excel_file_edit = QLineEdit(self)
        self.excel_file_edit.setText(self.get_cached_value("excel_file", ""))
        browse_button = QPushButton("Browse", self)
        browse_button.clicked.connect(self.browse_excel_file)
        excel_file_layout.addWidget(QLabel("Excel File:", self))
        excel_file_layout.addWidget(self.excel_file_edit)
        excel_file_layout.addWidget(browse_button)
        layout.addLayout(excel_file_layout)

        # Worksheet selection
        self.sheet_combo = QComboBox(self)
        self.sheet_combo.currentIndexChanged.connect(self.populate_headers)
        layout.addWidget(QLabel("Select Worksheet:"))
        layout.addWidget(self.sheet_combo)

        # Header row selection
        header_row_layout = QHBoxLayout()
        self.header_row_spin = QSpinBox(self)
        self.header_row_spin.setMinimum(1)
        self.header_row_spin.setValue(int(self.get_cached_value("header_row", "1")))
        self.header_row_spin.valueChanged.connect(self.populate_headers)
        header_row_layout.addWidget(QLabel("Header Row:"))
        header_row_layout.addWidget(self.header_row_spin)
        layout.addLayout(header_row_layout)

        # Max columns selection
        max_columns_layout = QHBoxLayout()
        self.max_columns_spin = QSpinBox(self)
        self.max_columns_spin.setMinimum(1)
        self.max_columns_spin.setValue(int(self.get_cached_value("max_columns", "20")))
        self.max_columns_spin.valueChanged.connect(self.populate_headers)
        max_columns_layout.addWidget(QLabel("Max Columns:"))
        max_columns_layout.addWidget(self.max_columns_spin)
        layout.addLayout(max_columns_layout)

        # Layer name field selection
        self.layer_name_combo = QComboBox(self)
        layout.addWidget(QLabel("Layer Name Field:"))
        layout.addWidget(self.layer_name_combo)

        # Source path field selection
        self.source_path_combo = QComboBox(self)
        layout.addWidget(QLabel("Source Path Field:"))
        layout.addWidget(self.source_path_combo)

        # Layer Name Descriptor Delimiter
        layer_name_delimiter_layout = QHBoxLayout()
        self.layer_name_delimiter_edit = QLineEdit(self)
        self.layer_name_delimiter_edit.setText(self.get_cached_value("layer_name_delimiter", "_"))  # Default to "_"
        layer_name_delimiter_layout.addWidget(QLabel("Layer Name Descriptor Delimiter:"))
        layer_name_delimiter_layout.addWidget(self.layer_name_delimiter_edit)
        layout.addLayout(layer_name_delimiter_layout)

        # Case-Sensitive Layer Matching
        self.case_sensitive_checkbox = QCheckBox("Case-Sensitive Layer Matching", self)
        self.case_sensitive_checkbox.setChecked(False)  # Default to unchecked
        layout.addWidget(self.case_sensitive_checkbox)

        # Collapsible panel for filter categories
        self.filter_group_box = QGroupBox("Filter Categories")
        self.filter_group_box.setCheckable(True)
        self.filter_group_box.setChecked(True)
        filter_layout = QVBoxLayout(self.filter_group_box)

        # First filter category
        self.use_filter_category_checkbox = QCheckBox("Enable First Filter Category", self)
        self.use_filter_category_checkbox.setChecked(True)
        self.use_filter_category_checkbox.stateChanged.connect(self.toggle_filter_category)
        filter_layout.addWidget(self.use_filter_category_checkbox)

        self.filter_category_combo = QComboBox(self)
        self.filter_category_combo.currentIndexChanged.connect(self.populate_filter_categories)
        filter_layout.addWidget(QLabel("First Filter Category Field:"))
        filter_layout.addWidget(self.filter_category_combo)

        self.filter_category_scroll = QScrollArea(self)
        self.filter_category_scroll.setWidgetResizable(True)
        self.filter_category_widget = QWidget()
        self.filter_category_layout = QVBoxLayout(self.filter_category_widget)
        self.filter_category_scroll.setWidget(self.filter_category_widget)
        filter_layout.addWidget(QLabel("Select First Filter Categories:"))
        filter_layout.addWidget(self.filter_category_scroll)

        # Second filter category
        self.use_second_filter_category_checkbox = QCheckBox("Enable Second Filter Category", self)
        self.use_second_filter_category_checkbox.setChecked(False)
        self.use_second_filter_category_checkbox.stateChanged.connect(self.toggle_second_filter_category)
        filter_layout.addWidget(self.use_second_filter_category_checkbox)

        self.second_filter_category_combo = QComboBox(self)
        self.second_filter_category_combo.currentIndexChanged.connect(self.populate_second_filter_categories)
        filter_layout.addWidget(QLabel("Second Filter Category Field:"))
        filter_layout.addWidget(self.second_filter_category_combo)

        self.second_filter_category_scroll = QScrollArea(self)
        self.second_filter_category_scroll.setWidgetResizable(True)
        self.second_filter_category_widget = QWidget()
        self.second_filter_category_layout = QVBoxLayout(self.second_filter_category_widget)
        self.second_filter_category_scroll.setWidget(self.second_filter_category_widget)
        filter_layout.addWidget(QLabel("Select Second Filter Categories:"))
        filter_layout.addWidget(self.second_filter_category_scroll)

        layout.addWidget(self.filter_group_box)

        # Duplicate match mode selection
        duplicate_match_layout = QHBoxLayout()
        self.duplicate_match_combo = QComboBox(self)
        self.duplicate_match_combo.addItems(["STOP ON FIRST SOURCE MATCH", "STOP ON FIRST LAYER MATCH"])
        self.duplicate_match_combo.setCurrentText(self.get_cached_value("duplicate_match_mode", "STOP ON FIRST SOURCE MATCH"))
        duplicate_match_layout.addWidget(QLabel("Duplicate Match Mode:", self))
        duplicate_match_layout.addWidget(self.duplicate_match_combo)
        layout.addLayout(duplicate_match_layout)

        # Validation report path selection
        report_path_layout = QHBoxLayout()
        self.report_path_edit = QLineEdit(self)
        self.report_path_edit.setText(self.get_cached_value("report_path", ""))
        browse_report_button = QPushButton("Browse", self)
        browse_report_button.clicked.connect(self.browse_report_path)
        report_path_layout.addWidget(QLabel("Validation Report Path:", self))
        report_path_layout.addWidget(self.report_path_edit)
        report_path_layout.addWidget(browse_report_button)
        layout.addLayout(report_path_layout)

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

        # Restore cached selections
        self.restore_cached_selections()

    def toggle_filter_category(self, state):
        """
        Enable or disable the first filter category dropdown and scrollable box based on the checkbox state.
        """
        enabled = state == Qt.Checked
        self.filter_category_combo.setEnabled(enabled)
        self.filter_category_scroll.setEnabled(enabled)
        self.log_message(f"First filter category {'enabled' if enabled else 'disabled'}.")

    def toggle_second_filter_category(self, state):
        """
        Enable or disable the second filter category dropdown and scrollable box based on the checkbox state.
        """
        enabled = state == Qt.Checked
        self.second_filter_category_combo.setEnabled(enabled)
        self.second_filter_category_scroll.setEnabled(enabled)
        self.log_message(f"Second filter category {'enabled' if enabled else 'disabled'}.")

    def restore_cached_selections(self):
        """
        Restore cached selections and validate them.
        """
        excel_file = self.get_cached_value("excel_file", "")
        if excel_file:
            self.excel_file_edit.setText(excel_file)
            self.load_sheets(excel_file)

            cached_sheet = self.get_cached_value("sheet", "")
            if cached_sheet and cached_sheet in [self.sheet_combo.itemText(i) for i in range(self.sheet_combo.count())]:
                self.sheet_combo.setCurrentText(cached_sheet)

                # Populate headers and validate cached fields
                self.populate_headers()
                cached_layer_name = self.get_cached_value("layer_name_field", "")
                cached_source_path = self.get_cached_value("source_path_field", "")

                if cached_layer_name and cached_layer_name in [self.layer_name_combo.itemText(i) for i in range(self.layer_name_combo.count())]:
                    self.layer_name_combo.setCurrentText(cached_layer_name)

                if cached_source_path and cached_source_path in [self.source_path_combo.itemText(i) for i in range(self.source_path_combo.count())]:
                    self.source_path_combo.setCurrentText(cached_source_path)

        use_filter_category = self.get_cached_value("use_filter_category", "True") == "True"
        self.use_filter_category_checkbox.setChecked(use_filter_category)

        cached_filter_category_field = self.get_cached_value("filter_category_field", "")
        if use_filter_category and cached_filter_category_field and cached_filter_category_field in [self.filter_category_combo.itemText(i) for i in range(self.filter_category_combo.count())]:
            self.filter_category_combo.setCurrentText(cached_filter_category_field)

            # Populate filter categories and validate cached selections
            self.populate_filter_categories()
            cached_filter_categories = self.get_cached_value("filter_categories", "").split(",")
            for i in range(self.filter_category_layout.count()):
                checkbox = self.filter_category_layout.itemAt(i).widget()
                if isinstance(checkbox, QCheckBox) and checkbox.text() in cached_filter_categories:
                    checkbox.setChecked(True)

        use_second_filter_category = self.get_cached_value("use_second_filter_category", "False") == "True"
        self.use_second_filter_category_checkbox.setChecked(use_second_filter_category)

        cached_second_filter_category_field = self.get_cached_value("second_filter_category_field", "")
        if use_second_filter_category and cached_second_filter_category_field and cached_second_filter_category_field in [self.second_filter_category_combo.itemText(i) for i in range(self.second_filter_category_combo.count())]:
            self.second_filter_category_combo.setCurrentText(cached_second_filter_category_field)

            # Populate second filter categories and validate cached selections
            self.populate_second_filter_categories()
            cached_second_filter_categories = self.get_cached_value("second_filter_categories", "").split(",")
            for i in range(self.second_filter_category_layout.count()):
                checkbox = self.second_filter_category_layout.itemAt(i).widget()
                if isinstance(checkbox, QCheckBox) and checkbox.text() in cached_second_filter_categories:
                    checkbox.setChecked(True)

        # Restore Layer Name Descriptor Delimiter
        self.layer_name_delimiter_edit.setText(self.get_cached_value("layer_name_delimiter", "_"))

        # Restore Case-Sensitive Layer Matching
        self.case_sensitive_checkbox.setChecked(self.get_cached_value("case_sensitive_matching", "False") == "True")

        # Set default report path if not restored from settings
        cached_report_path = self.get_cached_value("report_path", "")
        if cached_report_path:
            self.report_path_edit.setText(cached_report_path)
        else:
            qgis_project_path = QgsProject.instance().fileName()
            if qgis_project_path:
                project_dir = os.path.dirname(qgis_project_path)
                project_name = os.path.splitext(os.path.basename(qgis_project_path))[0]
                default_report_path = os.path.join(project_dir, f"{project_name}_ValidationReport.csv")
                self.report_path_edit.setText(default_report_path)
                self.log_message(f"Default report path set to: {default_report_path}")
            else:
                self.log_message("No QGIS project loaded. Unable to set default report path.")

    def get_cached_value(self, key, default):
        """
        Retrieve a cached value from QGIS project variables.
        If the value is empty or invalid, return the default value.
        """
        group_name = self.cache_prefix
        value, ok = self.project.readEntry(group_name, key)
        if not ok or not value:  # Check for empty or invalid values
            return default
        return value

    def save_cached_value(self, key, value):
        """
        Save a value to QGIS project variables.
        """
        group_name = self.cache_prefix
        try:
            self.project.writeEntry(group_name, key, str(value))  # Save the value as a string
            self.log_message(f"Saved project variable: {group_name}/{key} = {value}")
        except Exception as e:
            self.log_message(f"Failed to save project variable: {group_name}/{key}. Error: {e}")

    def log_message(self, message):
        """
        Append a regular message to the debug console log.
        """
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
            self.log_message(f"Worksheets loaded: {', '.join(workbook.sheetnames)}")
        except Exception as e:
            self.sheet_combo.clear()
            QMessageBox.critical(self, "Error", f"Failed to load worksheets: {e}")
            self.log_message(f"Error loading worksheets: {e}")

    def populate_headers(self):
        """
        Populate the Layer Name, Source Path, and Filter Category field combo boxes based on the selected worksheet and header row.
        """
        file_path = self.excel_file_edit.text()
        sheet_name = self.sheet_combo.currentText()
        header_row = self.header_row_spin.value()
        max_columns = self.max_columns_spin.value()

        if not file_path or not sheet_name:
            return

        try:
            workbook = load_workbook(file_path, data_only=True, read_only=True)
            sheet = workbook[sheet_name]

            # Read the header row
            headers = [
                cell.value for cell in sheet[header_row][:max_columns]
                if cell.value is not None
            ]

            self.layer_name_combo.clear()
            self.layer_name_combo.addItems(headers)

            self.source_path_combo.clear()
            self.source_path_combo.addItems(headers)

            self.filter_category_combo.clear()
            self.filter_category_combo.addItems(headers)

            self.second_filter_category_combo.clear()
            self.second_filter_category_combo.addItems(headers)

            self.log_message(f"Headers populated from row {header_row}: {', '.join(headers)}")
        except Exception as e:
            self.layer_name_combo.clear()
            self.source_path_combo.clear()
            self.filter_category_combo.clear()
            self.second_filter_category_combo.clear()
            QMessageBox.critical(self, "Error", f"Failed to populate headers: {e}")
            self.log_message(f"Error populating headers: {e}")

    def populate_filter_categories(self):
        """
        Populate the filter category selection box based on the selected filter category field.
        """
        file_path = self.excel_file_edit.text()
        sheet_name = self.sheet_combo.currentText()
        header_row = self.header_row_spin.value()
        filter_category_field = self.filter_category_combo.currentText()

        if not file_path or not sheet_name or not filter_category_field:
            # Clear the filter category layout if no valid field is selected
            self.clear_filter_category_layout()
            return

        try:
            workbook = load_workbook(file_path, data_only=True, read_only=True)
            sheet = workbook[sheet_name]

            # Get the column index for the filter category field
            headers = {cell.value: idx for idx, cell in enumerate(sheet[header_row], start=0)}
            if filter_category_field not in headers:
                raise ValueError("Selected filter category field not found in the header row.")

            filter_category_col = headers[filter_category_field]

            # Extract unique values from the filter category column
            categories = set()
            for row in sheet.iter_rows(min_row=header_row + 1, max_row=sheet.max_row):
                value = row[filter_category_col].value
                if value:
                    categories.add(str(value))
                if len(categories) >= 20:  # Limit to 20 categories
                    break

            # Clear the filter category layout before repopulating
            self.clear_filter_category_layout()

            # Populate the scrollable filter category selection box
            for category in sorted(categories):
                checkbox = QCheckBox(category)
                self.filter_category_layout.addWidget(checkbox)

            self.log_message(f"Filter categories populated: {', '.join(categories)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to populate filter categories: {e}")
            self.log_message(f"Error populating filter categories: {e}")

    def populate_second_filter_categories(self):
        """
        Populate the second filter category selection box based on the selected second filter category field.
        """
        file_path = self.excel_file_edit.text()
        sheet_name = self.sheet_combo.currentText()
        header_row = self.header_row_spin.value()
        second_filter_category_field = self.second_filter_category_combo.currentText()

        if not file_path or not sheet_name or not second_filter_category_field:
            # Clear the second filter category layout if no valid field is selected
            self.clear_second_filter_category_layout()
            return

        try:
            workbook = load_workbook(file_path, data_only=True, read_only=True)
            sheet = workbook[sheet_name]

            # Get the column index for the second filter category field
            headers = {cell.value: idx for idx, cell in enumerate(sheet[header_row], start=0)}
            if second_filter_category_field not in headers:
                raise ValueError("Selected second filter category field not found in the header row.")

            second_filter_category_col = headers[second_filter_category_field]

            # Extract unique values from the second filter category column
            categories = set()
            for row in sheet.iter_rows(min_row=header_row + 1, max_row=sheet.max_row):
                value = row[second_filter_category_col].value
                if value:
                    categories.add(str(value))
                if len(categories) >= 20:  # Limit to 20 categories
                    break

            # Clear the second filter category layout before repopulating
            self.clear_second_filter_category_layout()

            # Populate the scrollable second filter category selection box
            for category in sorted(categories):
                checkbox = QCheckBox(category)
                self.second_filter_category_layout.addWidget(checkbox)

            self.log_message(f"Second filter categories populated: {', '.join(categories)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to populate second filter categories: {e}")
            self.log_message(f"Error populating second filter categories: {e}")

    def clear_filter_category_layout(self):
        """
        Clear all widgets from the filter category layout and force a UI update.
        """
        self.log_message("Clearing filter category layout...")
        for i in reversed(range(self.filter_category_layout.count())):
            item = self.filter_category_layout.itemAt(i)
            widget = item.widget()
            if widget:
                self.log_message(f"Removing widget: {widget.text()}")
                self.filter_category_layout.removeWidget(widget)
                widget.deleteLater()
        self.filter_category_layout.update()  # Force the layout to update
        self.filter_category_widget.update()  # Force the parent widget to update
        self.log_message("Filter category layout cleared.")

    def clear_second_filter_category_layout(self):
        """
        Clear all widgets from the second filter category layout and force a UI update.
        """
        self.log_message("Clearing second filter category layout...")
        for i in reversed(range(self.second_filter_category_layout.count())):
            item = self.second_filter_category_layout.itemAt(i)
            widget = item.widget()
            if widget:
                self.log_message(f"Removing widget: {widget.text()}")
                self.second_filter_category_layout.removeWidget(widget)
                widget.deleteLater()
        self.second_filter_category_layout.update()  # Force the layout to update
        self.second_filter_category_widget.update()  # Force the parent widget to update
        self.log_message("Second filter category layout cleared.")

    def browse_report_path(self):
        """
        Open a file dialog to select the validation report path.
        """
        file_path, _ = QFileDialog.getSaveFileName(self, "Select Validation Report Path", "", "CSV files (*.csv);;All files (*.*)")
        if file_path:
            self.report_path_edit.setText(file_path)
            self.save_cached_value("report_path", file_path)
            self.log_message(f"Selected validation report path: {file_path}")

    def normalize_path(self, path, case_sensitive):
        """
        Normalize a file path or data source string for consistent comparison.
        """
        if not path:
            return ""
        # Maintain case sensitivity if required
        normalized = path.strip().replace("\\", "/")
        if not case_sensitive:
            normalized = normalized.lower()
        # Remove redundant slashes
        while "//" in normalized:
            normalized = normalized.replace("//", "/")
        # Remove everything after the | symbol
        if "|" in normalized:
            normalized = normalized.split("|", 1)[0]
        return normalized

    def validate_project(self):
        """
        Perform the validation logic and write the validation report.
        """
        # Save user selections to project variables
        self.save_cached_value("header_row", self.header_row_spin.value())
        self.save_cached_value("max_columns", self.max_columns_spin.value())
        self.save_cached_value("duplicate_match_mode", self.duplicate_match_combo.currentText())
        self.save_cached_value("sheet", self.sheet_combo.currentText())
        self.save_cached_value("layer_name_field", self.layer_name_combo.currentText())
        self.save_cached_value("source_path_field", self.source_path_combo.currentText())
        self.save_cached_value("use_filter_category", str(self.use_filter_category_checkbox.isChecked()))
        self.save_cached_value("filter_category_field", self.filter_category_combo.currentText())
        selected_categories = [
            checkbox.text() for i in range(self.filter_category_layout.count())
            if isinstance((checkbox := self.filter_category_layout.itemAt(i).widget()), QCheckBox) and checkbox.isChecked()
        ]
        self.save_cached_value("filter_categories", ",".join(selected_categories))

        self.save_cached_value("use_second_filter_category", str(self.use_second_filter_category_checkbox.isChecked()))
        self.save_cached_value("second_filter_category_field", self.second_filter_category_combo.currentText())
        second_selected_categories = [
            checkbox.text() for i in range(self.second_filter_category_layout.count())
            if isinstance((checkbox := self.second_filter_category_layout.itemAt(i).widget()), QCheckBox) and checkbox.isChecked()
        ]
        self.save_cached_value("second_filter_categories", ",".join(second_selected_categories))

        self.save_cached_value("layer_name_delimiter", self.layer_name_delimiter_edit.text())
        self.save_cached_value("case_sensitive_matching", str(self.case_sensitive_checkbox.isChecked()))
        layer_name_delimiter = self.layer_name_delimiter_edit.text()
        case_sensitive_matching = self.case_sensitive_checkbox.isChecked()

        excel_file = self.excel_file_edit.text()
        sheet_name = self.sheet_combo.currentText()
        header_row = self.header_row_spin.value()
        layer_name_field = self.layer_name_combo.currentText()
        source_path_field = self.source_path_combo.currentText()
        filter_category_field = self.filter_category_combo.currentText()
        report_path = self.report_path_edit.text()
        duplicate_match_mode = self.duplicate_match_combo.currentText()
        use_filter_category = self.use_filter_category_checkbox.isChecked()
        use_second_filter_category = self.use_second_filter_category_checkbox.isChecked()
        second_filter_category_field = self.second_filter_category_combo.currentText()

        if not excel_file or not sheet_name or not layer_name_field or not source_path_field or not report_path:
            QMessageBox.warning(self, "Missing Input", "Please fill in all fields before proceeding.")
            self.log_message("Validation aborted: Missing input fields.")
            return

        try:
            workbook = load_workbook(excel_file, data_only=True, read_only=True)
            sheet = workbook[sheet_name]

            # Map header names to column indices
            headers = {cell.value: idx for idx, cell in enumerate(sheet[header_row], start=0)}
            if layer_name_field not in headers or source_path_field not in headers or (use_filter_category and filter_category_field not in headers) or (use_second_filter_category and second_filter_category_field not in headers):
                raise ValueError("Selected fields not found in the header row.")

            layer_name_col = headers[layer_name_field]
            source_path_col = headers[source_path_field]
            filter_category_col = headers[filter_category_field] if use_filter_category else None
            second_filter_category_col = headers[second_filter_category_field] if use_second_filter_category else None

            # Extract data from the selected sheet
            reference_data = {}
            for row in sheet.iter_rows(min_row=header_row + 1, max_row=sheet.max_row):
                layer_name = row[layer_name_col].value
                source_path = row[source_path_col].value
                category = row[filter_category_col].value if use_filter_category else None
                second_category = row[second_filter_category_col].value if use_second_filter_category else None
                if layer_name and source_path and (
                    (not use_filter_category or (category and str(category) in selected_categories)) and
                    (not use_second_filter_category or (second_category and str(second_category) in second_selected_categories))
                ):
                    normalized_layer_name = self.normalize_path(layer_name, case_sensitive_matching)
                    normalized_source_path = self.normalize_path(source_path, case_sensitive_matching)
                    if normalized_layer_name not in reference_data:
                        reference_data[normalized_layer_name] = []
                    reference_data[normalized_layer_name].append((normalized_source_path, category, second_category))

            self.log_message(f"Reference data extracted: {reference_data}")

            # Collect validation details
            from datetime import datetime
            import getpass
            report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            report_user = getpass.getuser()
            qgis_project_path = QgsProject.instance().fileName()
            validation_excel_date_modified = datetime.fromtimestamp(os.path.getmtime(excel_file)).strftime("%Y-%m-%d %H:%M:%S")
            validation_filter_categories1 = ";".join(selected_categories)
            validation_filter_categories2 = ";".join(second_selected_categories)

            # Initialize summary counters
            matched_count = 0
            wrong_source_count = 0
            layer_name_not_found_count = 0
            total_count = 0

            # Open the report file for writing
            with open(report_path, "w", encoding="utf-8") as report_file:
                # Write the #VALIDATIONDETAILS# section
                report_file.write("#VALIDATIONDETAILS#\n")
                report_file.write(f"ReportDate={report_date}\n")
                report_file.write(f"ReportUser={report_user}\n")
                report_file.write(f"QGISprojectPath={qgis_project_path}\n")
                report_file.write(f"ValidationExcelFilePath={excel_file}\n")
                report_file.write(f"ValidationExcelSheet={sheet_name}\n")
                report_file.write(f"ValidationExcelDateModified={validation_excel_date_modified}\n")
                report_file.write(f"ValidationLayerNameField={layer_name_field}\n")
                report_file.write(f"ValidationSourceField={source_path_field}\n")
                report_file.write(f"ValidationFilterCatergories1={validation_filter_categories1}\n")
                report_file.write(f"ValidationFilterCatergories2={validation_filter_categories2}\n\n")

                # Write the #DATASOURCECHECK# section header
                report_file.write("#DATASOURCECHECK#\n")
                report_file.write("LayerName,CheckResult,LayerSource,ReferenceSource,FilterCategory,SecondFilterCategory\n")

                # Validate against project layers
                project_layers = QgsProject.instance().mapLayers()
                for layer_id, layer in project_layers.items():
                    layer_name = layer.name()
                    layer_source = layer.dataProvider().dataSourceUri()

                    # Normalize the layer name and source for comparison
                    normalized_layer_name = self.normalize_path(layer_name, case_sensitive_matching)
                    if layer_name_delimiter in normalized_layer_name:
                        normalized_layer_name = normalized_layer_name.split(layer_name_delimiter, 1)[0]
                        #DEBUG log the change to the layer name her for validation
                        self.log_message(f"Layer name '{layer_name}' normalized to '{normalized_layer_name}' using delimiter '{layer_name_delimiter}'")
                    normalized_layer_source = self.normalize_path(layer_source, case_sensitive_matching)

                    if normalized_layer_name in reference_data:
                        reference_sources = reference_data[normalized_layer_name]
                        for reference_source, category, second_category in reference_sources:
                            if normalized_layer_source == reference_source:
                                check_result = "MATCHED"
                                matched_count += 1
                                break
                        else:
                            reference_source, category, second_category = reference_sources[0]
                            check_result = "WRONGSOURCE"
                            wrong_source_count += 1
                    else:
                        reference_source = ""
                        category = ""
                        second_category = ""
                        check_result = "LAYERNAMENOTFOUND"
                        layer_name_not_found_count += 1

                    # Skip blank lines
                    if not layer_name or not check_result or not normalized_layer_source:
                        self.log_message(f"Skipping blank line for layer '{layer_name}'")
                        continue

                    # Increment total count
                    total_count += 1

                    # Write the validation result to the report
                    report_file.write(f"{layer_name},{check_result},{normalized_layer_source},{reference_source},{category},{second_category}\n")

                    self.log_message(f"Layer '{layer_name}' checked: {check_result}")

                # Write the #VALIDATIONSUMMARY# section
                report_file.write("\n#VALIDATIONSUMMARY#\n")
                report_file.write(f"DATASOURCES_MATCHED={matched_count}\n")
                report_file.write(f"DATASOURCES_WRONGSOURCE={wrong_source_count}\n")
                report_file.write(f"DATASOURCES_LAYERNAMENOTFOUND={layer_name_not_found_count}\n")
                report_file.write(f"DATASOURCES_TOTAL={total_count}\n")

                # Log the summary to the console
                self.log_message("\nValidation Summary:")
                self.log_message(f"DATASOURCES_MATCHED={matched_count}")
                self.log_message(f"DATASOURCES_WRONGSOURCE={wrong_source_count}")
                self.log_message(f"DATASOURCES_LAYERNAMENOTFOUND={layer_name_not_found_count}")
                self.log_message(f"DATASOURCES_TOTAL={total_count}")

            # Log the clickable link to the report
            self.log_message_link("Validation report written to:", report_path)

            QMessageBox.information(self, "Validation Complete", "Validation report generated successfully.")
        except Exception as e:
            # Capture the traceback details
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Error", f"Validation failed: {e}\n\nDetails:\n{tb}")
            self.log_message(f"Validation failed: {e}\nTraceback:\n{tb}")

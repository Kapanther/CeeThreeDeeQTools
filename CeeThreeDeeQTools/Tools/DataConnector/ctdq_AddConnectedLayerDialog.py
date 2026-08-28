"""
***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""

from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QRadioButton,
    QButtonGroup,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QComboBox,
    QLabel,
    QDialogButtonBox,
    QFileDialog,
    QMessageBox,
    QApplication,
    QWidget,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsCoordinateReferenceSystem, QgsMapLayer, QgsWkbTypes
from qgis.gui import QgsProjectionSelectionWidget

import os

from .ctdq_DataConnectorLogic import DataConnectorLogic
from .ctdq_DataConnectorSources import (
    DataConnectorSources,
    ServiceDiscoveryError,
    SERVICE_WFS,
    SERVICE_ARCGIS,
)
from .ctdq_ExtentWidget import (
    ExtentSelectionWidget,
    EXTENT_MODE_CANVAS,
    EXTENT_MODE_LAYER,
    EXTENT_MODE_MASK,
)
from .ctdq_DataConnectorExtract import (
    FORMAT_GPKG,
    FORMAT_SHP,
    MODE_COMBINED,
    MODE_SEPARATE,
    MODE_SINGLE_FILE,
    MODE_FOLDER,
)


class AddConnectedLayerDialog(QDialog):
    """Dialog to pick a streamed data source and the extraction settings for it."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface

        self.setWindowTitle("Add New Connected Layer")
        self.setMinimumWidth(560)

        self.init_ui()
        self.populate_streamed_layers()
        self.on_source_mode_changed()
        self.on_crs_mode_changed()
        self.on_output_mode_changed()

    # ------------------------------------------------------------------ UI

    def init_ui(self):
        layout = QVBoxLayout()

        layout.addWidget(self._build_source_group())
        self.extent_widget = ExtentSelectionWidget("Extent", self)
        layout.addWidget(self.extent_widget)
        layout.addWidget(self._build_crs_group())
        layout.addWidget(self._build_output_group())

        self.replace_layer_checkbox = QCheckBox("Replace layer with extracted")
        self.replace_layer_checkbox.setToolTip(
            "Remove the streamed layer from the project and replace it with the "
            "extracted geopackage layer."
        )
        layout.addWidget(self.replace_layer_checkbox)

        layout.addStretch()

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.setLayout(layout)

    def _build_source_group(self):
        group = QGroupBox("Streamed Layers")
        group_layout = QVBoxLayout()

        self.source_mode_group = QButtonGroup(self)
        self.use_project_layers_radio = QRadioButton("Use streamed layers in project")
        self.use_project_layers_radio.setChecked(True)
        self.use_url_radio = QRadioButton("Use source URL")
        self.source_mode_group.addButton(self.use_project_layers_radio)
        self.source_mode_group.addButton(self.use_url_radio)
        self.use_project_layers_radio.toggled.connect(self.on_source_mode_changed)

        mode_row = QHBoxLayout()
        mode_row.addWidget(self.use_project_layers_radio)
        mode_row.addWidget(self.use_url_radio)
        mode_row.addStretch()
        group_layout.addLayout(mode_row)

        group_layout.addWidget(self._build_project_layers_panel())
        group_layout.addWidget(self._build_url_panel())

        self.connection_status_label = QLabel("")
        self.connection_status_label.setWordWrap(True)
        group_layout.addWidget(self.connection_status_label)

        group.setLayout(group_layout)
        return group

    def _build_project_layers_panel(self):
        self.project_layers_panel = QWidget()
        panel_layout = QVBoxLayout()
        panel_layout.setContentsMargins(0, 0, 0, 0)

        self.streamed_layer_list = QListWidget()
        self.streamed_layer_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.streamed_layer_list.setMinimumHeight(150)
        panel_layout.addWidget(self.streamed_layer_list)

        self.project_layers_panel.setLayout(panel_layout)
        return self.project_layers_panel

    def _build_url_panel(self):
        self.url_panel = QWidget()
        panel_layout = QVBoxLayout()
        panel_layout.setContentsMargins(0, 0, 0, 0)

        url_row = QHBoxLayout()
        self.service_type_combo = QComboBox()
        self.service_type_combo.addItem("Auto detect", '')
        self.service_type_combo.addItem("WFS", SERVICE_WFS)
        self.service_type_combo.addItem("ArcGIS REST", SERVICE_ARCGIS)
        self.source_url_edit = QLineEdit()
        self.source_url_edit.setPlaceholderText(
            "https://example.com/geoserver/wfs  or  .../FeatureServer"
        )
        self.test_connection_button = QPushButton("Test Connection")
        self.test_connection_button.clicked.connect(self.on_test_connection)
        url_row.addWidget(self.service_type_combo)
        url_row.addWidget(self.source_url_edit, 1)
        url_row.addWidget(self.test_connection_button)
        panel_layout.addLayout(url_row)

        self.url_layer_list = QListWidget()
        self.url_layer_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.url_layer_list.setMinimumHeight(150)
        panel_layout.addWidget(self.url_layer_list)

        self.url_panel.setLayout(panel_layout)
        return self.url_panel

    def _build_crs_group(self):
        group = QGroupBox("Target CRS")
        group_layout = QVBoxLayout()

        self.crs_mode_group = QButtonGroup(self)
        project_crs = QgsProject.instance().crs()
        self.crs_project_radio = QRadioButton(
            f"Use Project CRS ({project_crs.authid() or 'not set'})"
        )
        self.crs_project_radio.setChecked(True)
        self.crs_custom_radio = QRadioButton("Use CRS")
        self.crs_mode_group.addButton(self.crs_project_radio)
        self.crs_mode_group.addButton(self.crs_custom_radio)
        self.crs_project_radio.toggled.connect(self.on_crs_mode_changed)

        group_layout.addWidget(self.crs_project_radio)

        crs_row = QHBoxLayout()
        crs_row.addWidget(self.crs_custom_radio)
        self.crs_selector = QgsProjectionSelectionWidget()
        self.crs_selector.setCrs(project_crs)
        crs_row.addWidget(self.crs_selector, 1)
        group_layout.addLayout(crs_row)

        group.setLayout(group_layout)
        return group

    def _build_output_group(self):
        group = QGroupBox("Output Location")
        group_layout = QVBoxLayout()

        self.output_format_group = QButtonGroup(self)
        self.output_gpkg_radio = QRadioButton("GeoPackage")
        self.output_gpkg_radio.setChecked(True)
        self.output_shp_radio = QRadioButton("Shapefile")
        self.output_format_group.addButton(self.output_gpkg_radio)
        self.output_format_group.addButton(self.output_shp_radio)

        format_row = QHBoxLayout()
        format_row.addWidget(self.output_gpkg_radio)
        format_row.addWidget(self.output_shp_radio)
        format_row.addStretch()
        group_layout.addLayout(format_row)

        self.output_mode_group = QButtonGroup(self)
        self.gpkg_combined_radio = QRadioButton("Combined GeoPackage (use layer name)")
        self.gpkg_combined_radio.setChecked(True)
        self.gpkg_separate_radio = QRadioButton("Separate GeoPackage per layer")
        self.shp_single_radio = QRadioButton("Single Shapefile")
        self.shp_folder_radio = QRadioButton("Folder (one shapefile per layer)")
        for radio in (
            self.gpkg_combined_radio, self.gpkg_separate_radio,
            self.shp_single_radio, self.shp_folder_radio,
        ):
            self.output_mode_group.addButton(radio)
            group_layout.addWidget(radio)

        for radio in (
            self.output_gpkg_radio, self.output_shp_radio,
            self.gpkg_combined_radio, self.gpkg_separate_radio,
            self.shp_single_radio, self.shp_folder_radio,
        ):
            radio.toggled.connect(self.on_output_mode_changed)

        path_row = QHBoxLayout()
        self.output_path_edit = QLineEdit()
        self.browse_output_button = QPushButton("Browse...")
        self.browse_output_button.clicked.connect(self.on_browse_output)
        path_row.addWidget(self.output_path_edit)
        path_row.addWidget(self.browse_output_button)
        group_layout.addLayout(path_row)

        self.output_path_edit.setText(self._default_output_path())

        group.setLayout(group_layout)
        return group

    def _default_output_path(self) -> str:
        """Project folder + project name, as a GeoPackage."""
        project = QgsProject.instance()
        project_file = project.fileName()

        if project_file:
            folder = os.path.dirname(project_file)
            base_name = os.path.splitext(os.path.basename(project_file))[0]
        else:
            folder = os.path.expanduser('~')
            base_name = 'untitled'

        return os.path.join(folder, f"{base_name}.gpkg")

    # -------------------------------------------------------------- populate

    def populate_streamed_layers(self):
        """Fill the list with WFS/REST layers currently loaded in the project."""
        self.streamed_layer_list.clear()

        for layer in DataConnectorLogic.get_streamed_layers():
            service = DataConnectorLogic.service_name_for_provider(layer.dataProvider().name())
            geom = DataConnectorLogic.geometry_type_label(layer)
            item = QListWidgetItem(f"{layer.name()}  [{service} · {geom}]")
            item.setData(Qt.ItemDataRole.UserRole, layer.id())
            self.streamed_layer_list.addItem(item)

        if self.streamed_layer_list.count() == 0:
            placeholder = QListWidgetItem("No streamed (WFS/REST) layers found in project")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.streamed_layer_list.addItem(placeholder)

    # --------------------------------------------------------------- signals

    def on_source_mode_changed(self):
        use_project_layers = self.use_project_layers_radio.isChecked()
        self.project_layers_panel.setVisible(use_project_layers)
        self.url_panel.setVisible(not use_project_layers)
        self.connection_status_label.setVisible(not use_project_layers)
        self.adjustSize()

    def on_crs_mode_changed(self):
        self.crs_selector.setEnabled(self.crs_custom_radio.isChecked())

    def on_output_mode_changed(self):
        """Show only the sub-modes valid for the chosen format and retarget the path."""
        is_gpkg = self.output_gpkg_radio.isChecked()
        self.gpkg_combined_radio.setVisible(is_gpkg)
        self.gpkg_separate_radio.setVisible(is_gpkg)
        self.shp_single_radio.setVisible(not is_gpkg)
        self.shp_folder_radio.setVisible(not is_gpkg)

        # Keep a valid sub-mode selected when the format flips
        if is_gpkg and not (self.gpkg_combined_radio.isChecked() or self.gpkg_separate_radio.isChecked()):
            self.gpkg_combined_radio.setChecked(True)
        if not is_gpkg and not (self.shp_single_radio.isChecked() or self.shp_folder_radio.isChecked()):
            self.shp_folder_radio.setChecked(True)

        self._retarget_output_path()

    def _retarget_output_path(self):
        """Swap the path between a file and a folder to match the current mode."""
        current = self.output_path_edit.text().strip()
        if not current:
            current = self._default_output_path()

        wants_folder = self.gpkg_separate_radio.isChecked() or self.shp_folder_radio.isChecked()
        has_extension = os.path.splitext(current)[1] != ''

        if wants_folder and has_extension:
            self.output_path_edit.setText(os.path.dirname(current))
        elif not wants_folder:
            extension = '.gpkg' if self.output_gpkg_radio.isChecked() else '.shp'
            if not has_extension:
                base = os.path.basename(self._default_output_path())
                base = os.path.splitext(base)[0]
                self.output_path_edit.setText(os.path.join(current, base + extension))
            elif not current.lower().endswith(extension):
                self.output_path_edit.setText(os.path.splitext(current)[0] + extension)

    def on_browse_output(self):
        """Open a file or directory picker appropriate to the current output mode."""
        current = self.output_path_edit.text().strip() or self._default_output_path()

        if self.gpkg_separate_radio.isChecked() or self.shp_folder_radio.isChecked():
            start = current if os.path.isdir(current) else os.path.dirname(current)
            chosen = QFileDialog.getExistingDirectory(self, "Select Output Folder", start)
        elif self.output_gpkg_radio.isChecked():
            chosen, _ = QFileDialog.getSaveFileName(
                self, "Select Output GeoPackage", current, "GeoPackage (*.gpkg)"
            )
        else:
            chosen, _ = QFileDialog.getSaveFileName(
                self, "Select Output Shapefile", current, "Shapefile (*.shp)"
            )

        if chosen:
            self.output_path_edit.setText(chosen)

    def on_test_connection(self):
        """Query the endpoint and list the layers it publishes."""
        url = self.source_url_edit.text().strip()
        if not url:
            self.connection_status_label.setText("Enter a source URL to test.")
            return

        self.url_layer_list.clear()
        self.connection_status_label.setText("Connecting...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        try:
            descriptors = DataConnectorSources.discover_layers(
                url, self.service_type_combo.currentData() or None
            )
        except ServiceDiscoveryError as exc:
            self.connection_status_label.setText(f"Connection failed: {exc}")
            return
        except Exception as exc:
            self.connection_status_label.setText(f"Connection failed: {exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()

        for descriptor in descriptors:
            item = QListWidgetItem(descriptor['title'])
            item.setData(Qt.ItemDataRole.UserRole, descriptor)
            self.url_layer_list.addItem(item)

        self.connection_status_label.setText(
            f"Connected. Found {len(descriptors)} layer(s) - select the ones to extract."
        )

    # ---------------------------------------------------------------- getters

    def get_source_mode(self) -> str:
        """Return 'project_layers' or 'url'."""
        return 'project_layers' if self.use_project_layers_radio.isChecked() else 'url'

    def get_selected_layer_ids(self) -> list:
        """Layer ids selected in the streamed layer list."""
        ids = []
        for item in self.streamed_layer_list.selectedItems():
            layer_id = item.data(Qt.ItemDataRole.UserRole)
            if layer_id:
                ids.append(layer_id)
        return ids

    def get_source_url(self) -> str:
        return self.source_url_edit.text().strip()

    def get_replace_layer(self) -> bool:
        return self.replace_layer_checkbox.isChecked()

    def get_extent_mode(self) -> str:
        return self.extent_widget.get_mode()

    def get_extent_layer_id(self) -> str:
        return self.extent_widget.get_extent_layer_id()

    def get_mask_layer_id(self) -> str:
        return self.extent_widget.get_mask_layer_id()

    def get_target_crs(self) -> QgsCoordinateReferenceSystem:
        if self.crs_custom_radio.isChecked():
            return self.crs_selector.crs()
        return QgsProject.instance().crs()

    def get_output_format(self) -> str:
        return FORMAT_GPKG if self.output_gpkg_radio.isChecked() else FORMAT_SHP

    def get_output_mode(self) -> str:
        if self.output_gpkg_radio.isChecked():
            return MODE_COMBINED if self.gpkg_combined_radio.isChecked() else MODE_SEPARATE
        return MODE_SINGLE_FILE if self.shp_single_radio.isChecked() else MODE_FOLDER

    def get_output_path(self) -> str:
        return self.output_path_edit.text().strip()

    def get_selected_layers(self) -> list:
        """Resolve the current selection into streamed layer objects."""
        if self.get_source_mode() == 'url':
            return self._build_url_layers()

        project = QgsProject.instance()
        layers = [project.mapLayer(layer_id) for layer_id in self.get_selected_layer_ids()]
        return [layer for layer in layers if layer is not None]

    def get_selected_url_descriptors(self) -> list:
        """Discovery descriptors selected in the URL layer list."""
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.url_layer_list.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole)
        ]

    def _build_url_layers(self) -> list:
        """Open the selected service layers, skipping any that fail to load."""
        target_crs = self.get_target_crs()
        crs_authid = target_crs.authid() if target_crs.isValid() else ''

        layers = []
        failures = []
        for descriptor in self.get_selected_url_descriptors():
            try:
                layers.append(DataConnectorSources.build_layer(descriptor, crs_authid))
            except ServiceDiscoveryError as exc:
                failures.append(str(exc))

        if failures:
            QMessageBox.warning(
                self, "Add New Connected Layer", "\n".join(failures)
            )
        return layers

    def get_extent_layer(self):
        return self.extent_widget.get_extent_layer()

    def get_mask_layer(self):
        return self.extent_widget.get_mask_layer()

    # ------------------------------------------------------------ validation

    def accept(self):
        error = self._validate()
        if error:
            QMessageBox.warning(self, "Add New Connected Layer", error)
            return
        super().accept()

    def _validate(self) -> str:
        """Return an error message, or empty string when the dialog is valid."""
        selection_count = self._selection_count()

        if self.get_source_mode() == 'project_layers':
            if not selection_count:
                return "Select at least one streamed layer."
        elif not self.get_source_url():
            return "Enter a source URL."
        elif not selection_count:
            return "Test the connection and select at least one layer to extract."

        extent_error = self.extent_widget.validate()
        if extent_error:
            return extent_error

        if not self.get_target_crs().isValid():
            return "Select a valid target CRS."

        path = self.get_output_path()
        if not path:
            return "Choose an output location."

        wants_folder = self.get_output_mode() in (MODE_SEPARATE, MODE_FOLDER)
        if wants_folder and not os.path.isdir(path):
            return f"Output folder does not exist:\n{path}"
        if not wants_folder and not os.path.isdir(os.path.dirname(path) or '.'):
            return f"Output folder does not exist:\n{os.path.dirname(path)}"

        if (self.get_output_mode() == MODE_SINGLE_FILE
                and selection_count > 1):
            return (
                "A single shapefile can only hold one layer.\n"
                "Choose 'Folder (one shapefile per layer)' instead."
            )

        return ''

    def _selection_count(self) -> int:
        """How many source layers are selected in the active source mode."""
        if self.get_source_mode() == 'url':
            return len(self.url_layer_list.selectedItems())
        return len(self.get_selected_layer_ids())

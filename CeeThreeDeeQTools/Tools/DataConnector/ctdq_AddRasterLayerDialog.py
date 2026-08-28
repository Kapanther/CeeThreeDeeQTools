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

import os

from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QRadioButton,
    QButtonGroup,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QLabel,
    QSpinBox,
    QDialogButtonBox,
    QFileDialog,
    QMessageBox,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsCoordinateReferenceSystem
from qgis.gui import QgsProjectionSelectionWidget

from .ctdq_DataConnectorLogic import DataConnectorLogic
from .ctdq_ExtentWidget import ExtentSelectionWidget
from .ctdq_RasterTileMath import RasterTileMath, MAX_ZOOM, TILE_WARNING_THRESHOLD
from .ctdq_DataConnectorRasterExtract import RASTER_FORMAT_GPKG, RASTER_FORMAT_GTIFF

RESOLUTION_CURRENT = 'current'
RESOLUTION_ZOOM = 'zoom'
RESOLUTION_SCALE = 'scale'


class AddRasterLayerDialog(QDialog):
    """Pick one streamed raster service and the resolution/extent to extract it at."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface

        self.setWindowTitle("Add New Raster Layers")
        self.setMinimumWidth(560)

        self.canvas_zoom = RasterTileMath.canvas_zoom(iface.mapCanvas())

        self.init_ui()
        self.populate_raster_layers()
        self.on_resolution_mode_changed()
        self.update_estimate()

    # ------------------------------------------------------------------ UI

    def init_ui(self):
        layout = QVBoxLayout()

        layout.addWidget(self._build_source_group())

        self.extent_widget = ExtentSelectionWidget("Extent", self)
        for radio in (
            self.extent_widget.canvas_radio,
            self.extent_widget.layer_radio,
            self.extent_widget.mask_radio,
        ):
            radio.toggled.connect(self.update_estimate)
        self.extent_widget.extent_layer_combo.currentIndexChanged.connect(self.update_estimate)
        self.extent_widget.mask_layer_combo.currentIndexChanged.connect(self.update_estimate)
        layout.addWidget(self.extent_widget)

        layout.addWidget(self._build_resolution_group())
        layout.addWidget(self._build_crs_group())
        layout.addWidget(self._build_output_group())

        self.replace_layer_checkbox = QCheckBox("Replace Layer with extracted")
        layout.addWidget(self.replace_layer_checkbox)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.setLayout(layout)

    def _build_source_group(self):
        group = QGroupBox("Streamed Raster Layers")
        group_layout = QVBoxLayout()

        self.raster_layer_list = QListWidget()
        # One raster at a time - tiled downloads are slow and memory hungry.
        self.raster_layer_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.raster_layer_list.setMinimumHeight(120)
        group_layout.addWidget(self.raster_layer_list)

        group.setLayout(group_layout)
        return group

    def _build_resolution_group(self):
        group = QGroupBox("Raster Resolution")
        group_layout = QVBoxLayout()

        self.resolution_mode_group = QButtonGroup(self)
        self.current_zoom_radio = QRadioButton(
            f"Use Current Zoom Level (currently {self.canvas_zoom})"
        )
        self.current_zoom_radio.setChecked(True)
        self.specify_zoom_radio = QRadioButton("Specify Zoom Level")
        self.specify_scale_radio = QRadioButton("Specify Scale  1:")
        for radio in (self.current_zoom_radio, self.specify_zoom_radio, self.specify_scale_radio):
            self.resolution_mode_group.addButton(radio)
            radio.toggled.connect(self.on_resolution_mode_changed)

        group_layout.addWidget(self.current_zoom_radio)

        zoom_row = QHBoxLayout()
        zoom_row.addWidget(self.specify_zoom_radio)
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(0, MAX_ZOOM)
        self.zoom_spin.setValue(self.canvas_zoom)
        self.zoom_spin.valueChanged.connect(self.update_estimate)
        zoom_row.addWidget(self.zoom_spin)
        zoom_row.addStretch()
        group_layout.addLayout(zoom_row)

        scale_row = QHBoxLayout()
        scale_row.addWidget(self.specify_scale_radio)
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(1, 100000000)
        self.scale_spin.setGroupSeparatorShown(True)
        self.scale_spin.setValue(int(RasterTileMath.scale_for_zoom(self.canvas_zoom)))
        self.scale_spin.valueChanged.connect(self.update_estimate)
        scale_row.addWidget(self.scale_spin)
        scale_row.addStretch()
        group_layout.addLayout(scale_row)

        self.estimate_label = QLabel("")
        self.estimate_label.setWordWrap(True)
        group_layout.addWidget(self.estimate_label)

        group.setLayout(group_layout)
        return group

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
        self.crs_selector.setEnabled(False)
        crs_row.addWidget(self.crs_selector, 1)
        group_layout.addLayout(crs_row)

        group.setLayout(group_layout)
        return group

    def _build_output_group(self):
        group = QGroupBox("Output Location")
        group_layout = QVBoxLayout()

        self.output_format_group = QButtonGroup(self)
        self.output_gpkg_radio = QRadioButton("GeoPackage (tiled, with zoom levels)")
        self.output_gpkg_radio.setChecked(True)
        self.output_gtiff_radio = QRadioButton("GeoTIFF")
        self.output_format_group.addButton(self.output_gpkg_radio)
        self.output_format_group.addButton(self.output_gtiff_radio)
        self.output_gpkg_radio.toggled.connect(self.on_output_format_changed)

        format_row = QHBoxLayout()
        format_row.addWidget(self.output_gpkg_radio)
        format_row.addWidget(self.output_gtiff_radio)
        format_row.addStretch()
        group_layout.addLayout(format_row)

        path_row = QHBoxLayout()
        self.output_path_edit = QLineEdit(self._default_output_path())
        self.browse_output_button = QPushButton("Browse...")
        self.browse_output_button.clicked.connect(self.on_browse_output)
        path_row.addWidget(self.output_path_edit)
        path_row.addWidget(self.browse_output_button)
        group_layout.addLayout(path_row)

        group.setLayout(group_layout)
        return group

    def _default_output_path(self) -> str:
        project_file = QgsProject.instance().fileName()
        if project_file:
            folder = os.path.dirname(project_file)
            base_name = os.path.splitext(os.path.basename(project_file))[0]
        else:
            folder = os.path.expanduser('~')
            base_name = 'untitled'
        return os.path.join(folder, f"{base_name}_raster.gpkg")

    # -------------------------------------------------------------- populate

    def populate_raster_layers(self):
        self.raster_layer_list.clear()

        for layer in DataConnectorLogic.get_streamed_raster_layers():
            service = DataConnectorLogic.service_name_for_provider(layer.dataProvider().name())
            item = QListWidgetItem(f"{layer.name()}  [{service}]")
            item.setData(Qt.ItemDataRole.UserRole, layer.id())
            self.raster_layer_list.addItem(item)

        if self.raster_layer_list.count() == 0:
            placeholder = QListWidgetItem("No streamed raster layers found in project")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.raster_layer_list.addItem(placeholder)

    # --------------------------------------------------------------- signals

    def on_resolution_mode_changed(self):
        self.zoom_spin.setEnabled(self.specify_zoom_radio.isChecked())
        self.scale_spin.setEnabled(self.specify_scale_radio.isChecked())
        self.update_estimate()

    def on_crs_mode_changed(self):
        self.crs_selector.setEnabled(self.crs_custom_radio.isChecked())

    def on_output_format_changed(self):
        current = self.output_path_edit.text().strip() or self._default_output_path()
        extension = '.gpkg' if self.output_gpkg_radio.isChecked() else '.tif'
        if not current.lower().endswith(extension):
            self.output_path_edit.setText(os.path.splitext(current)[0] + extension)

    def on_browse_output(self):
        current = self.output_path_edit.text().strip() or self._default_output_path()
        if self.output_gpkg_radio.isChecked():
            chosen, _ = QFileDialog.getSaveFileName(
                self, "Select Output GeoPackage", current, "GeoPackage (*.gpkg)"
            )
        else:
            chosen, _ = QFileDialog.getSaveFileName(
                self, "Select Output GeoTIFF", current, "GeoTIFF (*.tif)"
            )
        if chosen:
            self.output_path_edit.setText(chosen)

    def update_estimate(self):
        """Recalculate the tile/pixel estimate and warn when the download looks large."""
        extent = self._current_extent()
        if extent is None:
            self.estimate_label.setText("Select an extent to estimate the download size.")
            return

        rectangle, crs = extent
        zoom = self.get_zoom()
        estimate = RasterTileMath.estimate(rectangle, crs, zoom)

        text = (
            f"Zoom level {zoom} · approx {estimate['tiles']} tile(s) · "
            f"{estimate['width']} x {estimate['height']} px · "
            f"{estimate['resolution']:.2f} m/px"
        )

        if estimate['tiles'] > TILE_WARNING_THRESHOLD:
            self.estimate_label.setStyleSheet("color: #b45309;")
            text += (
                f"\n⚠ More than {TILE_WARNING_THRESHOLD} tiles - this extraction may be "
                "slow and some services may throttle or reject the request."
            )
        else:
            self.estimate_label.setStyleSheet("")

        self.estimate_label.setText(text)

    def _current_extent(self):
        """Resolve the chosen extent into (QgsRectangle, crs), or None when unavailable."""
        mode = self.extent_widget.get_mode()

        if mode == 'layer':
            layer = self.extent_widget.get_extent_layer()
            return (layer.extent(), layer.crs()) if layer else None

        if mode == 'mask':
            layer = self.extent_widget.get_mask_layer()
            return (layer.extent(), layer.crs()) if layer else None

        canvas = self.iface.mapCanvas()
        return canvas.extent(), canvas.mapSettings().destinationCrs()

    # ---------------------------------------------------------------- getters

    def get_selected_layer(self):
        items = self.raster_layer_list.selectedItems()
        if not items:
            return None
        layer_id = items[0].data(Qt.ItemDataRole.UserRole)
        return QgsProject.instance().mapLayer(layer_id) if layer_id else None

    def get_resolution_mode(self) -> str:
        if self.specify_zoom_radio.isChecked():
            return RESOLUTION_ZOOM
        if self.specify_scale_radio.isChecked():
            return RESOLUTION_SCALE
        return RESOLUTION_CURRENT

    def get_zoom(self) -> int:
        mode = self.get_resolution_mode()
        if mode == RESOLUTION_ZOOM:
            return self.zoom_spin.value()
        if mode == RESOLUTION_SCALE:
            return RasterTileMath.zoom_for_scale(float(self.scale_spin.value()))
        return self.canvas_zoom

    def get_target_crs(self) -> QgsCoordinateReferenceSystem:
        if self.crs_custom_radio.isChecked():
            return self.crs_selector.crs()
        return QgsProject.instance().crs()

    def get_output_format(self) -> str:
        return RASTER_FORMAT_GPKG if self.output_gpkg_radio.isChecked() else RASTER_FORMAT_GTIFF

    def get_output_path(self) -> str:
        return self.output_path_edit.text().strip()

    def get_replace_layer(self) -> bool:
        return self.replace_layer_checkbox.isChecked()

    def get_extent_mode(self) -> str:
        return self.extent_widget.get_mode()

    def get_extent_layer(self):
        return self.extent_widget.get_extent_layer()

    def get_mask_layer(self):
        return self.extent_widget.get_mask_layer()

    # ------------------------------------------------------------ validation

    def accept(self):
        error = self._validate()
        if error:
            QMessageBox.warning(self, "Add New Raster Layers", error)
            return

        if not self._confirm_large_download():
            return

        super().accept()

    def _validate(self) -> str:
        if self.get_selected_layer() is None:
            return "Select a streamed raster layer."

        extent_error = self.extent_widget.validate()
        if extent_error:
            return extent_error

        if not self.get_target_crs().isValid():
            return "Select a valid target CRS."

        path = self.get_output_path()
        if not path:
            return "Choose an output location."
        if not os.path.isdir(os.path.dirname(path) or '.'):
            return f"Output folder does not exist:\n{os.path.dirname(path)}"

        return ''

    def _confirm_large_download(self) -> bool:
        extent = self._current_extent()
        if extent is None:
            return True

        estimate = RasterTileMath.estimate(extent[0], extent[1], self.get_zoom())
        if estimate['tiles'] <= TILE_WARNING_THRESHOLD:
            return True

        answer = QMessageBox.question(
            self,
            "Add New Raster Layers",
            f"This extraction needs approximately {estimate['tiles']} tiles "
            f"({estimate['width']} x {estimate['height']} px).\n\n"
            "Large downloads can be slow and some services throttle or reject them.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

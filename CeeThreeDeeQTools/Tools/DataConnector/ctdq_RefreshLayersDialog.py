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
    QLabel,
    QGroupBox,
    QRadioButton,
    QButtonGroup,
    QSpinBox,
    QDialogButtonBox,
    QMessageBox,
)

from .ctdq_ExtentWidget import ExtentSelectionWidget
from .ctdq_RasterTileMath import MAX_ZOOM

EXTENT_SOURCE_PREVIOUS = 'previous'
EXTENT_SOURCE_NEW = 'new'

ZOOM_SOURCE_PREVIOUS = 'previous'
ZOOM_SOURCE_CURRENT = 'current'
ZOOM_SOURCE_SPECIFY = 'specify'


class RefreshLayersDialog(QDialog):
    """Confirms a refresh and lets the user keep or replace the stored extent/zoom."""

    def __init__(self, layer_count, parent=None, title="Refresh Vector Layers",
                 show_zoom=False, canvas_zoom=0):
        super().__init__(parent)

        self.show_zoom = show_zoom
        self.canvas_zoom = canvas_zoom

        self.setWindowTitle(title)
        self.setMinimumWidth(460)

        layout = QVBoxLayout()

        warning = QLabel(
            f"<b>Warning:</b> all {layer_count} connected layer(s) will be re-extracted "
            "from their original data sources.<br><br>"
            "The data currently held in these layers will be <b>replaced</b> and any local "
            "edits will be lost. Styling and connection metadata are preserved."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        layout.addWidget(self._build_extent_source_group())

        self.extent_widget = ExtentSelectionWidget("New Extent", self)
        layout.addWidget(self.extent_widget)

        if show_zoom:
            layout.addWidget(self._build_zoom_group())

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Refresh")
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.setLayout(layout)
        self.on_extent_source_changed()
        if show_zoom:
            self.on_zoom_source_changed()

    def _build_extent_source_group(self):
        group = QGroupBox("Extent")
        group_layout = QVBoxLayout()

        self.extent_source_group = QButtonGroup(self)
        self.previous_extent_radio = QRadioButton("Use Previous Extent")
        self.previous_extent_radio.setChecked(True)
        self.previous_extent_radio.setToolTip(
            "Re-extract using the extent stored against each layer when it was created."
        )
        self.new_extent_radio = QRadioButton("Use New Extent")
        self.extent_source_group.addButton(self.previous_extent_radio)
        self.extent_source_group.addButton(self.new_extent_radio)
        self.previous_extent_radio.toggled.connect(self.on_extent_source_changed)

        group_layout.addWidget(self.previous_extent_radio)
        group_layout.addWidget(self.new_extent_radio)

        group.setLayout(group_layout)
        return group

    def on_extent_source_changed(self):
        self.extent_widget.setEnabled(self.new_extent_radio.isChecked())

    def _build_zoom_group(self):
        group = QGroupBox("Tile Zoom Level")
        group_layout = QVBoxLayout()

        self.zoom_source_group = QButtonGroup(self)
        self.previous_zoom_radio = QRadioButton("Use Previous Zoom Level")
        self.previous_zoom_radio.setChecked(True)
        self.current_zoom_radio = QRadioButton(
            f"Use Current Zoom Level (currently {self.canvas_zoom})"
        )
        self.specify_zoom_radio = QRadioButton("Specify Zoom Level")
        for radio in (self.previous_zoom_radio, self.current_zoom_radio, self.specify_zoom_radio):
            self.zoom_source_group.addButton(radio)
            radio.toggled.connect(self.on_zoom_source_changed)

        group_layout.addWidget(self.previous_zoom_radio)
        group_layout.addWidget(self.current_zoom_radio)

        zoom_row = QHBoxLayout()
        zoom_row.addWidget(self.specify_zoom_radio)
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(0, MAX_ZOOM)
        self.zoom_spin.setValue(self.canvas_zoom)
        zoom_row.addWidget(self.zoom_spin)
        zoom_row.addStretch()
        group_layout.addLayout(zoom_row)

        group.setLayout(group_layout)
        return group

    def on_zoom_source_changed(self):
        self.zoom_spin.setEnabled(self.specify_zoom_radio.isChecked())

    # ---------------------------------------------------------------- getters

    def get_extent_source(self) -> str:
        return EXTENT_SOURCE_NEW if self.new_extent_radio.isChecked() else EXTENT_SOURCE_PREVIOUS

    def get_extent_mode(self) -> str:
        return self.extent_widget.get_mode()

    def get_extent_layer(self):
        return self.extent_widget.get_extent_layer()

    def get_mask_layer(self):
        return self.extent_widget.get_mask_layer()

    def get_zoom_source(self) -> str:
        if not self.show_zoom or self.previous_zoom_radio.isChecked():
            return ZOOM_SOURCE_PREVIOUS
        if self.current_zoom_radio.isChecked():
            return ZOOM_SOURCE_CURRENT
        return ZOOM_SOURCE_SPECIFY

    def get_zoom(self):
        """Zoom level to use, or None when the stored level should be kept."""
        source = self.get_zoom_source()
        if source == ZOOM_SOURCE_CURRENT:
            return self.canvas_zoom
        if source == ZOOM_SOURCE_SPECIFY:
            return self.zoom_spin.value()
        return None

    def accept(self):
        if self.get_extent_source() == EXTENT_SOURCE_NEW:
            error = self.extent_widget.validate()
            if error:
                QMessageBox.warning(self, self.windowTitle(), error)
                return
        super().accept()

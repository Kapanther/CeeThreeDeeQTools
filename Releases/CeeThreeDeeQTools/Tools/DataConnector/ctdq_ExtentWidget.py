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
    QGroupBox,
    QVBoxLayout,
    QHBoxLayout,
    QRadioButton,
    QButtonGroup,
    QComboBox,
)
from qgis.core import QgsProject, QgsMapLayer, QgsWkbTypes

EXTENT_MODE_CANVAS = 'canvas'
EXTENT_MODE_LAYER = 'layer'
EXTENT_MODE_MASK = 'mask'


class ExtentSelectionWidget(QGroupBox):
    """Map canvas / layer extent / mask layer chooser shared by the extract dialogs."""

    def __init__(self, title="Extent", parent=None):
        super().__init__(title, parent)

        layout = QVBoxLayout()

        self.mode_group = QButtonGroup(self)
        self.canvas_radio = QRadioButton("Use Map Canvas")
        self.canvas_radio.setChecked(True)
        self.layer_radio = QRadioButton("Use Layer Extent")
        self.mask_radio = QRadioButton("Use Mask Layer")
        for radio in (self.canvas_radio, self.layer_radio, self.mask_radio):
            self.mode_group.addButton(radio)
            radio.toggled.connect(self._on_mode_changed)

        layout.addWidget(self.canvas_radio)

        layer_row = QHBoxLayout()
        layer_row.addWidget(self.layer_radio)
        self.extent_layer_combo = QComboBox()
        layer_row.addWidget(self.extent_layer_combo, 1)
        layout.addLayout(layer_row)

        mask_row = QHBoxLayout()
        mask_row.addWidget(self.mask_radio)
        self.mask_layer_combo = QComboBox()
        mask_row.addWidget(self.mask_layer_combo, 1)
        layout.addLayout(mask_row)

        self.setLayout(layout)

        self.populate()
        self._on_mode_changed()

    def populate(self):
        """Fill the extent-layer and mask-layer combos from the current project."""
        self.extent_layer_combo.clear()
        self.mask_layer_combo.clear()

        for layer in QgsProject.instance().mapLayers().values():
            if not layer.isValid():
                continue
            self.extent_layer_combo.addItem(layer.name(), layer.id())

            is_polygon = (
                layer.type() == QgsMapLayer.LayerType.VectorLayer
                and layer.geometryType() == QgsWkbTypes.GeometryType.PolygonGeometry
            )
            if is_polygon:
                self.mask_layer_combo.addItem(layer.name(), layer.id())

    def _on_mode_changed(self):
        self.extent_layer_combo.setEnabled(self.layer_radio.isChecked())
        self.mask_layer_combo.setEnabled(self.mask_radio.isChecked())

    # ---------------------------------------------------------------- getters

    def get_mode(self) -> str:
        if self.layer_radio.isChecked():
            return EXTENT_MODE_LAYER
        if self.mask_radio.isChecked():
            return EXTENT_MODE_MASK
        return EXTENT_MODE_CANVAS

    def get_extent_layer_id(self) -> str:
        return self.extent_layer_combo.currentData() or ''

    def get_mask_layer_id(self) -> str:
        return self.mask_layer_combo.currentData() or ''

    def get_extent_layer(self):
        return QgsProject.instance().mapLayer(self.get_extent_layer_id())

    def get_mask_layer(self):
        return QgsProject.instance().mapLayer(self.get_mask_layer_id())

    def validate(self) -> str:
        """Return an error message, or empty string when the selection is usable."""
        if self.get_mode() == EXTENT_MODE_LAYER and not self.get_extent_layer_id():
            return "Select a layer to use for the extent."
        if self.get_mode() == EXTENT_MODE_MASK and not self.get_mask_layer_id():
            return "Select a polygon layer to use as the mask."
        return ''

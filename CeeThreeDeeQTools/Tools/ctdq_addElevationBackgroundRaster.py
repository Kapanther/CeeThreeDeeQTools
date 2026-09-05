# -*- coding: utf-8 -*-
"""Proof-of-concept overlay for section rasters on an elevation profile."""

import json

from qgis.core import QgsMapRendererParallelJob, QgsMapSettings, QgsProject, QgsRasterLayer
from qgis.PyQt.QtCore import QEvent, QSize, Qt
from qgis.PyQt.QtGui import QColor, QImage, QPainter
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from qgis.gui import QgsMapLayerComboBox
from qgis.core import QgsMapLayerProxyModel

PERSISTENCE_SCOPE = "CeeThreeDeeQTools"
PERSISTENCE_KEY = "elevationBackgroundRasters"


class ElevationRasterOverlay(QWidget):
    """Paint a raster image over the plot area of an elevation canvas."""

    def __init__(self, canvas, image, minimum_distance, maximum_distance,
                 minimum_elevation, maximum_elevation):
        super().__init__(canvas)
        self.canvas = canvas
        self.image = image
        self.minimum_distance = minimum_distance
        self.maximum_distance = maximum_distance
        self.minimum_elevation = minimum_elevation
        self.maximum_elevation = maximum_elevation
        self._last_geometry = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.canvas.installEventFilter(self)
        if hasattr(self.canvas, "scaleChanged"):
            self.canvas.scaleChanged.connect(self.reposition)
        self.reposition()
        self.show()

    def eventFilter(self, watched, event):
        if watched is self.canvas and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
        ):
            self.reposition()
        return False

    def reposition(self):
        plot_area = self.canvas.plotArea()
        distance_range = self.canvas.visibleDistanceRange()
        elevation_range = self.canvas.visibleElevationRange()
        distance_span = distance_range.upper() - distance_range.lower()
        elevation_span = elevation_range.upper() - elevation_range.lower()
        if distance_span <= 0 or elevation_span <= 0:
            return

        left = plot_area.left() + (
            (self.minimum_distance - distance_range.lower()) / distance_span
        ) * plot_area.width()
        right = plot_area.left() + (
            (self.maximum_distance - distance_range.lower()) / distance_span
        ) * plot_area.width()
        axis_ratio = getattr(self.canvas, "axisScaleRatio", lambda: 1.0)()
        if axis_ratio <= 0:
            axis_ratio = 1.0
        pixels_per_distance = plot_area.width() / distance_span
        vertical_height = (
            (self.maximum_elevation - self.minimum_elevation)
            * pixels_per_distance / axis_ratio
        )
        bottom = plot_area.bottom() - (
            (self.minimum_elevation - elevation_range.lower()) / elevation_span
        ) * plot_area.height()
        top = bottom - vertical_height
        geometry = (
            round(left),
            round(top),
            max(1, round(right - left)),
            max(1, round(bottom - top)),
        )
        if geometry == self._last_geometry:
            return
        self._last_geometry = geometry
        self.setGeometry(*geometry)
        self.raise_()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setOpacity(0.75)
        painter.drawImage(self.rect(), self.image)
        painter.end()

    def close_overlay(self):
        self.canvas.removeEventFilter(self)
        if getattr(self.canvas, "_ctdq_elevation_background", None) is self:
            del self.canvas._ctdq_elevation_background
        self.deleteLater()


def _profile_key(canvas):
    """Return a stable project-local key based on the profile container name."""
    widget = canvas
    candidates = []
    while widget is not None:
        title = widget.windowTitle().strip()
        object_name = widget.objectName().strip()
        for value in (title, object_name):
            if (
                value
                and value not in candidates
                and value not in (
                    "PlotCanvas",
                    "QgsElevationProfileCanvas",
                    "QgsElevationProfileWidget",
                )
                and "canvas" not in value.lower()
            ):
                candidates.append(value)
        widget = widget.parentWidget()
    return candidates[0] if candidates else "Elevation profile"


def _saved_overlays():
    value, ok = QgsProject.instance().readEntry(
        PERSISTENCE_SCOPE, PERSISTENCE_KEY, "{}"
    )
    if not ok:
        value = "{}"
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return {}


def _save_overlay(canvas, layer, minimum_distance, maximum_distance,
                  minimum_elevation, maximum_elevation):
    overlays = _saved_overlays()
    overlays[_profile_key(canvas)] = {
        "layer_id": layer.id(),
        "minimum_distance": minimum_distance,
        "maximum_distance": maximum_distance,
        "minimum_elevation": minimum_elevation,
        "maximum_elevation": maximum_elevation,
    }
    QgsProject.instance().writeEntry(
        PERSISTENCE_SCOPE, PERSISTENCE_KEY, json.dumps(overlays)
    )


def restore_persistent_overlays(iface):
    """Restore saved overlays onto profile canvases currently in the application."""
    try:
        from qgis.gui import QgsElevationProfileCanvas
    except ImportError:
        return
    overlays = _saved_overlays()
    layers = QgsProject.instance().mapLayers()
    for canvas in iface.mainWindow().findChildren(QgsElevationProfileCanvas):
        saved = overlays.get(_profile_key(canvas))
        if (
            not isinstance(saved, dict)
            or getattr(canvas, "_ctdq_elevation_background", None) is not None
        ):
            continue
        layer = layers.get(saved.get("layer_id"))
        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            continue
        try:
            overlay = ElevationRasterOverlay(
                canvas,
                _raster_image(layer),
                saved["minimum_distance"],
                saved["maximum_distance"],
                saved["minimum_elevation"],
                saved["maximum_elevation"],
            )
            overlay.layer = layer
            canvas._ctdq_elevation_background = overlay
        except (KeyError, RuntimeError, TypeError, ValueError):
            pass


def _raster_image(layer):
    """Render the layer with its current QGIS raster renderer."""
    settings = QgsMapSettings()
    settings.setExtent(layer.extent())
    width = min(1600, max(1, layer.width()))
    height = min(1000, max(1, layer.height()))
    settings.setOutputSize(QSize(width, height))
    settings.setLayers([layer])
    settings.setDestinationCrs(layer.crs())
    settings.setBackgroundColor(QColor(0, 0, 0, 0))
    settings.setTransformContext(QgsProject.instance().transformContext())
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    image = job.renderedImage()
    if image.isNull():
        raise ValueError("The raster could not be rendered.")
    return image


class AddElevationBackgroundRasterDialog(QDialog):
    """Select a georeferenced section raster and place it on an open profile."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Add Elevation Background Raster (POC)")
        self.setMinimumWidth(520)
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(QgsMapLayerProxyModel.RasterLayer)
        active_layer = self.iface.activeLayer()
        if isinstance(active_layer, QgsRasterLayer):
            self.layer_combo.setLayer(active_layer)

        self.profile_combo = QComboBox()
        self.canvases = self._find_canvases()
        for canvas in self.canvases:
            self.profile_combo.addItem(self._canvas_name(canvas), canvas)

        self.minimum_distance = self._number_box()
        self.maximum_distance = self._number_box()
        self.minimum_elevation = self._number_box()
        self.maximum_elevation = self._number_box()
        form = QFormLayout()
        form.addRow("Active raster layer", self.layer_combo)
        form.addRow("Elevation profile", self.profile_combo)
        form.addRow("Minimum distance", self.minimum_distance)
        form.addRow("Maximum distance", self.maximum_distance)
        form.addRow("Minimum elevation", self.minimum_elevation)
        form.addRow("Maximum elevation", self.maximum_elevation)

        note = QLabel("POC: the selected layer is rendered with its current QGIS style and attached to the selected profile.")
        note.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.add_overlay)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.layer_combo.layerChanged.connect(self._set_bounds_from_layer)
        self.profile_combo.currentIndexChanged.connect(self._load_existing_overlay)
        self._set_bounds_from_layer(self.layer_combo.currentLayer())
        self._load_existing_overlay()

    @staticmethod
    def _number_box():
        box = QDoubleSpinBox()
        box.setRange(-1e12, 1e12)
        box.setDecimals(3)
        box.setValue(0)
        return box

    def _set_bounds_from_layer(self, layer):
        if layer is None:
            return
        extent = layer.extent()
        self.minimum_distance.setValue(extent.xMinimum())
        self.maximum_distance.setValue(extent.xMaximum())
        self.minimum_elevation.setValue(extent.yMinimum())
        self.maximum_elevation.setValue(extent.yMaximum())

    def _find_canvases(self):
        try:
            from qgis.gui import QgsElevationProfileCanvas
        except ImportError:
            return []
        return list(self.iface.mainWindow().findChildren(QgsElevationProfileCanvas))

    @staticmethod
    def _canvas_name(canvas):
        return _profile_key(canvas)

    def _selected_canvas(self):
        canvas = self.profile_combo.currentData()
        if canvas is None:
            raise RuntimeError("Open an elevation profile view before running this POC.")
        return canvas

    def _load_existing_overlay(self):
        canvas = self.profile_combo.currentData()
        overlay = getattr(canvas, "_ctdq_elevation_background", None)
        if overlay is not None:
            self.layer_combo.setLayer(overlay.layer)
            self.minimum_distance.setValue(overlay.minimum_distance)
            self.maximum_distance.setValue(overlay.maximum_distance)
            self.minimum_elevation.setValue(overlay.minimum_elevation)
            self.maximum_elevation.setValue(overlay.maximum_elevation)
            return
        saved = _saved_overlays().get(_profile_key(canvas))
        if saved is None:
            return
        layer = QgsProject.instance().mapLayer(saved.get("layer_id"))
        if isinstance(layer, QgsRasterLayer):
            self.layer_combo.setLayer(layer)
        self.minimum_distance.setValue(saved["minimum_distance"])
        self.maximum_distance.setValue(saved["maximum_distance"])
        self.minimum_elevation.setValue(saved["minimum_elevation"])
        self.maximum_elevation.setValue(saved["maximum_elevation"])

    def add_overlay(self):
        layer = self.layer_combo.currentLayer()
        if layer is None or not layer.isValid():
            QMessageBox.warning(self, "No raster selected", "Select a valid raster layer from the active project.")
            return
        if self.maximum_distance.value() <= self.minimum_distance.value() or self.maximum_elevation.value() <= self.minimum_elevation.value():
            QMessageBox.warning(self, "Invalid bounds", "Maximum bounds must be greater than minimum bounds.")
            return
        try:
            canvas = self._selected_canvas()
            image = _raster_image(layer)
        except Exception as error:
            QMessageBox.critical(self, "Elevation profile error", str(error))
            return

        previous = getattr(canvas, "_ctdq_elevation_background", None)
        if previous is not None:
            previous.close_overlay()
        overlay = ElevationRasterOverlay(
            canvas, image, self.minimum_distance.value(), self.maximum_distance.value(),
            self.minimum_elevation.value(), self.maximum_elevation.value()
        )
        overlay.layer = layer
        canvas._ctdq_elevation_background = overlay
        _save_overlay(
            canvas,
            layer,
            self.minimum_distance.value(),
            self.maximum_distance.value(),
            self.minimum_elevation.value(),
            self.maximum_elevation.value(),
        )
        self.accept()


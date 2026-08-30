# -*- coding: utf-8 -*-
"""
Contour generation and styling for imported LandXML surfaces.

Uses the ``native:meshcontours`` processing algorithm on the mesh's elevation
dataset, then applies a rule-based renderer (minor / major) and labels the
major contours from the ``value`` field with a text buffer.
"""

import math
import random

from qgis.core import (
    QgsApplication,
    QgsLineSymbol,
    QgsMapLayer,
    QgsPalLayerSettings,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingUtils,
    QgsRuleBasedLabeling,
    QgsRuleBasedRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
)
from qgis.PyQt.QtGui import QColor

MAJOR_TOLERANCE = 1e-4
ALGORITHM_ID = 'native:meshcontours'


class _CapturingFeedback(QgsProcessingFeedback):
    """Keeps algorithm messages so failures can be reported to the user."""

    def __init__(self):
        super().__init__()
        self.messages = []

    def reportError(self, error, fatalError=False):
        self.messages.append(error)

    def pushWarning(self, warning):
        self.messages.append(warning)

    def pushInfo(self, info):
        self.messages.append(info)

    def summary(self):
        return " | ".join(m for m in self.messages if m) or "no details reported"


class LandXMLContours:
    """Builds and styles contour layers from a mesh layer."""

    @staticmethod
    def generate(mesh_layer, minor_interval, major_interval, target_crs,
                 z_min, z_max, warnings, errors):
        """Return a styled contour line layer, or ``None`` on failure."""
        try:
            import processing
        except ImportError:
            errors.append("Processing framework unavailable; contours skipped.")
            return None

        if QgsApplication.processingRegistry().algorithmById(ALGORITHM_ID) is None:
            errors.append(
                "Algorithm '{0}' is not available in this QGIS build.".format(
                    ALGORITHM_ID))
            return None

        if minor_interval <= 0:
            errors.append("Contour interval must be greater than zero.")
            return None
        if z_min is None or z_max is None or z_max <= z_min:
            errors.append(
                "Surface '{0}' has no elevation range to contour.".format(
                    mesh_layer.name()))
            return None

        # The algorithm needs an explicit level range, not just an increment
        minimum = math.floor(z_min / minor_interval) * minor_interval
        maximum = math.ceil(z_max / minor_interval) * minor_interval

        context = QgsProcessingContext()
        feedback = _CapturingFeedback()
        params = {
            'INPUT': mesh_layer,
            'DATASET_GROUPS': [0],
            'DATASET_TIME': {'type': 'static'},
            'INCREMENT': minor_interval,
            'MINIMUM': minimum,
            'MAXIMUM': maximum,
            'CRS_OUTPUT': target_crs,
            'OUTPUT_LINES': 'TEMPORARY_OUTPUT',
            'OUTPUT_POLYGONS': 'TEMPORARY_OUTPUT',
        }

        try:
            result = processing.run(ALGORITHM_ID, params,
                                    context=context, feedback=feedback)
        except Exception as exc:  # processing raises for any invalid input
            errors.append(
                "Contours for '{0}' failed: {1} (levels {2:g} to {3:g} step "
                "{4:g}). Details: {5}".format(
                    mesh_layer.name(), exc, minimum, maximum, minor_interval,
                    feedback.summary()))
            return None

        layer = LandXMLContours._take_layer(result.get('OUTPUT_LINES'), context)
        if layer is None or not layer.isValid():
            errors.append("Contours for '{0}' produced no layer. Details: {1}".format(
                mesh_layer.name(), feedback.summary()))
            return None

        layer.setName("{0} Contours".format(mesh_layer.name()))
        if layer.featureCount() == 0:
            warnings.append(
                "Contours for '{0}' are empty; check the interval.".format(
                    mesh_layer.name()))

        LandXMLContours._style(layer, major_interval)
        LandXMLContours._label(layer, major_interval)
        return layer

    @staticmethod
    def _take_layer(identifier, context):
        # Newer QGIS returns the layer itself for TEMPORARY_OUTPUT
        if isinstance(identifier, QgsMapLayer):
            return identifier
        if not isinstance(identifier, str) or not identifier:
            return None
        layer = context.takeResultLayer(identifier)
        if layer is not None:
            return layer
        return QgsProcessingUtils.mapLayerFromString(identifier, context)

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------

    @staticmethod
    def _colours():
        """A random light colour plus a darker version of the same hue."""
        hue = random.randint(0, 359)
        minor = QColor.fromHsl(hue, 150, 165)
        major = QColor.fromHsl(hue, 200, 85)
        return minor, major

    @staticmethod
    def _rgba(colour):
        return "{0},{1},{2},255".format(
            colour.red(), colour.green(), colour.blue())

    @staticmethod
    def _major_expression(major_interval):
        return 'abs("value" % {0}) <= {1}'.format(major_interval, MAJOR_TOLERANCE)

    @staticmethod
    def _style(layer, major_interval):
        minor_colour, major_colour = LandXMLContours._colours()
        minor_symbol = QgsLineSymbol.createSimple(
            {'color': LandXMLContours._rgba(minor_colour), 'width': '0.16'})
        major_symbol = QgsLineSymbol.createSimple(
            {'color': LandXMLContours._rgba(major_colour), 'width': '0.4'})

        root = QgsRuleBasedRenderer.Rule(None)
        minor_rule = QgsRuleBasedRenderer.Rule(
            minor_symbol, 0, 0,
            'NOT ({0})'.format(LandXMLContours._major_expression(major_interval)),
            'Minor')
        major_rule = QgsRuleBasedRenderer.Rule(major_symbol, 0, 0, 'ELSE', 'Major')
        root.appendChild(minor_rule)
        root.appendChild(major_rule)

        layer.setRenderer(QgsRuleBasedRenderer(root))
        layer.triggerRepaint()

    @staticmethod
    def _label(layer, major_interval):
        settings = QgsPalLayerSettings()
        settings.fieldName = 'value'
        settings.placement = LandXMLContours._line_placement()

        text_format = QgsTextFormat()
        text_format.setSize(8)
        buffer_settings = QgsTextBufferSettings()
        buffer_settings.setEnabled(True)
        buffer_settings.setSize(1.0)
        buffer_settings.setColor(QColor(255, 255, 255))
        text_format.setBuffer(buffer_settings)
        settings.setFormat(text_format)

        root = QgsRuleBasedLabeling.Rule(None)
        rule = QgsRuleBasedLabeling.Rule(settings)
        rule.setDescription('Major contours')
        rule.setFilterExpression(
            LandXMLContours._major_expression(major_interval))
        root.appendChild(rule)

        layer.setLabeling(QgsRuleBasedLabeling(root))
        layer.setLabelsEnabled(True)

    @staticmethod
    def _line_placement():
        placement = getattr(QgsPalLayerSettings, 'Line', None)
        if placement is not None:
            return placement
        from qgis.core import Qgis
        return Qgis.LabelPlacement.Line

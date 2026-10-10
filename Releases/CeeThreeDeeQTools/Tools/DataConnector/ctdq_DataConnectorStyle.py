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

from qgis.core import (
    QgsMapLayer,
    QgsMapLayerStyle,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeatureRequest,
    QgsCategorizedSymbolRenderer,
    QgsGraduatedSymbolRenderer,
    QgsRuleBasedRenderer,
)


class DataConnectorStyle:
    """Copies styling onto extracted layers and drops classes that match no features."""

    @staticmethod
    def copy_style(source_layer, extracted_layer, results, prune_unused=True):
        """Transfer renderer/labeling from the source, prune empty classes, then persist."""
        try:
            style = QgsMapLayerStyle()
            style.readFromLayer(source_layer)
            if not style.isValid():
                return
            style.writeToLayer(extracted_layer)
        except Exception as exc:
            results['warnings'].append(
                f"Style transfer failed for '{extracted_layer.name()}': {exc}"
            )
            return

        if prune_unused:
            try:
                removed = DataConnectorStyle.prune_unused_classes(extracted_layer)
                if removed:
                    results['warnings'].append(
                        f"'{extracted_layer.name()}': removed {removed} unused style class(es)."
                    )
            except Exception as exc:
                results['warnings'].append(
                    f"Could not clean up style classes for '{extracted_layer.name()}': {exc}"
                )

        extracted_layer.triggerRepaint()
        DataConnectorStyle._save_default_style(extracted_layer, results)

    @staticmethod
    def _save_default_style(layer, results):
        """Persist to the gpkg layer_styles table, or a .qml beside a shapefile."""
        try:
            layer.saveDefaultStyle()
        except TypeError:
            # QGIS 3.26+ requires the style categories argument
            try:
                layer.saveDefaultStyle(QgsMapLayer.StyleCategory.AllStyleCategories)
            except Exception as exc:
                results['warnings'].append(
                    f"Could not save style for '{layer.name()}': {exc}"
                )
        except Exception as exc:
            results['warnings'].append(f"Could not save style for '{layer.name()}': {exc}")

    # ---------------------------------------------------------------- pruning

    @staticmethod
    def prune_unused_classes(layer) -> int:
        """Remove renderer classes with no matching features. Returns the number removed."""
        renderer = layer.renderer()

        if isinstance(renderer, QgsCategorizedSymbolRenderer):
            return DataConnectorStyle._prune_categorized(layer, renderer)
        if isinstance(renderer, QgsGraduatedSymbolRenderer):
            return DataConnectorStyle._prune_graduated(layer, renderer)
        if isinstance(renderer, QgsRuleBasedRenderer):
            return DataConnectorStyle._prune_rules(layer, renderer.rootRule())
        return 0

    @staticmethod
    def _prune_categorized(layer, renderer) -> int:
        present = DataConnectorStyle._collect_values(layer, renderer.classAttribute())
        if present is None:
            return 0

        categories = renderer.categories()
        doomed = []
        for index, category in enumerate(categories):
            if DataConnectorStyle._is_catch_all(category):
                continue
            if not DataConnectorStyle._category_matches(category, present):
                doomed.append(index)

        # Never strip every class - a renderer with no categories draws nothing.
        if len(doomed) >= len(categories):
            return 0

        for index in reversed(doomed):
            renderer.deleteCategory(index)
        return len(doomed)

    @staticmethod
    def _is_catch_all(category) -> bool:
        """The 'all other values' entry has an empty value and must be kept."""
        value = category.value()
        if value is None:
            return True
        if isinstance(value, (list, tuple)):
            return len(value) == 0
        return str(value) == ''

    @staticmethod
    def _category_matches(category, present) -> bool:
        value = category.value()
        # QGIS 3.26+ allows a single category to hold several values
        if isinstance(value, (list, tuple)):
            return any(DataConnectorStyle._normalise(item) in present for item in value)
        return DataConnectorStyle._normalise(value) in present

    @staticmethod
    def _prune_graduated(layer, renderer) -> int:
        values = DataConnectorStyle._collect_numeric_values(layer, renderer.classAttribute())
        if values is None:
            return 0

        ranges = renderer.ranges()
        doomed = []
        for index, value_range in enumerate(ranges):
            lower = value_range.lowerValue()
            upper = value_range.upperValue()
            if not any(lower <= value <= upper for value in values):
                doomed.append(index)

        if len(doomed) >= len(ranges):
            return 0

        for index in reversed(doomed):
            renderer.deleteClass(index)
        return len(doomed)

    @staticmethod
    def _prune_rules(layer, rule) -> int:
        """Recursively drop leaf rules whose filter matches nothing."""
        removed = 0
        for child in list(rule.children()):
            if child.children():
                removed += DataConnectorStyle._prune_rules(layer, child)
                continue

            if child.isElse() or not child.filterExpression():
                continue

            if not DataConnectorStyle._has_matching_feature(layer, child.filterExpression()):
                rule.removeChild(child)
                removed += 1

        return removed

    @staticmethod
    def _has_matching_feature(layer, expression) -> bool:
        request = QgsFeatureRequest().setFilterExpression(expression)
        request.setLimit(1)
        for _ in layer.getFeatures(request):
            return True
        return False

    # ------------------------------------------------------------ value reads

    @staticmethod
    def _collect_values(layer, attribute):
        """
        Distinct normalised values for a field or expression.

        Returns None when the classification cannot be evaluated, so callers skip pruning.
        """
        if not attribute:
            return None

        field_index = layer.fields().lookupField(attribute)
        if field_index >= 0:
            return {
                DataConnectorStyle._normalise(value)
                for value in layer.uniqueValues(field_index)
            }

        return DataConnectorStyle._evaluate_expression(
            layer, attribute, DataConnectorStyle._normalise
        )

    @staticmethod
    def _collect_numeric_values(layer, attribute):
        """Numeric values used by graduated classification, or None if not evaluable."""
        if not attribute:
            return None

        raw_values = None
        field_index = layer.fields().lookupField(attribute)
        if field_index >= 0:
            raw_values = layer.uniqueValues(field_index)
        else:
            raw_values = DataConnectorStyle._evaluate_expression(layer, attribute, lambda v: v)

        if raw_values is None:
            return None

        numeric = []
        for value in raw_values:
            try:
                numeric.append(float(value))
            except (TypeError, ValueError):
                continue
        return numeric

    @staticmethod
    def _evaluate_expression(layer, attribute, transform):
        expression = QgsExpression(attribute)
        if expression.hasParserError():
            return None

        context = QgsExpressionContext(
            QgsExpressionContextUtils.globalProjectLayerScopes(layer)
        )
        expression.prepare(context)

        values = set()
        for feature in layer.getFeatures():
            context.setFeature(feature)
            values.add(transform(expression.evaluate(context)))
        return values

    @staticmethod
    def _normalise(value) -> str:
        """String form used to compare feature values against class values."""
        if value is None:
            return ''
        try:
            if value.isNull():  # QVariant null
                return ''
        except AttributeError:
            pass
        return str(value)

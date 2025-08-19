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

from typing import Any, Optional

from qgis.core import (
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFileDestination,
    QgsProject,
    QgsLayerTreeModel,
    QgsMapLayer,
    Qgis,
    QgsVectorLayerSimpleLabeling,
    QgsRuleBasedLabeling,
    QgsPalLayerSettings,
    QgsSingleBandGrayRenderer,
    QgsSingleBandPseudoColorRenderer,
)
from qgis import processing
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QPushButton, QScrollArea, QWidget
import xml.etree.ElementTree as ET
from xml.dom.minidom import parseString
from .support import ctdtool_info


class ThemeSelectionDialog(QDialog):
    def __init__(self, themes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Themes")
        self.selected_themes = []

        layout = QVBoxLayout(self)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        self.checkboxes = []
        for theme in themes:
            checkbox = QCheckBox(theme)
            scroll_layout.addWidget(checkbox)
            self.checkboxes.append(checkbox)

        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)

        button_box = QVBoxLayout()
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_box.addWidget(ok_button)
        button_box.addWidget(cancel_button)

        layout.addLayout(button_box)

    def getSelectedThemes(self):
        return [checkbox.text() for checkbox in self.checkboxes if checkbox.isChecked()]


class ExportProjectStylesAsXML(QgsProcessingAlgorithm):
    TOOL_NAME = "ExportProjectStylesAsXML"
    """
    Export all QGIS style information to an XML report.
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    OUTPUT = "OUTPUT"  # Update this constant to reflect XML output
    THEMES = "THEMES"  # Reintroduce this constant

    def name(self):
        return self.TOOL_NAME

    def displayName(self):
        return ctdtool_info[self.TOOL_NAME]["disp"]

    def group(self):
        return ctdtool_info[self.TOOL_NAME]["group"]

    def groupId(self):
        return ctdtool_info[self.TOOL_NAME]["group_id"]

    def shortHelpString(self) -> str:
        """
        Returns a localised short helper string for the algorithm. This string
        should provide a basic description about what the algorithm does and the
        parameters and outputs associated with it.
        """
        return "Exports all the QGIS style information to a report."

    def initAlgorithm(self, config: Optional[dict[str, Any]] = None):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """

        # Retrieve all saved themes in the current QGIS project
        project = QgsProject.instance()
        saved_themes = project.mapThemeCollection().mapThemes()

        # Add a parameter for selecting themes
        self.addParameter(
            QgsProcessingParameterEnum(
                self.THEMES,
                "Select themes",
                options=saved_themes,
                allowMultiple=True,
                optional=True,
            )
        )

        # Update the output parameter to export to an XML file
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                "Output XML file",
                fileFilter="XML files (*.xml)"
            )
        )

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        """
        Here is where the processing itself takes place.
        """

        # Retrieve the output file path
        output_file = self.parameterAsFile(parameters, self.OUTPUT, context)

        # Retrieve selected themes from the input parameter
        selected_theme_indices = self.parameterAsEnums(parameters, self.THEMES, context)
        project = QgsProject.instance()
        saved_themes = project.mapThemeCollection().mapThemes()
        filtered_themes = [saved_themes[i] for i in selected_theme_indices]

        feedback.pushInfo(f"Filtered themes: {filtered_themes}")

        # Create an XML structure for the selected themes and their layers
        root = ET.Element("Themes")
        layer_tree_root = project.layerTreeRoot()
        layer_tree_model = QgsLayerTreeModel(layer_tree_root)

        # Define a mapping for LayerFlag enum values
        layer_flag_mapping = {
            QgsMapLayer.LayerFlag.Identifiable: "Identifiable",
            QgsMapLayer.LayerFlag.Removable: "Removable",
            QgsMapLayer.LayerFlag.Searchable: "Searchable",
            QgsMapLayer.LayerFlag.Private: "Private",
        }

        for theme in filtered_themes:
            theme_element = ET.SubElement(root, "Theme", name=theme)

            # Apply the theme
            project.mapThemeCollection().applyTheme(theme, layer_tree_root, layer_tree_model)

            # Add visible layers as child nodes under the theme
            for layer in project.mapLayers().values():
                # Check if the layer is visible
                layer_tree_node = layer_tree_root.findLayer(layer.id())
                is_visible = layer_tree_node.isVisible() if layer_tree_node else False

                # Skip layers that are not visible
                if not is_visible:
                    continue

                # Create the Layer node
                layer_element = ET.SubElement(
                    theme_element, "Layer", name=layer.name(), visible=str(is_visible)
                )

                # Convert layer flags to human-readable format
                layer_flags = layer.flags()
                readable_flags = [
                    name for flag, name in layer_flag_mapping.items() if layer_flags & flag
                ]
                layer_element.set("flags", ", ".join(readable_flags))

                # Add rasterStyle or vectorStyle based on layer type
                if layer.type() == QgsMapLayer.RasterLayer:
                    raster_style_element = ET.SubElement(layer_element, "rasterStyle")
                    renderer = layer.renderer()
                    if renderer:
                        legend_items_element = ET.SubElement(raster_style_element, "LegendItems")
                        for value, color in renderer.legendSymbologyItems():
                            legend_item_element = ET.SubElement(legend_items_element, "LegendItem")
                            legend_item_element.set("value", str(value))
                            legend_item_element.set("color", color.name())
                    else:
                        ET.SubElement(raster_style_element, "NotTransferrable")

                elif layer.type() == QgsMapLayer.VectorLayer:
                    vector_style_element = ET.SubElement(layer_element, "vectorStyle")
                    geometry_type = layer.geometryType()
                    geometry_type_str = {
                        Qgis.GeometryType.Point: "Point",
                        Qgis.GeometryType.Line: "Line",
                        Qgis.GeometryType.Polygon: "Polygon",
                    }.get(geometry_type, "Unknown")
                    vector_style_element.set("geometryType", geometry_type_str)

                    # Add symbology node
                    symbology = layer.renderer()
                    if symbology:
                        symbology_element = ET.SubElement(vector_style_element, "symbology")

                        # Check symbology type
                        if symbology.type() == "singleSymbol":
                            single_symbol_element = ET.SubElement(symbology_element, "SingleSymbol")
                            symbol = symbology.symbol()
                            for i in range(symbol.symbolLayerCount()):
                                symbol_layer = symbol.symbolLayer(i)
                                for key, value in symbol_layer.properties().items():
                                    single_symbol_element.set(key, str(value))
                        elif symbology.type() == "categorizedSymbol":
                            multi_symbol_element = ET.SubElement(symbology_element, "MultiSymbol")
                            for category in symbology.categories():
                                category_element = ET.SubElement(multi_symbol_element, "Category", name=category.label())
                                symbol = category.symbol()
                                for i in range(symbol.symbolLayerCount()):
                                    symbol_layer = symbol.symbolLayer(i)
                                    for key, value in symbol_layer.properties().items():
                                        category_element.set(key, str(value))

                    # Add labels node
                    labels_element = ET.SubElement(vector_style_element, "labels")
                    labeling = layer.labeling()
                    if not layer.labelsEnabled():
                        ET.SubElement(labels_element, "NoLabels")
                    elif isinstance(labeling, QgsVectorLayerSimpleLabeling):
                        single_labels_element = ET.SubElement(labels_element, "SingleLabels")
                        label_settings = labeling.settings()
                        label_format = labeling.settings().format()
                        single_labels_element.set("FieldName", label_settings.fieldName)
                        single_labels_element.set("FontFamily", label_format.font().family())  # Extract font family as string
                        single_labels_element.set("FontStyle", label_format.font().styleName())
                        single_labels_element.set("FontSize", str(label_format.font().pointSize()))
                        single_labels_element.set("TextColor", label_format.color().name())
                        single_labels_element.set("BufferSize", str(label_format.buffer().size()))
                        single_labels_element.set("BufferColor", label_format.buffer().color().name())                      

                    elif isinstance(labeling, QgsRuleBasedLabeling):
                        rule_based_labels_element = ET.SubElement(labels_element, "RuleBasedLabels")
                        for rule in labeling.rootRule().children():
                            rule_element = ET.SubElement(rule_based_labels_element, "Rule")
                            rule_settings = rule.settings()
                            rule_format = rule.settings().format()
                            rule_element.set("FieldName", rule_settings.fieldName)
                            rule_element.set("FontFamily", rule_format.font().family())  # Extract font family as string
                            rule_element.set("FontStyle", rule_format.font().styleName())
                            rule_element.set("FontSize", str(rule_format.font().pointSize()))
                            rule_element.set("TextColor", rule_format.color().name())
                            rule_element.set("BufferSize", str(rule_format.buffer().size()))
                            rule_element.set("BufferColor", rule_format.buffer().color().name())   
                            

                    else:
                        ET.SubElement(labels_element, "LabelsNotTransferrable")

        # Convert the XML structure to a string and prettify it
        xml_string = ET.tostring(root, encoding="utf-8")
        pretty_xml = parseString(xml_string).toprettyxml(indent="  ")

        # Write the prettified XML to the output file
        try:
            with open(output_file, "w", encoding="utf-8") as file:
                file.write(pretty_xml)
            feedback.pushInfo(f"XML file successfully written to {output_file}")
        except Exception as e:
            raise QgsProcessingException(f"Failed to write XML file: {e}")

        # Return the results of the algorithm
        return {self.OUTPUT: output_file}

    def createInstance(self):
        return self.__class__()

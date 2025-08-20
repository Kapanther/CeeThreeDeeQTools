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
    QgsVectorLayer,
    QgsRasterLayer,
    QgsProcessingParameterFolderDestination
)
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QPushButton, QScrollArea, QWidget
import xml.etree.ElementTree as ET
from xml.dom.minidom import parseString
from .ctdq_support import ctdtool_info
import os


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

class ExportProjectLayerStyles(QgsProcessingAlgorithm):
    TOOL_NAME = "ExportProjectLayerStyles"

    # PARAMETERS #

    OUTPUT = "OUTPUT"  # Update this constant to reflect XML output
    THEMES = "THEMES"  # Reintroduce this constant
    EXPORT_MODE = "EXPORT_MODE"  # New parameter for export mode
    QML_OUTPUT_DIR = "QML_OUTPUT_DIR"  # New parameter for QML output directory

    def name(self):
        return self.TOOL_NAME

    def displayName(self):
        return ctdtool_info[self.TOOL_NAME]["disp"]

    def group(self):
        return ctdtool_info[self.TOOL_NAME]["group"]

    def groupId(self):
        return ctdtool_info[self.TOOL_NAME]["group_id"]

    def shortHelpString(self) -> str:
        return "Exports all the QGIS style information to a report."

    def initAlgorithm(self, config: Optional[dict[str, Any]] = None):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """

        # Retrieve all saved themes in the current QGIS project
        project = QgsProject.instance()
        saved_themes = project.mapThemeCollection().mapThemes()

        # Add a parameter for selecting export mode
        self.addParameter(
            QgsProcessingParameterEnum(
                self.EXPORT_MODE,
                "Export Mode",
                options=["ByThemes", "ByLayer"],
                defaultValue=0  # Default to "ByThemes"
            )
        )

        # Add a parameter for selecting themes (only used in "ByThemes" mode)
        self.addParameter(
            QgsProcessingParameterEnum(
                self.THEMES,
                "Select themes (if by themes mode is selected)",
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
                fileFilter="XML files (*.xml)",
                optional=True
            )
        )

        # Add a parameter for specifying the QML output directory
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.QML_OUTPUT_DIR,
                "QML Output Directory",
                optional=True
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

        # Retrieve the selected export mode
        export_mode_index = self.parameterAsEnum(parameters, self.EXPORT_MODE, context)
        export_mode = ["ByThemes", "ByLayer"][export_mode_index]

        # Retrieve the project instance
        project = QgsProject.instance()

        # Retrieve the layer tree root and model
        layer_tree_root = project.layerTreeRoot()
        layer_tree_model = QgsLayerTreeModel(layer_tree_root)

        # Retrieve the QML output directory
        qml_output_dir = self.parameterAsString(parameters, self.QML_OUTPUT_DIR, context)
        if qml_output_dir and not os.path.exists(qml_output_dir):
            os.makedirs(qml_output_dir)

        # Create an XML structure
        root = ET.Element("Export")

        if export_mode == "ByThemes":
            # Retrieve selected themes from the input parameter
            selected_theme_indices = self.parameterAsEnums(parameters, self.THEMES, context)
            saved_themes = project.mapThemeCollection().mapThemes()
            filtered_themes = [saved_themes[i] for i in selected_theme_indices]

            feedback.pushInfo(f"Exporting by themes: {filtered_themes}")

            for theme in filtered_themes:
                theme_element = ET.SubElement(root, "Theme", name=theme)

                # Apply the theme
                project.mapThemeCollection().applyTheme(theme, layer_tree_root, layer_tree_model)

                # Create a directory for the theme if QML export is enabled
                theme_qml_dir = None
                if qml_output_dir:
                    theme_qml_dir = os.path.join(qml_output_dir, theme)
                    os.makedirs(theme_qml_dir, exist_ok=True)

                # Add visible layers as child nodes under the theme
                for layer in project.mapLayers().values():
                    layer_tree_node = layer_tree_root.findLayer(layer.id())
                    is_visible = layer_tree_node.isVisible() if layer_tree_node else False

                    if not is_visible:
                        continue

                    layer_element = ET.SubElement(
                        theme_element, "Layer", name=layer.name(), visible=str(is_visible)
                    )
                    self._add_layer_details(layer, layer_element)

                    # Export QML for the layer
                    if qml_output_dir and theme_qml_dir:
                        self._export_qml(layer, theme_qml_dir, feedback)

        elif export_mode == "ByLayer":
            feedback.pushInfo("Exporting by layers")

            for layer in project.mapLayers().values():
                layer_element = ET.SubElement(root, "Layer", name=layer.name())
                self._add_layer_details(layer, layer_element)

                # Export QML for the layer
                if qml_output_dir:
                    self._export_qml(layer, qml_output_dir, feedback)

        # Write the XML file only if an output file path is specified
        if output_file:
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
        else:
            feedback.pushInfo("No XML file specified. Skipping XML export.")

        # Return the results of the algorithm
        return {self.OUTPUT: output_file if output_file else None}

    def _add_layer_details(self, layer, layer_element):
        """
        Adds details about a layer to the XML element.
        """
        # Define a mapping for LayerFlag enum values
        layer_flag_mapping = {
            QgsMapLayer.LayerFlag.Identifiable: "Identifiable",
            QgsMapLayer.LayerFlag.Removable: "Removable",
            QgsMapLayer.LayerFlag.Searchable: "Searchable",
            QgsMapLayer.LayerFlag.Private: "Private",
        }

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

    def _export_qml(self, layer, output_dir, feedback):
        """
        Exports the QML (QGIS Layer Style) file for a given layer.
        Handles duplicate layer names by appending a numeric suffix.
        """
        if not isinstance(layer, (QgsVectorLayer, QgsRasterLayer)):
            feedback.pushInfo(f"Skipping QML export for unsupported layer type: {layer.name()}")
            return

        base_name = layer.name()
        file_name = f"{base_name}.qml"
        file_path = os.path.join(output_dir, file_name)

        # Handle duplicate layer names
        counter = 1
        while os.path.exists(file_path):
            file_name = f"{base_name}_{counter}.qml"
            file_path = os.path.join(output_dir, file_name)
            counter += 1

        try:
            layer.saveNamedStyle(file_path)
            feedback.pushInfo(f"QML file saved: {file_path}")
        except Exception as e:
            feedback.reportError(f"Failed to save QML for layer {layer.name()}: {e}")

    def createInstance(self):
        return self.__class__()

"""
Common Functions for CTDQ Algorithms
"""
from qgis.core import (
    QgsRasterBandStats,
    QgsSingleBandPseudoColorRenderer,
    QgsGradientColorRamp,
    QgsFillSymbol,
    QgsTextFormat,
    QgsProcessingLayerPostProcessorInterface,
    QgsProcessing,
    QgsRendererRange,
    QgsClassificationQuantile,
    QgsTextBufferSettings,
    QgsLayerTreeGroup,
    QgsLayerTree,
    QgsGraduatedSymbolRenderer,  # Added import
    QgsStyle,  # Added import for QgsStyle
    QgsPalLayerSettings,  # Added import for labeling
    QgsVectorLayerSimpleLabeling,
    QgsCategorizedSymbolRenderer,  # Added import for categorized rendering
    QgsRendererCategory,  # Added import for renderer categories
    QgsSymbol,  # Added import for symbols
)

from qgis.PyQt.QtGui import QColor

from qgis.utils import iface
from qgis.PyQt.QtCore import QItemSelectionModel, Qt, QCoreApplication
import inspect

import processing


class LayerPostProcessor(QgsProcessingLayerPostProcessorInterface):
    def __init__(self, display_name, 
                 color_ramp_graduated: QgsGraduatedSymbolRenderer = None,
                 color_ramp_catergorised: QgsCategorizedSymbolRenderer = None,
                 color_ramp_field: str = None, 
                 fill_symbol_definition: QgsFillSymbol = None,
                 label_field_expression: str = None,
                 label_text_format: QgsTextFormat = None,
                 label_buffer_format: QgsTextBufferSettings = None
                 ):
        super().__init__()
        self.display_name = display_name
        self.colour_ramp_graduated = color_ramp_graduated # expects a QgsGraduatedSymbolRenderer
        self.colour_ramp_catergorised = color_ramp_catergorised # expects a QgsCategorizedSymbolRenderer
        self.color_ramp_field = color_ramp_field # expects a string
        self.fill_symbol_definition = fill_symbol_definition # expects a QgsFillSymbol
        self.label_field_expression = label_field_expression # expects a string
        self.label_text_format = label_text_format # expects a QgsTextFormat and also an expression to be defined
        self.label_buffer_format = label_buffer_format # expects a QgsTextBufferSettings and also an expression to be defined and a text format        

    def postProcessLayer(self, layer, context, feedback):
        if layer.isValid():
            # Set the layer name
            layer.setName(self.display_name)

            # Apply fill symbol if available
            if self.fill_symbol_definition:
                try:
                    layer.renderer().setSymbol(self.fill_symbol_definition)
                    layer.triggerRepaint()                                      
                except Exception as e_fs:
                    feedback.pushInfo(f"Styler: failed to apply fill symbol: {e_fs}")

            # Apply labeling if available
            if self.label_field_expression:
                feedback.pushInfo(f"Styler: applying labeling on field {self.label_field_expression}")
                try:
                    label_settings = QgsPalLayerSettings()
                    if( self.label_text_format):
                        text_format = self.label_text_format
                        if( self.label_buffer_format):
                            text_format.setBuffer(self.label_buffer_format)
                        label_settings.setFormat(text_format)  # Apply text format if provided                        
                    label_settings.fieldName = self.label_field_expression       
                    label_settings.isExpression = True  # Treat fieldName as an expression             
                    label_settings.placement = QgsPalLayerSettings.Horizontal                
                    label_settings.placementSettings().allowDegradedPlacement = True

                    label_settings.enabled = True  # Enable labeling
                    
                    labeling = QgsVectorLayerSimpleLabeling(label_settings)
                    layer.setLabeling(labeling)
                    layer.setLabelsEnabled(True)                    
                    layer.triggerRepaint()                    
                    
                except Exception as e_l:
                    feedback.pushInfo(f"Styler: failed to apply labeling: {e_l}")

            # Applty categorized renderer
            if self.colour_ramp_catergorised and self.color_ramp_field:                
                feedback.pushInfo(f"Styler: applying categorized renderer on field {self.color_ramp_field}")
                try:
                    # Use the provided categorized renderer directly
                    layer.setRenderer(self.colour_ramp_catergorised)
                    feedback.pushInfo("Styler: categorized renderer applied.")
                except Exception as e_r:
                    feedback.pushInfo(f"Styler: failed to create/apply categorized renderer: {e_r}")

            # Apply graduated renderer
            if self.colour_ramp_graduated and self.color_ramp_field:                
                feedback.pushInfo(f"Styler: applying graduated renderer on field {self.color_ramp_field}")
                try:
                    # Use the provided graduated renderer directly
                    class_method = QgsClassificationQuantile()
                    class_method.setLabelPrecision(1)
                    self.colour_ramp_graduated.setClassificationMethod(class_method)
                    self.colour_ramp_graduated.updateClasses(layer, 5)
                    layer.setRenderer(self.colour_ramp_graduated)
                    feedback.pushInfo("Styler: graduated renderer applied.")
                except Exception as e_r:
                    feedback.pushInfo(f"Styler: failed to create/apply graduated renderer: {e_r}")


            # finally attempt to refresh legend/symbology view (best-effort)
            try:
                iface.layerTreeView().refreshLayerSymbology(layer.id())
                QCoreApplication.processEvents()
            except Exception:
                try:
                    # older/newer API differences — ignore failures
                    iface.layerTreeView().refreshLayerSymbology()
                except Exception:
                    pass


def create_group(name: str, root: QgsLayerTree) -> None:
    """
    Create a group (if doesn't exist) in QGIS layer tree.
    """
    group = root.findGroup(name)  # find group in whole hierarchy
    if not group:  # if group does not already exists
        selected_nodes = iface.layerTreeView().selectedNodes()  # get all selected nodes
        if selected_nodes:  # if a node is selected
            # check the first node is group
            if isinstance(selected_nodes[0], QgsLayerTreeGroup):
                # if it is add a group inside
                group = selected_nodes[0].insertGroup(0, name)
            else:
                parent = selected_nodes[0].parent()
                # get current index so that new group can be inserted at that location
                index = parent.children().index(selected_nodes[0])
                group = parent.insertGroup(index, name)
        else:
            group = root.insertGroup(0, name)


def select_group(name: str) -> bool:
    """
    Select group item of a node tree
    """

    view = iface.layerTreeView()
    m = view.model()

    listIndexes = m.match(
        m.index(0, 0),
        Qt.DisplayRole,
        name,
        1,
        Qt.MatchFixedString | Qt.MatchRecursive | Qt.MatchCaseSensitive | Qt.MatchWrap,
    )

    if listIndexes:
        i = listIndexes[0]
        view.selectionModel().setCurrentIndex(i, QItemSelectionModel.ClearAndSelect)
        return True

    else:
        return False

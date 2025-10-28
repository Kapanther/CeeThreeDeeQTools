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
    def __init__(self, display_name, symbology=None):
        """
        Initialize the LayerPostProcessor with a symbology object.
        
        Args:
            display_name: The name to display for the layer
            symbology: PostVectorSymbology or PostRasterSymbology object
        """
        super().__init__()
        self.display_name = display_name
        self.symbology = symbology

    def postProcessLayer(self, layer, context, feedback):
        """
        Apply symbology and set display name for the layer during post-processing.
        
        Args:
            layer: The QgsVectorLayer or QgsRasterLayer to process
            context: The QgsProcessingContext for the algorithm
            feedback: The QgsProcessingFeedback for reporting progress
        """
        if layer.isValid():
            # Set the layer name
            layer.setName(self.display_name)

            if not self.symbology:
                return

            # Import here to avoid circular imports
            from .ctdq_AlgoSymbology import PostVectorSymbology, PostRasterSymbology

            # Handle vector symbology
            if isinstance(self.symbology, PostVectorSymbology):
                self._apply_vector_symbology(layer, context, feedback)
            
            # Handle raster symbology (placeholder for future implementation)
            elif isinstance(self.symbology, PostRasterSymbology):
                self._apply_raster_symbology(layer, context, feedback)

            # Finally attempt to refresh legend/symbology view (best-effort)
            try:
                iface.layerTreeView().refreshLayerSymbology(layer.id())
                QCoreApplication.processEvents()
            except Exception:
                try:
                    # older/newer API differences — ignore failures
                    iface.layerTreeView().refreshLayerSymbology()
                except Exception:
                    pass

    def _apply_vector_symbology(self, layer, context, feedback):
        """Apply vector symbology from PostVectorSymbology object."""
        # Apply renderer (graduated, categorized, or single symbol)
        renderer = self.symbology.get_renderer()
        if renderer:
            try:
                if self.symbology.graduated_renderer:
                    feedback.pushInfo(f"Styler: applying graduated renderer on field {self.symbology.color_ramp_field}")
                    class_method = QgsClassificationQuantile()
                    class_method.setLabelPrecision(1)
                    renderer.setClassificationMethod(class_method)
                    renderer.updateClasses(layer, 5)
                    layer.setRenderer(renderer)
                    feedback.pushInfo("Styler: graduated renderer applied.")
                
                elif self.symbology.categorized_renderer:
                    feedback.pushInfo(f"Styler: applying categorized renderer on field {self.symbology.color_ramp_field}")
                    # If no categories were provided, generate them from unique values
                    if not renderer.categories():
                        self._generate_categorized_colors(layer, renderer, self.symbology.color_ramp_field)
                    layer.setRenderer(renderer)
                    feedback.pushInfo("Styler: categorized renderer applied.")
                
                elif self.symbology.single_symbol_renderer:
                    feedback.pushInfo("Styler: applying single symbol renderer")
                    layer.setRenderer(renderer)
                    feedback.pushInfo("Styler: single symbol renderer applied.")
                
                layer.triggerRepaint()
            except Exception as e_r:
                feedback.pushInfo(f"Styler: failed to apply renderer: {e_r}")

        # Apply labeling
        if self.symbology.labeling:
            try:
                feedback.pushInfo(f"Styler: applying labeling")
                layer.setLabeling(self.symbology.labeling)
                layer.setLabelsEnabled(True)
                layer.triggerRepaint()
                feedback.pushInfo("Styler: labeling applied.")
            except Exception as e_l:
                feedback.pushInfo(f"Styler: failed to apply labeling: {e_l}")

    def _generate_categorized_colors(self, layer, renderer, field_name):
        """Generate random colors for categorized renderer based on unique values.

        Args:
            layer: The QgsVectorLayer to process
            renderer: The QgsCategorizedSymbolRenderer to update
            field_name: The name of the field to categorize
        """
        import random
        categories = []
        unique_values = layer.uniqueValues(layer.fields().indexFromName(field_name))
        
        # Get the symbol from the renderer or create a default one
        base_symbol = renderer.sourceSymbol() if renderer.sourceSymbol() else QgsSymbol.defaultSymbol(layer.geometryType())
        
        for value in unique_values:
            if value is not None:
                # Create a copy of the symbol with different color
                category_symbol = base_symbol.clone()
                # Generate a random-ish color based on the value hash
                random.seed(hash(str(value)))
                color = QColor.fromHsv(random.randint(0, 359), 180, 200, 128)
                category_symbol.setColor(color)
                
                category = QgsRendererCategory(value, category_symbol, str(value))
                categories.append(category)
        
        # Update renderer with new categories using the correct API
        renderer.deleteAllCategories()
        for category in categories:
            renderer.addCategory(category)

    def _apply_raster_symbology(self, layer, context, feedback):
        """Apply raster symbology from PostRasterSymbology object (placeholder)."""
        feedback.pushInfo("Styler: raster symbology not yet implemented.")
        # TODO: Implement raster symbology application


def create_group(name: str, root: QgsLayerTree) -> None:
    """
    Create a group (if doesn't exist) in QGIS layer tree.

    Args:
        name: The name of the group to create
        root: The root QgsLayerTree to search for the group

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

    Args:
        name: The name of the group to select
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

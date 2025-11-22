"""
Service for handling layer symbology visibility updates.
"""

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsCategorizedSymbolRenderer,
    QgsGraduatedSymbolRenderer,
    QgsRuleBasedRenderer
)


class SymbologyService:
    """Handles symbology visibility updates for categorized, graduated, and rule-based renderers."""
    
    @staticmethod
    def update_category_visibility(layer_id, category_index, visible, iface):
        """Update visibility of a categorized symbol category."""
        try:
            project = QgsProject.instance()
            layer = project.mapLayer(layer_id)
            
            if not layer or not isinstance(layer, QgsVectorLayer):
                return False, None
            
            renderer = layer.renderer()
            if not isinstance(renderer, QgsCategorizedSymbolRenderer):
                return False, None
            
            # Validate index
            if category_index < 0 or category_index >= len(renderer.categories()):
                return False, None
            
            # Update the render state
            renderer.updateCategoryRenderState(category_index, visible)
            
            # Trigger updates
            layer.triggerRepaint()
            iface.layerTreeView().refreshLayerSymbology(layer.id())
            layer.emitStyleChanged()
            
            return True, layer
            
        except Exception:
            return False, None
    
    @staticmethod
    def update_range_visibility(layer_id, range_index, visible, iface):
        """Update visibility of a graduated symbol range."""
        try:
            project = QgsProject.instance()
            layer = project.mapLayer(layer_id)
            
            if not layer or not isinstance(layer, QgsVectorLayer):
                return False, None
            
            renderer = layer.renderer()
            if not isinstance(renderer, QgsGraduatedSymbolRenderer):
                return False, None
            
            # Validate index
            if range_index < 0 or range_index >= len(renderer.ranges()):
                return False, None
            
            # Update the render state
            renderer.updateRangeRenderState(range_index, visible)
            
            # Trigger updates
            layer.triggerRepaint()
            iface.layerTreeView().refreshLayerSymbology(layer.id())
            layer.emitStyleChanged()
            
            return True, layer
            
        except Exception:
            return False, None
    
    @staticmethod
    def update_rule_visibility(layer_id, rule_key, visible, iface):
        """Update visibility of a rule-based renderer rule."""
        try:
            project = QgsProject.instance()
            layer = project.mapLayer(layer_id)
            
            if not layer or not isinstance(layer, QgsVectorLayer):
                return False, None
            
            renderer = layer.renderer()
            if not isinstance(renderer, QgsRuleBasedRenderer):
                return False, None
            
            # Find and update the rule
            root_rule = renderer.rootRule()
            rule = root_rule.findRuleByKey(rule_key)
            if not rule:
                return False, None
            
            rule.setActive(visible)
            
            # Trigger updates
            layer.triggerRepaint()
            iface.layerTreeView().refreshLayerSymbology(layer.id())
            layer.emitStyleChanged()
            
            return True, layer
                    
        except Exception:
            return False, None
    
    @staticmethod
    def update_symbology_checkboxes_for_layer(layer, tree_widget):
        """Update symbology checkbox states for a specific layer without rebuilding the tree."""
        from qgis.PyQt.QtCore import Qt
        
        try:
            # Find the tree item for this layer
            layer_item = SymbologyService._find_layer_item(layer.id(), tree_widget)
            
            if not layer_item:
                return False
            
            # Update symbology child items
            renderer = layer.renderer()
            
            if isinstance(renderer, QgsCategorizedSymbolRenderer):
                SymbologyService._update_category_checkboxes(layer_item, renderer)
            
            elif isinstance(renderer, QgsGraduatedSymbolRenderer):
                SymbologyService._update_range_checkboxes(layer_item, renderer)
            
            elif isinstance(renderer, QgsRuleBasedRenderer):
                # Rule-based renderers need full refresh
                return False
            
            return True
                    
        except Exception:
            return False
    
    @staticmethod
    def _find_layer_item(layer_id, tree_widget):
        """Find the tree widget item for a given layer ID."""
        from qgis.PyQt.QtCore import Qt
        
        root = tree_widget.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            if item.data(0, Qt.UserRole + 1) == "layer":
                if item.data(0, Qt.UserRole) == layer_id:
                    return item
            # Check group children
            elif item.data(0, Qt.UserRole + 1) == "group":
                for j in range(item.childCount()):
                    child = item.child(j)
                    if child.data(0, Qt.UserRole + 1) == "layer":
                        if child.data(0, Qt.UserRole) == layer_id:
                            return child
        return None
    
    @staticmethod
    def _update_category_checkboxes(layer_item, renderer):
        """Update checkbox states for categorized renderer."""
        from qgis.PyQt.QtCore import Qt
        
        categories = renderer.categories()
        for i in range(layer_item.childCount()):
            child = layer_item.child(i)
            if child.data(0, Qt.UserRole + 1) == "category":
                category_index = child.data(0, Qt.UserRole + 2)
                if 0 <= category_index < len(categories):
                    category = categories[category_index]
                    new_state = Qt.Checked if category.renderState() else Qt.Unchecked
                    if child.checkState(0) != new_state:
                        child.setCheckState(0, new_state)
    
    @staticmethod
    def _update_range_checkboxes(layer_item, renderer):
        """Update checkbox states for graduated renderer."""
        from qgis.PyQt.QtCore import Qt
        
        ranges = renderer.ranges()
        for i in range(layer_item.childCount()):
            child = layer_item.child(i)
            if child.data(0, Qt.UserRole + 1) == "range":
                range_index = child.data(0, Qt.UserRole + 2)
                if 0 <= range_index < len(ranges):
                    range_item = ranges[range_index]
                    new_state = Qt.Checked if range_item.renderState() else Qt.Unchecked
                    if child.checkState(0) != new_state:
                        child.setCheckState(0, new_state)

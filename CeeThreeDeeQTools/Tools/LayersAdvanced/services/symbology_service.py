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
    def update_category_visibility(layer_id, category_index, visible, iface, log_callback=None):
        """
        Update visibility of a categorized symbol category.
        
        Args:
            layer_id: Layer ID
            category_index: Index of the category to update
            visible: True to show, False to hide
            iface: QGIS interface object
            log_callback: Optional callback function for logging
        
        Returns:
            tuple: (success: bool, layer: QgsVectorLayer or None)
        """
        try:
            if log_callback:
                log_callback(f"update_category_visibility: index={category_index}, visible={visible}")
            
            project = QgsProject.instance()
            layer = project.mapLayer(layer_id)
            
            if not layer:
                if log_callback:
                    log_callback(f"ERROR: Layer not found: {layer_id}")
                return False, None
            
            if not isinstance(layer, QgsVectorLayer):
                if log_callback:
                    log_callback(f"ERROR: Layer is not a vector layer")
                return False, None
            
            renderer = layer.renderer()
            if not isinstance(renderer, QgsCategorizedSymbolRenderer):
                if log_callback:
                    log_callback(f"ERROR: Renderer is not categorized: {type(renderer)}")
                return False, None
            
            if log_callback:
                log_callback(f"Found categorized renderer with {len(renderer.categories())} categories")
            
            # Validate index
            if category_index < 0 or category_index >= len(renderer.categories()):
                if log_callback:
                    log_callback(f"ERROR: Invalid category index: {category_index}")
                return False, None
            
            # Update the render state
            renderer.updateCategoryRenderState(category_index, visible)
            category = renderer.categories()[category_index]
            if log_callback:
                log_callback(f"Updated category {category_index} '{category.label()}' to visible={visible}")
            
            # Trigger updates - emit rendererChanged to force styling panel update
            layer.triggerRepaint()
            iface.layerTreeView().refreshLayerSymbology(layer.id())
            
            # CRITICAL: Emit rendererChanged signal to force QGIS Layer Styling panel to update
            try:
                layer.rendererChanged.emit()
                if log_callback:
                    log_callback(f"Emitted rendererChanged signal")
            except Exception as e:
                if log_callback:
                    log_callback(f"Error emitting rendererChanged: {str(e)}")
            
            if log_callback:
                log_callback(f"Category visibility update complete")
            
            return True, layer
            
        except Exception as e:
            import traceback
            if log_callback:
                error_msg = f"ERROR in update_category_visibility: {str(e)}\n{traceback.format_exc()}"
                log_callback(error_msg)
            return False, None
    
    @staticmethod
    def update_range_visibility(layer_id, range_index, visible, iface, log_callback=None):
        """
        Update visibility of a graduated symbol range.
        
        Args:
            layer_id: Layer ID
            range_index: Index of the range to update
            visible: True to show, False to hide
            iface: QGIS interface object
            log_callback: Optional callback function for logging
        
        Returns:
            tuple: (success: bool, layer: QgsVectorLayer or None)
        """
        try:
            if log_callback:
                log_callback(f"update_range_visibility: index={range_index}, visible={visible}")
            
            project = QgsProject.instance()
            layer = project.mapLayer(layer_id)
            
            if not layer:
                if log_callback:
                    log_callback(f"ERROR: Layer not found: {layer_id}")
                return False, None
            
            if not isinstance(layer, QgsVectorLayer):
                if log_callback:
                    log_callback(f"ERROR: Layer is not a vector layer")
                return False, None
            
            renderer = layer.renderer()
            if not isinstance(renderer, QgsGraduatedSymbolRenderer):
                if log_callback:
                    log_callback(f"ERROR: Renderer is not graduated: {type(renderer)}")
                return False, None
            
            if log_callback:
                log_callback(f"Found graduated renderer with {len(renderer.ranges())} ranges")
            
            # Validate index
            if range_index < 0 or range_index >= len(renderer.ranges()):
                if log_callback:
                    log_callback(f"ERROR: Invalid range index: {range_index}")
                return False, None
            
            # Update the render state
            renderer.updateRangeRenderState(range_index, visible)
            range_item = renderer.ranges()[range_index]
            if log_callback:
                log_callback(f"Updated range {range_index} '{range_item.label()}' to visible={visible}")
            
            # Trigger updates - emit rendererChanged to force styling panel update
            layer.triggerRepaint()
            iface.layerTreeView().refreshLayerSymbology(layer.id())
            
            # CRITICAL: Emit rendererChanged signal to force QGIS Layer Styling panel to update
            try:
                layer.rendererChanged.emit()
                if log_callback:
                    log_callback(f"Emitted rendererChanged signal for range update")
            except Exception as e:
                if log_callback:
                    log_callback(f"Error emitting rendererChanged: {str(e)}")
            
            if log_callback:
                log_callback(f"Range visibility update complete")
            
            return True, layer
            
        except Exception as e:
            import traceback
            if log_callback:
                error_msg = f"ERROR in update_range_visibility: {str(e)}\n{traceback.format_exc()}"
                log_callback(error_msg)
            return False, None
    
    @staticmethod
    def update_rule_visibility(layer_id, rule_key, visible, iface, log_callback=None):
        """
        Update visibility of a rule-based renderer rule.
        
        Args:
            layer_id: Layer ID
            rule_key: Key of the rule to update
            visible: True to show, False to hide
            iface: QGIS interface object
            log_callback: Optional callback function for logging
        
        Returns:
            tuple: (success: bool, layer: QgsVectorLayer or None)
        """
        try:
            if log_callback:
                log_callback(f"update_rule_visibility: rule_key={rule_key}, visible={visible}")
            
            project = QgsProject.instance()
            layer = project.mapLayer(layer_id)
            
            if not layer:
                if log_callback:
                    log_callback(f"ERROR: Layer not found: {layer_id}")
                return False, None
                
            if not isinstance(layer, QgsVectorLayer):
                if log_callback:
                    log_callback(f"ERROR: Layer is not a vector layer")
                return False, None
            
            renderer = layer.renderer()
            if not isinstance(renderer, QgsRuleBasedRenderer):
                if log_callback:
                    log_callback(f"ERROR: Renderer is not rule-based: {type(renderer)}")
                return False, None
            
            # Find and update the rule
            root_rule = renderer.rootRule()
            rule = root_rule.findRuleByKey(rule_key)
            if not rule:
                if log_callback:
                    log_callback(f"ERROR: Rule with key={rule_key} not found")
                return False, None
            
            rule.setActive(visible)
            if log_callback:
                log_callback(f"Updated rule '{rule.label()}' to active={visible}")
            
            # Trigger updates - emit rendererChanged to force styling panel update
            layer.triggerRepaint()
            iface.layerTreeView().refreshLayerSymbology(layer.id())
            
            # CRITICAL: Emit rendererChanged signal to force QGIS Layer Styling panel to update
            try:
                layer.rendererChanged.emit()
                if log_callback:
                    log_callback(f"Emitted rendererChanged signal for rule update")
            except Exception as e:
                if log_callback:
                    log_callback(f"Error emitting rendererChanged: {str(e)}")
            
            if log_callback:
                log_callback(f"Rule visibility update complete")
            
            return True, layer
                    
        except Exception as e:
            import traceback
            if log_callback:
                error_msg = f"ERROR in update_rule_visibility: {str(e)}\n{traceback.format_exc()}"
                log_callback(error_msg)
            return False, None
    
    @staticmethod
    def reactivate_layer_if_active(layer, iface, log_callback=None):
        """
        Reactivate a layer if it's currently active to trigger layer styling panel refresh.
        Uses deselect/reselect approach to force styling panel update.
        
        Args:
            layer: QgsVectorLayer to reactivate
            iface: QGIS interface object
            log_callback: Optional callback function for logging
        """
        try:
            current_layer = iface.activeLayer()
            if current_layer and layer and current_layer.id() == layer.id():
                # Deselect and reselect to force styling panel refresh
                if log_callback:
                    log_callback(f"Deselecting and reselecting layer to force styling panel refresh")
                
                # First set to None to deselect
                iface.setActiveLayer(None)
                
                # Add a small delay to ensure the deselection is processed
                from qgis.PyQt.QtCore import QTimer
                QTimer.singleShot(50, lambda: iface.setActiveLayer(layer))
                
                if log_callback:
                    log_callback(f"Layer reactivation scheduled")
            else:
                if log_callback:
                    log_callback(f"Layer is not currently active, no reactivation needed")
        except Exception as e:
            if log_callback:
                log_callback(f"Error reactivating layer: {str(e)}")
    
    @staticmethod
    def update_symbology_checkboxes_for_layer(layer, tree_widget, log_callback=None):
        """
        Update symbology checkbox states for a specific layer without rebuilding the tree.
        
        Args:
            layer: QgsVectorLayer whose symbology checkboxes to update
            tree_widget: QTreeWidget containing the layer tree
            log_callback: Optional callback function for logging
        
        Returns:
            bool: True if successful, False otherwise
        """
        from qgis.PyQt.QtCore import Qt
        
        try:
            if log_callback:
                log_callback(f"Updating symbology checkboxes for layer: {layer.name()}")
            
            # Find the tree item for this layer
            layer_item = SymbologyService._find_layer_item(layer.id(), tree_widget)
            
            if not layer_item:
                if log_callback:
                    log_callback(f"Layer item not found in tree")
                return False
            
            # Update symbology child items
            renderer = layer.renderer()
            
            if isinstance(renderer, QgsCategorizedSymbolRenderer):
                SymbologyService._update_category_checkboxes(layer_item, renderer, log_callback)
            
            elif isinstance(renderer, QgsGraduatedSymbolRenderer):
                SymbologyService._update_range_checkboxes(layer_item, renderer, log_callback)
            
            elif isinstance(renderer, QgsRuleBasedRenderer):
                # For rule-based, return False to trigger full refresh
                if log_callback:
                    log_callback("Rule-based renderer detected - needs full refresh")
                return False
            
            return True
                    
        except Exception as e:
            import traceback
            if log_callback:
                error_msg = f"ERROR in update_symbology_checkboxes_for_layer: {str(e)}\n{traceback.format_exc()}"
                log_callback(error_msg)
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
    def _update_category_checkboxes(layer_item, renderer, log_callback):
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
                        if log_callback:
                            log_callback(f"Updated category {category_index} checkbox to {new_state}")
    
    @staticmethod
    def _update_range_checkboxes(layer_item, renderer, log_callback):
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
                        if log_callback:
                            log_callback(f"Updated range {range_index} checkbox to {new_state}")

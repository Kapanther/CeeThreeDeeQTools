"""
Service for handling layer and group selection in QGIS layer tree.
"""

from qgis.core import QgsProject


class SelectionService:
    """Handles selection synchronization between LayersAdvanced and QGIS layer tree."""
    
    @staticmethod
    def select_layer_in_qgis(layer, iface, log_callback=None):
        """
        Select a layer in QGIS layer tree view and set as active.
        
        Args:
            layer: QgsVectorLayer to select
            iface: QGIS interface object
            log_callback: Optional callback function for logging
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Set as active layer
            iface.setActiveLayer(layer)
            
            # Also select it in the QGIS layer tree view
            layer_tree_view = iface.layerTreeView()
            layer_tree_model = layer_tree_view.model()
            
            # Get the source model if it's a proxy model
            if hasattr(layer_tree_model, 'sourceModel'):
                source_model = layer_tree_model.sourceModel()
            else:
                source_model = layer_tree_model
            
            root = QgsProject.instance().layerTreeRoot()
            layer_node = root.findLayer(layer)
            if layer_node:
                index = source_model.node2index(layer_node)
                # Map back to proxy model if needed
                if hasattr(layer_tree_model, 'mapFromSource'):
                    index = layer_tree_model.mapFromSource(index)
                layer_tree_view.setCurrentIndex(index)
                if log_callback:
                    log_callback(f"Selected layer in QGIS panel: {layer.name()}")
                return True
            
            return False
            
        except Exception as e:
            if log_callback:
                log_callback(f"Error selecting layer in QGIS panel: {str(e)}")
            return False
    
    @staticmethod
    def select_group_in_qgis(group_name, iface, log_callback=None):
        """
        Select a group in QGIS layer tree view.
        
        Args:
            group_name: Name of the group to select
            iface: QGIS interface object
            log_callback: Optional callback function for logging
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Select the group in QGIS layer tree view
            layer_tree_view = iface.layerTreeView()
            layer_tree_model = layer_tree_view.model()
            
            # Get the source model if it's a proxy model
            if hasattr(layer_tree_model, 'sourceModel'):
                source_model = layer_tree_model.sourceModel()
            else:
                source_model = layer_tree_model
            
            root = QgsProject.instance().layerTreeRoot()
            group_node = root.findGroup(group_name)
            if group_node:
                index = source_model.node2index(group_node)
                # Map back to proxy model if needed
                if hasattr(layer_tree_model, 'mapFromSource'):
                    index = layer_tree_model.mapFromSource(index)
                layer_tree_view.setCurrentIndex(index)
                if log_callback:
                    log_callback(f"Selected group in QGIS panel: {group_name}")
                return True
            
            return False
            
        except Exception as e:
            if log_callback:
                log_callback(f"Error selecting group in QGIS panel: {str(e)}")
            return False

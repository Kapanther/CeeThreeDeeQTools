"""
Service for handling layer and group movement operations.
"""

from qgis.core import QgsProject


class LayerOperationsService:
    """Handles layer and group movement operations in the QGIS layer tree."""
    
    @staticmethod
    def move_layer_up(layer_id):
        """
        Move a layer up in the layer order.
        
        Args:
            layer_id: ID of the layer to move
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            project = QgsProject.instance()
            root = project.layerTreeRoot()
            
            # Find the layer node in the tree
            layer_node = root.findLayer(layer_id)
            if not layer_node:
                return False
            
            # Get parent and current index
            parent = layer_node.parent()
            if not parent:
                return False
            
            children = parent.children()
            current_index = children.index(layer_node)
            
            # Move up if not already at top
            if current_index > 0:
                cloned = layer_node.clone()
                parent.insertChildNode(current_index - 1, cloned)
                parent.removeChildNode(layer_node)
                return True
            
            return False
            
        except Exception:
            return False
    
    @staticmethod
    def move_layer_down(layer_id):
        """
        Move a layer down in the layer order.
        
        Args:
            layer_id: ID of the layer to move
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            project = QgsProject.instance()
            root = project.layerTreeRoot()
            
            # Find the layer node in the tree
            layer_node = root.findLayer(layer_id)
            if not layer_node:
                return False
            
            # Get parent and current index
            parent = layer_node.parent()
            if not parent:
                return False
            
            children = parent.children()
            current_index = children.index(layer_node)
            
            # Move down if not already at bottom
            if current_index < len(children) - 1:
                cloned = layer_node.clone()
                parent.insertChildNode(current_index + 2, cloned)
                parent.removeChildNode(layer_node)
                return True
            
            return False
            
        except Exception:
            return False
    
    @staticmethod
    def move_group_up(group_name):
        """
        Move a group up in the layer order.
        
        Args:
            group_name: Name of the group to move
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            project = QgsProject.instance()
            root = project.layerTreeRoot()
            
            group_node = root.findGroup(group_name)
            if not group_node:
                return False
            
            # Get parent and current index
            parent = group_node.parent()
            if not parent:
                return False
            
            children = parent.children()
            current_index = children.index(group_node)
            
            # Move up if not already at top
            if current_index > 0:
                cloned = group_node.clone()
                parent.insertChildNode(current_index - 1, cloned)
                # After inserting, original is now at current_index + 1
                parent.removeChildNode(parent.children()[current_index + 1])
                return True
            
            return False
            
        except Exception:
            return False
    
    @staticmethod
    def move_group_down(group_name):
        """
        Move a group down in the layer order.
        
        Args:
            group_name: Name of the group to move
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            project = QgsProject.instance()
            root = project.layerTreeRoot()
            
            group_node = root.findGroup(group_name)
            if not group_node:
                return False
            
            # Get parent and current index
            parent = group_node.parent()
            if not parent:
                return False
            
            children = parent.children()
            current_index = children.index(group_node)
            
            # Move down if not already at bottom
            if current_index < len(children) - 1:
                cloned = group_node.clone()
                parent.insertChildNode(current_index + 2, cloned)
                parent.removeChildNode(parent.children()[current_index])
                return True
            
            return False
            
        except Exception:
            return False
    
    @staticmethod
    def set_group_visibility_recursive(group_node, visible):
        """
        Recursively set visibility for all layers in a group.
        
        Args:
            group_node: QgsLayerTreeGroup node
            visible: True to show, False to hide
        """
        from qgis.core import QgsLayerTreeLayer
        
        try:
            # Set the group's visibility
            group_node.setItemVisibilityChecked(visible)
            
            # Set visibility for all children
            for child in group_node.children():
                if isinstance(child, QgsLayerTreeLayer):
                    child.setItemVisibilityChecked(visible)
                else:
                    # Recursively handle nested groups
                    LayerOperationsService.set_group_visibility_recursive(child, visible)
        except Exception:
            pass

"""
Service for handling layer tree reordering operations including drag-and-drop.
"""

from qgis.core import (
    QgsProject,
    QgsLayerTreeGroup
)
from qgis.PyQt.QtCore import Qt


class TreeReorderingService:
    """Static service for applying tree reordering from widget to QGIS layer tree."""
    
    @staticmethod
    def apply_tree_reordering(layer_tree_widget, root_node):
        """
        Apply the visual tree reordering to the actual QGIS layer tree.
        
        Args:
            layer_tree_widget: The QTreeWidget with the desired structure
            root_node: The QGIS layer tree root node
        """
        TreeReorderingService._apply_tree_structure(
            layer_tree_widget.invisibleRootItem(),
            root_node
        )
    
    @staticmethod
    def _apply_tree_structure(widget_parent, qgis_parent):
        """
        Recursively apply tree structure from widget to QGIS layer tree.
        Uses the same clone-insert-remove pattern as move_layer_up/down.
        
        Args:
            widget_parent: Parent tree widget item
            qgis_parent: Parent QGIS layer tree node
        """
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        
        # Collect widget structure at this level (only layers and groups, skip symbology items)
        widget_structure = []
        for i in range(widget_parent.childCount()):
            child = widget_parent.child(i)
            item_type = child.data(0, Qt.UserRole + 1)
            item_id = child.data(0, Qt.UserRole)
            
            # Only process actual QGIS tree nodes (layers and groups), skip symbology items
            if item_type == "layer":
                widget_structure.append(("layer", item_id, child))
            elif item_type == "group":
                widget_structure.append(("group", item_id, child))
            elif item_type in ("category", "range", "rule"):
                pass  # Skip symbology items silently
        
        if not widget_structure:
            return
        
        # FIRST: Recursively process all group children (bottom-up approach)
        for item_type, item_id, widget_child in widget_structure:
            if item_type == "group":
                group_node = root.findGroup(item_id)
                if group_node and isinstance(group_node, QgsLayerTreeGroup):
                    TreeReorderingService._apply_tree_structure(widget_child, group_node)
        
        # NOW: Reorder nodes at this level using the proven clone-insert-remove pattern
        # Process in reverse order to avoid index shifting issues
        desired_nodes = []
        for item_type, item_id, widget_child in widget_structure:
            if item_type == "layer":
                layer_node = root.findLayer(item_id)
                if layer_node:
                    desired_nodes.append((layer_node, item_id, item_type))
            elif item_type == "group":
                group_node = root.findGroup(item_id)
                if group_node:
                    desired_nodes.append((group_node, item_id, item_type))
        
        # Process each node and move if needed
        # We need to process from the end backwards to avoid index shifting
        for target_index in range(len(desired_nodes) - 1, -1, -1):
            node, item_id, item_type = desired_nodes[target_index]
            
            # Re-find the node to get current position (it may have moved)
            if item_type == "layer":
                current_node = root.findLayer(item_id)
            else:
                current_node = root.findGroup(item_id)
            
            if not current_node:
                continue
            
            current_parent = current_node.parent()
            
            # Check if already at correct position
            if current_parent == qgis_parent:
                current_children = qgis_parent.children()
                if target_index < len(current_children) and current_children[target_index] == current_node:
                    continue
            
            # Move the node using clone-insert-remove pattern
            # IMPORTANT: Store reference to original node BEFORE cloning
            original_node = current_node
            original_parent = current_parent
            
            # Clone and insert
            cloned = current_node.clone()
            qgis_parent.insertChildNode(target_index, cloned)
            
            # Remove the original using the stored reference (NOT by searching)
            if original_parent:
                original_parent.removeChildNode(original_node)

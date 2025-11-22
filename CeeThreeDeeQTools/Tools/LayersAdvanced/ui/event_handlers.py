"""
Event handlers for LayersAdvanced dialog interactions.
"""

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QTreeWidgetItem, QLineEdit


class EventHandlers:
    """Handlers for UI events in the LayersAdvanced dialog."""
    
    @staticmethod
    def handle_item_double_click(dialog, item, column):
        """Handle double-click on tree item to start renaming."""
        if column == 0:  # Only allow renaming in name column
            dialog.start_rename_item(item)
    
    @staticmethod
    def handle_f2_key_press(dialog, event):
        """Handle F2 key press to start renaming."""
        from qgis.PyQt.QtCore import Qt, QEvent
        
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_F2:
            selected = dialog.layer_tree.selectedItems()
            if len(selected) == 1:
                dialog.start_rename_item(selected[0])
                return True
        return False
    
    @staticmethod
    def start_rename(dialog, item):
        """
        Start renaming a layer or group.
        
        Args:
            dialog: The LayersAdvancedDialog instance
            item: The tree item to rename
        """
        item_type = item.data(0, Qt.UserRole + 1)
        
        # Only allow renaming layers and groups, not symbology items
        if item_type in ("layer", "group"):
            # Store original name and enable editing
            item.setData(0, Qt.UserRole + 2, item.text(0))  # Store original name
            
            # Disconnect the itemChanged signal temporarily
            try:
                dialog.layer_tree.itemChanged.disconnect(dialog.on_item_visibility_changed)
            except (TypeError, RuntimeError):
                pass
            
            # Make item editable and start editing
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            dialog.layer_tree.editItem(item, 0)
            
            # Reconnect when done
            dialog.layer_tree.itemChanged.connect(dialog.on_item_name_changed)
    
    @staticmethod
    def finish_rename(dialog, item, column):
        """
        Finish renaming a layer or group and apply to QGIS.
        
        Args:
            dialog: The LayersAdvancedDialog instance
            item: The tree item that was renamed
            column: The column that was edited
        """
        if column != 0:
            return
        
        # Disconnect rename signal
        try:
            dialog.layer_tree.itemChanged.disconnect(dialog.on_item_name_changed)
        except (TypeError, RuntimeError):
            pass
        
        # Make item non-editable again
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        
        # Reconnect normal signal
        dialog.layer_tree.itemChanged.connect(dialog.on_item_visibility_changed)
        
        # Get the new name and item info
        new_name = item.text(0)
        original_name = item.data(0, Qt.UserRole + 2)
        item_type = item.data(0, Qt.UserRole + 1)
        item_id = item.data(0, Qt.UserRole)
        
        # If name didn't change, nothing to do
        if new_name == original_name or not new_name.strip():
            item.setText(0, original_name)
            return
        
        # Apply the rename to QGIS
        project = QgsProject.instance()
        
        if item_type == "layer":
            layer = project.mapLayer(item_id)
            if layer:
                layer.setName(new_name)
        elif item_type == "group":
            root = project.layerTreeRoot()
            group_node = root.findGroup(item_id)
            if group_node:
                group_node.setName(new_name)
                # Update the item_id since group names are used as IDs
                item.setData(0, Qt.UserRole, new_name)
    
    @staticmethod
    def handle_show_all(dialog):
        """Handle Show All button click."""
        from ..services.visibility_service import VisibilityService
        
        selected_items = dialog.layer_tree.selectedItems()
        
        if selected_items:
            # Show only selected items
            for item in selected_items:
                item_type = item.data(0, Qt.UserRole + 1)
                if item_type in ("layer", "group"):
                    dialog.toggle_selected_visibility(True)
        else:
            # Show all layers
            root_item = dialog.layer_tree.invisibleRootItem()
            for i in range(root_item.childCount()):
                child = root_item.child(i)
                item_type = child.data(0, Qt.UserRole + 1)
                if item_type == "layer" or item_type == "group":
                    child.setCheckState(0, Qt.Checked)
    
    @staticmethod
    def handle_hide_all(dialog):
        """Handle Hide All button click."""
        from ..services.visibility_service import VisibilityService
        
        selected_items = dialog.layer_tree.selectedItems()
        
        if selected_items:
            # Hide only selected items
            for item in selected_items:
                item_type = item.data(0, Qt.UserRole + 1)
                if item_type in ("layer", "group"):
                    dialog.toggle_selected_visibility(False)
        else:
            # Hide all layers
            root_item = dialog.layer_tree.invisibleRootItem()
            for i in range(root_item.childCount()):
                child = root_item.child(i)
                item_type = child.data(0, Qt.UserRole + 1)
                if item_type == "layer" or item_type == "group":
                    child.setCheckState(0, Qt.Unchecked)

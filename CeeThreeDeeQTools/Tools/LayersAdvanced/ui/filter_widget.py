"""
Service for filtering/searching tree items.
"""

from qgis.PyQt.QtCore import Qt


class FilterService:
    """Static service for filtering tree widget items."""
    
    @staticmethod
    def filter_tree(tree_widget, search_text):
        """
        Filter tree items based on search text.
        
        Args:
            tree_widget: The QTreeWidget to filter
            search_text: Text to search for (case-insensitive)
            
        Returns:
            Tuple of (total_layers, hidden_layers) counts
        """
        search_lower = search_text.lower()
        
        # If no search text, show everything
        if not search_text:
            FilterService._show_all_items(tree_widget.invisibleRootItem())
            total_count = FilterService._count_layers(tree_widget.invisibleRootItem())
            return (total_count, 0)
        
        # Hide items that don't match, show those that do
        FilterService._filter_item_recursive(tree_widget.invisibleRootItem(), search_lower)
        
        # Count total and hidden layers
        total_count = FilterService._count_layers(tree_widget.invisibleRootItem())
        hidden_count = FilterService._count_hidden_layers(tree_widget.invisibleRootItem())
        
        return (total_count, hidden_count)
    
    @staticmethod
    def _filter_item_recursive(parent_item, search_text):
        """
        Recursively filter items in the tree.
        
        Args:
            parent_item: Parent tree widget item
            search_text: Lowercase search text
            
        Returns:
            True if this item or any child matches, False otherwise
        """
        has_visible_child = False
        
        # Process all children first
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child_matches = FilterService._filter_item_recursive(child, search_text)
            if child_matches:
                has_visible_child = True
        
        # Check if this item matches
        if parent_item != parent_item.treeWidget().invisibleRootItem():
            item_text = parent_item.text(0).lower()
            item_matches = search_text in item_text
            
            # Show item if it matches or has visible children
            should_show = item_matches or has_visible_child
            parent_item.setHidden(not should_show)
            
            return should_show
        
        return has_visible_child
    
    @staticmethod
    def _show_all_items(parent_item):
        """
        Recursively show all items in the tree.
        
        Args:
            parent_item: Parent tree widget item
        """
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child.setHidden(False)
            FilterService._show_all_items(child)
    
    @staticmethod
    def _count_layers(parent_item):
        """
        Recursively count all layer items (not groups) in the tree.
        
        Args:
            parent_item: Parent tree widget item
            
        Returns:
            Count of layer items
        """
        count = 0
        
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            item_type = child.data(0, Qt.UserRole + 1)
            
            # Only count actual layers, not groups or symbology items
            if item_type == "layer":
                count += 1
            
            # Recurse into children (groups)
            count += FilterService._count_layers(child)
        
        return count
    
    @staticmethod
    def _count_hidden_layers(parent_item):
        """
        Recursively count hidden layer items (not groups) in the tree.
        
        Args:
            parent_item: Parent tree widget item
            
        Returns:
            Count of hidden layer items
        """
        count = 0
        
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            item_type = child.data(0, Qt.UserRole + 1)
            
            # Only count hidden actual layers, not groups or symbology items
            if item_type == "layer" and child.isHidden():
                count += 1
            
            # Recurse into children (groups)
            count += FilterService._count_hidden_layers(child)
        
        return count

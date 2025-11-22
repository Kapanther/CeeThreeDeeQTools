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
        """
        search_lower = search_text.lower()
        
        # If no search text, show everything
        if not search_text:
            FilterService._show_all_items(tree_widget.invisibleRootItem())
            return
        
        # Hide items that don't match, show those that do
        FilterService._filter_item_recursive(tree_widget.invisibleRootItem(), search_lower)
    
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

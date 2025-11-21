"""Service for managing layer visibility."""

from qgis.core import QgsProject, QgsMapLayer


class VisibilityService:
    """Handles layer visibility operations."""
    
    @staticmethod
    def is_layer_visible(layer: QgsMapLayer) -> bool:
        """Check if a layer is currently visible in the map canvas."""
        try:
            project = QgsProject.instance()
            root = project.layerTreeRoot()
            layer_tree_layer = root.findLayer(layer.id())
            
            if layer_tree_layer:
                return layer_tree_layer.isVisible()
        except Exception:
            pass
        
        return False
    
    @staticmethod
    def set_layer_visibility(layer_id: str, visible: bool):
        """Set the visibility of a layer."""
        try:
            project = QgsProject.instance()
            root = project.layerTreeRoot()
            layer_tree_layer = root.findLayer(layer_id)
            
            if layer_tree_layer:
                layer_tree_layer.setItemVisibilityChecked(visible)
        except Exception as e:
            print(f"Error setting layer visibility: {e}")
    
    @staticmethod
    def set_multiple_layers_visibility(layer_ids: list, visible: bool):
        """
        Set visibility for multiple layers at once.
        
        Args:
            layer_ids: List of layer IDs
            visible: Boolean visibility state
        """
        for layer_id in layer_ids:
            VisibilityService.set_layer_visibility(layer_id, visible)

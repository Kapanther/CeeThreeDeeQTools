"""
Service for managing QGIS signal connections and disconnections.
"""

from qgis.core import QgsProject


class SignalManagerService:
    """Static service for managing signal connections to QGIS."""
    
    @staticmethod
    def connect_project_signals(dialog):
        """
        Connect to project-level QGIS signals.
        
        Args:
            dialog: The LayersAdvancedDialog instance with signal handlers
        """
        project = QgsProject.instance()
        
        # Project signals - refresh when layers added/removed
        try:
            project.layersAdded.connect(dialog.refresh_layers)
        except (TypeError, RuntimeError):
            pass
        
        try:
            project.layersRemoved.connect(dialog.refresh_layers)
        except (TypeError, RuntimeError):
            pass
        
        # Connect signals for newly added layers
        try:
            project.layersAdded.connect(dialog.connect_layer_signals)
        except (TypeError, RuntimeError):
            pass
        
        try:
            project.cleared.connect(dialog.on_project_loaded)
        except (TypeError, RuntimeError):
            pass
        
        try:
            project.readProject.connect(dialog.on_project_loaded)
        except (TypeError, RuntimeError):
            pass
        
        # Layer tree signals
        root = project.layerTreeRoot()
        try:
            root.addedChildren.connect(dialog.on_layer_tree_children_changed)
        except (TypeError, RuntimeError):
            pass
        
        try:
            root.removedChildren.connect(dialog.on_layer_tree_children_changed)
        except (TypeError, RuntimeError):
            pass
        
        # Connect to visibility changes - this catches changes from QLP
        try:
            root.visibilityChanged.connect(dialog.on_qgis_visibility_changed)
        except (TypeError, RuntimeError):
            pass
        
        # Also connect to individual layer node visibility changes recursively
        SignalManagerService._connect_node_visibility_recursive(dialog, root)
        
        # Active layer changed
        try:
            dialog.iface.layerTreeView().currentLayerChanged.connect(dialog.on_qgis_active_layer_changed)
        except (TypeError, RuntimeError):
            pass
    
    @staticmethod
    def connect_layer_signals(dialog, layers):
        """
        Connect to layer-specific signals (renderer changes, etc.).
        
        Args:
            dialog: The LayersAdvancedDialog instance with signal handlers
            layers: List of QgsMapLayer instances
        """
        for layer in layers:
            try:
                layer.rendererChanged.connect(dialog.on_renderer_changed)
                if hasattr(dialog, 'log_debug'):
                    dialog.log_debug(f"✓ Connected rendererChanged for layer: {layer.name()} (type: {type(layer).__name__})")
            except (TypeError, RuntimeError, AttributeError) as e:
                if hasattr(dialog, 'log_debug'):
                    dialog.log_debug(f"✗ Failed to connect rendererChanged for layer: {layer.name()} - {e}")
            
            try:
                layer.styleChanged.connect(dialog.on_layer_changed)
                if hasattr(dialog, 'log_debug'):
                    dialog.log_debug(f"✓ Connected styleChanged for layer: {layer.name()}")
            except (TypeError, RuntimeError, AttributeError) as e:
                if hasattr(dialog, 'log_debug'):
                    dialog.log_debug(f"✗ Failed to connect styleChanged for layer: {layer.name()} - {e}")
            
            # Connect to legendChanged - fires when symbology checkboxes are toggled
            try:
                layer.legendChanged.connect(dialog.on_legend_changed)
                if hasattr(dialog, 'log_debug'):
                    dialog.log_debug(f"✓ Connected legendChanged for layer: {layer.name()}")
            except (TypeError, RuntimeError, AttributeError) as e:
                if hasattr(dialog, 'log_debug'):
                    dialog.log_debug(f"✗ Failed to connect legendChanged for layer: {layer.name()} - {e}")
    
    @staticmethod
    def disconnect_tree_signals(root):
        """
        Temporarily disconnect layer tree signals.
        
        Args:
            root: QGIS layer tree root node
            
        Returns:
            True if signals were disconnected, False otherwise
        """
        try:
            root.addedChildren.disconnect()
            root.removedChildren.disconnect()
            return True
        except (TypeError, RuntimeError):
            return False
    
    @staticmethod
    def reconnect_tree_signals(dialog, root):
        """
        Reconnect layer tree signals after temporary disconnection.
        
        Args:
            dialog: The LayersAdvancedDialog instance with signal handlers
            root: QGIS layer tree root node
        """
        try:
            root.addedChildren.connect(dialog.on_layer_tree_children_changed)
            root.removedChildren.connect(dialog.on_layer_tree_children_changed)
        except (TypeError, RuntimeError):
            pass
    
    @staticmethod
    def _connect_node_visibility_recursive(dialog, node):
        """
        Recursively connect visibility signals for all layer tree nodes.
        
        Args:
            dialog: The LayersAdvancedDialog instance
            node: QgsLayerTreeNode to process
        """
        # Connect to visibilityChanged (when visibility state changes programmatically)
        try:
            node.visibilityChanged.connect(dialog.on_qgis_visibility_changed)
        except (TypeError, RuntimeError, AttributeError):
            pass
        
        # IMPORTANT: Also connect to itemVisibilityCheckedChanged 
        # This fires when user checks/unchecks in QLP
        try:
            node.itemVisibilityCheckedChanged.connect(dialog.on_qgis_visibility_changed)
        except (TypeError, RuntimeError, AttributeError):
            pass
        
        # Recursively process children
        if hasattr(node, 'children'):
            for child in node.children():
                SignalManagerService._connect_node_visibility_recursive(dialog, child)

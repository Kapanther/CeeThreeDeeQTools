"""
***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""

from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QPushButton,
    QLabel,
    QCheckBox,
    QLineEdit,
    QMenu,
    QTextEdit,
    QToolBar,
    QAction
)
from qgis.PyQt.QtCore import Qt, pyqtSignal, QSettings, QEvent
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsProject, 
    QgsMapLayer, 
    QgsVectorLayer, 
    QgsRasterLayer,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsCategorizedSymbolRenderer,
    QgsGraduatedSymbolRenderer,
    QgsRuleBasedRenderer,
    QgsRendererCategory,
    QgsRendererRange
)
from .services.layer_service import LayerService
from .services.visibility_service import VisibilityService
from .services.symbology_service import SymbologyService
from .services.selection_service import SelectionService
from .services.layer_operations_service import LayerOperationsService
from .services.tree_reordering_service import TreeReorderingService
from .services.signal_manager_service import SignalManagerService
from .ui.layer_tree_builder import LayerTreeBuilder
from .ui.context_menu import LayerContextMenu
from .ui.event_handlers import EventHandlers
from .ui.filter_widget import FilterService
import os


class DraggableTreeWidget(QTreeWidget):
    """Custom QTreeWidget that emits a signal after drag-and-drop operations."""
    
    dropCompleted = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def dropEvent(self, event):
        """Override dropEvent to detect when items are dropped."""
        # Let Qt handle the drop first
        super().dropEvent(event)
        
        # Emit signal after a short delay to allow Qt to finish processing
        from qgis.PyQt.QtCore import QTimer
        QTimer.singleShot(100, self.dropCompleted.emit)


class LayersAdvancedDialog(QDockWidget):
    """
    Dockable widget for advanced layer management and information display.
    """
    
    # Signals
    layerVisibilityChanged = pyqtSignal(str, bool)  # layer_id, visible
    layerSelected = pyqtSignal(str)  # layer_id
    
    def __init__(self, iface, parent=None):
        super().__init__("Layers Advanced", parent)
        self.iface = iface
        
        # Set object name for QGIS to save/restore dock state automatically
        self.setObjectName("CeeThreeDeeQToolsLayersAdvanced")
        
        # Allow docking on left or right side
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        
        # Flag to prevent refresh during visibility updates
        self._updating_visibility = False
        
        # Flag to prevent circular selection updates
        self._updating_selection = False
        
        # Create the main widget
        main_widget = QWidget()
        self.setWidget(main_widget)
        
        # Setup UI
        self.init_ui(main_widget)
        
        # Connect to QGIS project signals
        self.connect_project_signals()
        
        # Connect signals for existing layers
        self.connect_existing_layer_signals()
        
        # Initial load of layers
        self.refresh_layers()
    
    def init_ui(self, main_widget):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        main_widget.setLayout(layout)
        
        # Title and refresh button
        title_layout = QHBoxLayout()
        title_label = QLabel("<h3>Layers Advanced</h3>")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setToolTip("Refresh the layer list")
        refresh_btn.clicked.connect(self.refresh_layers)
        title_layout.addWidget(refresh_btn)
        
        layout.addLayout(title_layout)
        
        # Toolbar
        toolbar = QToolBar()
        # Set icon size to 80% of default
        default_size = toolbar.iconSize()
        toolbar.setIconSize(default_size * 0.8)
        # Only show icons, not text
        toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        
        # Expand All Groups action
        expand_action = QAction(QIcon(":/images/themes/default/mActionExpandTree.svg"), "Expand All Groups", self)
        expand_action.setToolTip("Expand all groups")
        expand_action.triggered.connect(self.expand_all_groups)
        toolbar.addAction(expand_action)
        
        # Collapse All Groups action
        collapse_action = QAction(QIcon(":/images/themes/default/mActionCollapseTree.svg"), "Collapse All Groups", self)
        collapse_action.setToolTip("Collapse all groups")
        collapse_action.triggered.connect(self.collapse_all_groups)
        toolbar.addAction(collapse_action)
        
        toolbar.addSeparator()
        
        # Toggle Expand/Collapse All Layers action
        self.toggle_layers_action = QAction(QIcon(":/images/themes/default/mActionExpandNewTree.svg"), "Expand All Layers", self)
        self.toggle_layers_action.setToolTip("Expand/collapse all layers (show/hide symbology)")
        self.toggle_layers_action.triggered.connect(self.toggle_all_layers)
        toolbar.addAction(self.toggle_layers_action)
        
        toolbar.addSeparator()
        
        layout.addWidget(toolbar)
        
        # Filter/search box
        search_layout = QHBoxLayout()
        search_label = QLabel("Filter:")
        search_layout.addWidget(search_label)
        
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search layers...")
        self.search_box.textChanged.connect(self.filter_layers)
        search_layout.addWidget(self.search_box)
        
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.search_box.clear)
        search_layout.addWidget(clear_btn)
        
        layout.addLayout(search_layout)
        
        # Layer tree widget
        self.layer_tree = DraggableTreeWidget()
        self.layer_tree.setHeaderLabels(["Layer Name", "Type", "Features/Size", "CRS", "File Type", "File Size", "Source"])
        self.layer_tree.setColumnWidth(0, 200)
        self.layer_tree.setColumnWidth(1, 80)
        self.layer_tree.setColumnWidth(2, 100)
        self.layer_tree.setColumnWidth(3, 80)
        self.layer_tree.setColumnWidth(4, 80)
        self.layer_tree.setColumnWidth(5, 80)
        self.layer_tree.setColumnWidth(6, 150)
        self.layer_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.layer_tree.customContextMenuRequested.connect(self.show_context_menu)
        self.layer_tree.itemChanged.connect(self.on_item_visibility_changed)
        self.layer_tree.itemSelectionChanged.connect(self.on_item_selected)
        
        # Enable multi-selection with Ctrl and Shift
        self.layer_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        
        # Enable drag and drop for reordering
        self.layer_tree.setDragEnabled(True)
        self.layer_tree.setAcceptDrops(True)
        self.layer_tree.setDragDropMode(QTreeWidget.InternalMove)
        self.layer_tree.setDefaultDropAction(Qt.MoveAction)
        
        # Connect drop completed signal
        self.layer_tree.dropCompleted.connect(self.on_drop_completed)
        
        # Enable editing for layer name column (column 0)
        self.layer_tree.setEditTriggers(QTreeWidget.NoEditTriggers)  # Disable default triggers
        self.layer_tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        
        # Install event filter for F2 key
        self.layer_tree.installEventFilter(self)
        
        # Enable header context menu for column visibility
        header = self.layer_tree.header()
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self.show_header_context_menu)
        
        # Restore column visibility settings
        self.restore_column_visibility()
        
        layout.addWidget(self.layer_tree)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        self.show_all_btn = QPushButton("Show All")
        self.show_all_btn.setToolTip("Show all layers (or selected layers if any are selected)")
        self.show_all_btn.clicked.connect(self.show_all_layers)
        button_layout.addWidget(self.show_all_btn)
        
        self.hide_all_btn = QPushButton("Hide All")
        self.hide_all_btn.setToolTip("Hide all layers (or selected layers if any are selected)")
        self.hide_all_btn.clicked.connect(self.hide_all_layers)
        button_layout.addWidget(self.hide_all_btn)
        
        button_layout.addStretch()
        
        # Layer reordering buttons
        self.move_up_btn = QPushButton("Move Up")
        self.move_up_btn.setIcon(QIcon(":/images/themes/default/mActionArrowUp.svg"))
        self.move_up_btn.clicked.connect(self.move_layer_up)
        button_layout.addWidget(self.move_up_btn)
        
        self.move_down_btn = QPushButton("Move Down")
        self.move_down_btn.setIcon(QIcon(":/images/themes/default/mActionArrowDown.svg"))
        self.move_down_btn.clicked.connect(self.move_layer_down)
        button_layout.addWidget(self.move_down_btn)
        
        layout.addLayout(button_layout)
        
        # Info label
        self.info_label = QLabel("Total layers: 0")
        layout.addWidget(self.info_label)
        
        # Filter info label (shows filtered count)
        self.filter_info_label = QLabel("")
        self.filter_info_label.setStyleSheet("color: #FF6B35; font-weight: bold;")  # Orange color for visibility
        self.filter_info_label.setVisible(False)  # Hidden by default
        layout.addWidget(self.filter_info_label)
        
        # Debug console
        debug_layout = QVBoxLayout()
        debug_header = QHBoxLayout()
        debug_label = QLabel("<b>Debug Console:</b>")
        debug_header.addWidget(debug_label)
        
        clear_debug_btn = QPushButton("Clear")
        clear_debug_btn.setMaximumWidth(60)
        clear_debug_btn.clicked.connect(self.clear_debug)
        debug_header.addWidget(clear_debug_btn)
        
        debug_layout.addLayout(debug_header)
        
        self.debug_console = QTextEdit()
        self.debug_console.setReadOnly(True)
        self.debug_console.setMaximumHeight(100)
        self.debug_console.setStyleSheet("")  # Use default QGIS theme styling
        debug_layout.addWidget(self.debug_console)
        
        layout.addLayout(debug_layout)
        
        # Initial debug message
        self.log_debug("LayersAdvanced panel initialized")
    
    def log_debug(self, message):
        """Add a message to the debug console."""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.debug_console.append(f"[{timestamp}] {message}")
        # Auto-scroll to bottom
        scrollbar = self.debug_console.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def clear_debug(self):
        """Clear the debug console."""
        self.debug_console.clear()
        self.log_debug("Console cleared")
    
    def connect_project_signals(self):
        """Connect to QGIS project signals for automatic updates."""
        SignalManagerService.connect_project_signals(self)
    
    def connect_existing_layer_signals(self):
        """Connect signals for all existing layers in the project."""
        project = QgsProject.instance()
        layers = list(project.mapLayers().values())
        self.log_debug(f"\n=== Connecting signals for {len(layers)} existing layers ===")
        if layers:
            self.connect_layer_signals(layers)
        else:
            self.log_debug("No existing layers to connect")
    
    def on_project_loaded(self):
        """Handle project loaded event - refresh layers after a delay to ensure layers are fully loaded."""
        self.log_debug("\n=== on_project_loaded() called ===")
        # Connect signals for layers in the new project
        self.connect_existing_layer_signals()
        # Use a single-shot timer to refresh after layers are fully loaded
        from qgis.PyQt.QtCore import QTimer
        QTimer.singleShot(100, self.refresh_layers)
    
    def connect_layer_signals(self, layers):
        """Connect to signals for newly added layers."""
        self.log_debug(f"\nconnect_layer_signals() called with {len(layers)} layers")
        SignalManagerService.connect_layer_signals(self, layers)
        # Also connect CRS changes
        for layer in layers:
            try:
                layer.crsChanged.connect(self.on_layer_changed)
            except Exception:
                pass
    
    def on_renderer_changed(self):
        """Handle renderer/symbology changes (e.g., from QGIS layer styling panel)."""
        sender = self.sender()
        self.log_debug(f"\n>>> on_renderer_changed() called! sender={sender.name() if sender else 'None'}, type={type(sender).__name__ if sender else 'None'}")
        self.log_debug(f"    _updating_visibility = {self._updating_visibility}")
        
        if not self._updating_visibility:
            # For rasters, we need to rebuild symbology items (gradient/discrete list changes)
            # For vectors, we can just update checkboxes
            if sender:
                from qgis.core import QgsRasterLayer
                if isinstance(sender, QgsRasterLayer):
                    self.log_debug(f"    → Detected QgsRasterLayer, calling update_layer_symbology_items()")
                    self.update_layer_symbology_items(sender)
                else:
                    self.log_debug(f"    → Detected vector layer, calling update_layer_symbology_checkboxes()")
                    self.update_layer_symbology_checkboxes(sender)
            else:
                self.log_debug(f"    → No sender, calling refresh_layers()")
                self.refresh_layers()
        else:
            self.log_debug(f"    → Skipped (updating_visibility=True)")
    
    def on_legend_changed(self):
        """Handle legend changes - fires when symbology checkboxes are toggled in QLP."""
        if not self._updating_visibility:
            sender = self.sender()
            if sender:
                # Update symbology checkboxes for this layer
                self.update_layer_symbology_checkboxes(sender)
    
    def on_layer_changed(self):
        """Handle layer property changes (like CRS)."""
        # Don't refresh if we're in the middle of updating visibility
        if not self._updating_visibility:
            self.refresh_layers()
    
    def on_layer_tree_children_changed(self, node, index_from, index_to):
        """
        Handle layer tree structure changes (groups added/removed, layers moved).
        
        Args:
            node: The parent node where children changed
            index_from: Starting index of the change
            index_to: Ending index of the change
        """
        if self._updating_visibility:
            return
        
        self.log_debug(f"Layer tree children changed - refreshing (node: {node}, indices: {index_from}-{index_to})")
        self.refresh_layers()
    
    def on_drop_completed(self):
        """Handle completion of drag-and-drop operation."""
        self.apply_tree_reordering()
    
    def apply_tree_reordering(self):
        """Apply the visual tree reordering to the actual QGIS layer tree."""
        try:
            project = QgsProject.instance()
            root = project.layerTreeRoot()
            
            # Temporarily disconnect the layer tree signals to avoid recursive updates
            try:
                root.addedChildren.disconnect(self.on_layer_tree_children_changed)
                root.removedChildren.disconnect(self.on_layer_tree_children_changed)
            except (TypeError, RuntimeError):
                pass
            
            # Apply the tree structure recursively using service
            TreeReorderingService.apply_tree_reordering(self.layer_tree, root)
            
            # Reconnect signals
            try:
                root.addedChildren.connect(self.on_layer_tree_children_changed)
                root.removedChildren.connect(self.on_layer_tree_children_changed)
            except (TypeError, RuntimeError):
                pass
            
            # Refresh to sync with QGIS
            self.refresh_layers()
            
        except Exception as e:
            import traceback
            self.log_debug(f"ERROR in apply_tree_reordering: {str(e)}")
            self.log_debug(traceback.format_exc())
    
    def update_layer_symbology_checkboxes(self, layer):
        """Update symbology checkbox states for a specific layer without rebuilding the tree."""
        # Disconnect itemChanged signal temporarily
        try:
            self.layer_tree.itemChanged.disconnect(self.on_item_visibility_changed)
        except (TypeError, RuntimeError):
            pass
        
        try:
            # Use service to update checkboxes
            success = SymbologyService.update_symbology_checkboxes_for_layer(
                layer, self.layer_tree
            )
            
            # If service returns False (e.g., rule-based renderer), do full refresh
            if not success:
                self.refresh_layers()
                
        finally:
            # Reconnect itemChanged signal
            try:
                self.layer_tree.itemChanged.connect(self.on_item_visibility_changed)
            except (TypeError, RuntimeError):
                pass
    
    def update_layer_symbology_items(self, layer):
        """
        Update symbology child items for a specific raster layer.
        Used when raster renderer/interpolation changes.
        """
        self.log_debug(f"\n=== update_layer_symbology_items() called for {layer.name()} ===")
        self.log_debug(f"    Layer ID: {layer.id()}")
        self.log_debug(f"    Layer type: {type(layer).__name__}")
        
        try:
            # Find the layer item in the tree
            layer_item = self._find_layer_item(layer.id())
            if not layer_item:
                self.log_debug(f"    ✗ Could not find tree item for layer {layer.name()}")
                return
            
            self.log_debug(f"    ✓ Found layer item: {layer_item.text(0)}")
            self.log_debug(f"    Current child count: {layer_item.childCount()}")
            
            # Remove all existing children
            removed_count = 0
            while layer_item.childCount() > 0:
                layer_item.removeChild(layer_item.child(0))
                removed_count += 1
            self.log_debug(f"    Removed {removed_count} existing children")
            
            # Rebuild symbology items for this layer
            from qgis.core import QgsRasterLayer
            if isinstance(layer, QgsRasterLayer):
                self.log_debug(f"    Calling LayerTreeBuilder.add_raster_symbology_items()...")
                LayerTreeBuilder.add_raster_symbology_items(layer, layer_item, self)
                self.log_debug(f"    ✓ Rebuilt raster symbology for {layer.name()}, new child count: {layer_item.childCount()}")
            
        except Exception as e:
            self.log_debug(f"    ✗ ERROR updating symbology items: {e}")
            import traceback
            traceback.print_exc()
    
    def _find_layer_item(self, layer_id):
        """
        Find a layer tree item by layer ID.
        
        Args:
            layer_id: The layer ID to search for
            
        Returns:
            QTreeWidgetItem or None
        """
        self.log_debug(f"    _find_layer_item() searching for layer_id: {layer_id}")
        # Search through all items
        iterator = QTreeWidgetItemIterator(self.layer_tree)
        items_checked = 0
        while iterator.value():
            item = iterator.value()
            items_checked += 1
            # Check if this item represents a layer with matching ID
            item_type = item.data(0, Qt.UserRole + 1)
            if item_type == "layer":
                item_layer_id = item.data(0, Qt.UserRole)
                self.log_debug(f"      Found layer item: {item.text(0)} (id={item_layer_id})")
                if item_layer_id == layer_id:
                    self.log_debug(f"      ✓ Match found!")
                    return item
            iterator += 1
        self.log_debug(f"    Checked {items_checked} items, no match found")
        return None
    
    def refresh_layers(self):
        """Refresh the layer list from the current project."""
        self.log_debug("========== refresh_layers() CALLED ==========")
        # Don't refresh if we're in the middle of updating visibility
        if self._updating_visibility:
            self.log_debug("Skipping refresh - _updating_visibility is True")
            return
        
        # Temporarily disconnect the itemChanged signal to avoid recursion
        try:
            self.layer_tree.itemChanged.disconnect(self.on_item_visibility_changed)
        except (TypeError, RuntimeError):
            # Signal not connected, ignore
            pass
        
        try:
            # Clear existing items
            self.layer_tree.clear()
            
            # Get project and root
            project = QgsProject.instance()
            root = project.layerTreeRoot()
            
            self.log_debug(f"refresh_layers() calling build_tree_from_node, root={root}, has {len(root.children())} children")
            
            # Build tree from layer tree structure
            LayerTreeBuilder.build_tree_from_node(root, None, self.layer_tree, self)
            
            # Expand all groups by default
            self.layer_tree.expandAll()
            
            # Update info
            layer_count = len(project.mapLayers())
            self.info_label.setText(f"Total layers: {layer_count}")
        
        finally:
            # Reconnect the signal
            try:
                self.layer_tree.itemChanged.connect(self.on_item_visibility_changed)
            except (TypeError, RuntimeError):
                # Already connected, ignore
                pass
    
    def filter_layers(self, text):
        """Filter layers based on search text, including child layers in groups."""
        total_count, hidden_count = FilterService.filter_tree(self.layer_tree, text)
        
        # Update the main info label with visible/total counts
        visible_count = total_count - hidden_count
        if hidden_count > 0:
            self.info_label.setText(f"Showing {visible_count} of {total_count} layers")
            self.filter_info_label.setText(f"Filtered: {hidden_count} layer{'s' if hidden_count != 1 else ''} hidden from view")
            self.filter_info_label.setVisible(True)
        else:
            self.info_label.setText(f"Total layers: {total_count}")
            self.filter_info_label.setVisible(False)
    
    def on_item_visibility_changed(self, item, column):
        """Handle checkbox state change for layer visibility."""
        if column != 0:
            return
        
        # Set flag to prevent refresh during visibility updates
        self._updating_visibility = True
        
        try:
            item_type = item.data(0, Qt.UserRole + 1)
            is_checked = item.checkState(0) == Qt.Checked
            
            self.log_debug(f"on_item_visibility_changed: type={item_type}, checked={is_checked}, name={item.text(0)}")
            
            if item_type == "layer":
                # Handle layer visibility
                layer_id = item.data(0, Qt.UserRole)
                VisibilityService.set_layer_visibility(layer_id, is_checked)
                self.layerVisibilityChanged.emit(layer_id, is_checked)
                self.log_debug(f"  Layer visibility set")
            
            elif item_type == "group":
                # Handle group visibility - update the QGIS group node and all children
                self.log_debug(f"  Handling group visibility")
                # Block signals to prevent recursive calls during updates
                try:
                    self.layer_tree.itemChanged.disconnect(self.on_item_visibility_changed)
                except (TypeError, RuntimeError):
                    pass  # Signal not connected
                
                try:
                    # Get the actual QGIS group node safely by name
                    group_name = item.data(0, Qt.UserRole)
                    root = QgsProject.instance().layerTreeRoot()
                    group_node = root.findGroup(group_name)
                    if group_node:
                        # Set visibility on the QGIS layer tree directly (not on widget items)
                        self.set_qgis_group_visibility_recursive(group_node, is_checked)
                finally:
                    try:
                        self.layer_tree.itemChanged.connect(self.on_item_visibility_changed)
                    except (TypeError, RuntimeError):
                        pass  # Already connected
            
            elif item_type == "category":
                # Handle category visibility for categorized renderer
                self.set_category_visibility(item, is_checked)
            
            elif item_type == "range":
                # Handle range visibility for graduated renderer
                self.set_range_visibility(item, is_checked)
            
            elif item_type == "rule":
                # Handle rule visibility for rule-based renderer
                self.set_rule_visibility(item, is_checked)
        
        finally:
            # Clear flag after visibility update is complete
            self._updating_visibility = False
    
    def set_category_visibility(self, item, visible):
        """Toggle visibility of a categorized symbol category."""
        layer_id = item.data(0, Qt.UserRole)
        category_index = item.data(0, Qt.UserRole + 2)
        
        # Temporarily disconnect our handler to avoid catching our own signal
        project = QgsProject.instance()
        layer = project.mapLayer(layer_id)
        
        if layer:
            try:
                layer.rendererChanged.disconnect(self.on_renderer_changed)
            except (TypeError, RuntimeError):
                pass
        
        try:
            # Update visibility using service
            SymbologyService.update_category_visibility(
                layer_id, category_index, visible, self.iface
            )
        finally:
            # Reconnect our handler
            if layer:
                try:
                    layer.rendererChanged.connect(self.on_renderer_changed)
                except (TypeError, RuntimeError):
                    pass
    
    def set_range_visibility(self, item, visible):
        """Toggle visibility of a graduated symbol range."""
        layer_id = item.data(0, Qt.UserRole)
        range_index = item.data(0, Qt.UserRole + 2)
        
        # Temporarily disconnect our handlers to avoid catching our own signals
        project = QgsProject.instance()
        layer = project.mapLayer(layer_id)
        
        if layer:
            try:
                layer.rendererChanged.disconnect(self.on_renderer_changed)
            except (TypeError, RuntimeError):
                pass
            try:
                layer.legendChanged.disconnect(self.on_legend_changed)
            except (TypeError, RuntimeError):
                pass
        
        try:
            # Update visibility using service
            SymbologyService.update_range_visibility(
                layer_id, range_index, visible, self.iface
            )
        finally:
            # Reconnect our handlers
            if layer:
                try:
                    layer.rendererChanged.connect(self.on_renderer_changed)
                except (TypeError, RuntimeError):
                    pass
                try:
                    layer.legendChanged.connect(self.on_legend_changed)
                except (TypeError, RuntimeError):
                    pass
    
    def set_rule_visibility(self, item, visible):
        """Toggle visibility of a rule-based renderer rule."""
        layer_id = item.data(0, Qt.UserRole)
        rule_key = item.data(0, Qt.UserRole + 2)
        
        # Temporarily disconnect our handler to avoid catching our own signal
        project = QgsProject.instance()
        layer = project.mapLayer(layer_id)
        
        if layer:
            try:
                layer.rendererChanged.disconnect(self.on_renderer_changed)
            except (TypeError, RuntimeError):
                pass
        
        try:
            # Update visibility using service
            SymbologyService.update_rule_visibility(
                layer_id, rule_key, visible, self.iface
            )
        finally:
            # Reconnect our handler
            if layer:
                try:
                    layer.rendererChanged.connect(self.on_renderer_changed)
                except (TypeError, RuntimeError):
                    pass
    
    def set_qgis_group_visibility_recursive(self, group_node, visible):
        """Recursively set visibility for all layers in a QGIS group node."""
        LayerOperationsService.set_group_visibility_recursive(group_node, visible)
    
    def on_item_selected(self):
        """Handle layer selection in the tree."""
        # Prevent circular updates
        if self._updating_selection:
            return
        
        selected_items = self.layer_tree.selectedItems()
        if not selected_items:
            return
        
        item = selected_items[0]
        item_type = item.data(0, Qt.UserRole + 1)
        
        if item_type == "layer":
            layer_id = item.data(0, Qt.UserRole)
            self.layerSelected.emit(layer_id)
            
            # Select layer in QGIS using service
            project = QgsProject.instance()
            layer = project.mapLayer(layer_id)
            if layer:
                self._updating_selection = True
                try:
                    SelectionService.select_layer_in_qgis(layer, self.iface, self.log_debug)
                finally:
                    self._updating_selection = False
        
        elif item_type == "group":
            # Select group in QGIS using service
            group_name = item.data(0, Qt.UserRole)
            self._updating_selection = True
            try:
                SelectionService.select_group_in_qgis(group_name, self.iface, self.log_debug)
            finally:
                self._updating_selection = False
        
        elif item_type in ["category", "range", "rule"]:
            # For symbology items, select the parent layer
            parent = item.parent()
            if parent and parent.data(0, Qt.UserRole + 1) == "layer":
                layer_id = parent.data(0, Qt.UserRole)
                self.layerSelected.emit(layer_id)
                
                # Select parent layer in QGIS using service
                project = QgsProject.instance()
                layer = project.mapLayer(layer_id)
                if layer:
                    self._updating_selection = True
                    try:
                        SelectionService.select_layer_in_qgis(layer, self.iface, self.log_debug)
                    finally:
                        self._updating_selection = False
    
    def on_qgis_visibility_changed(self):
        """Handle visibility changes from QGIS (e.g., from main Layers panel)."""
        # Log to see when this is triggered
        sender = self.sender()
        sender_info = "unknown"
        if sender:
            if hasattr(sender, 'name'):
                sender_info = f"{type(sender).__name__}: {sender.name()}"
            else:
                sender_info = f"{type(sender).__name__}"
        
        self.log_debug(f"on_qgis_visibility_changed triggered by {sender_info}, _updating_visibility={self._updating_visibility}")
        
        # Don't update if we're the ones making the change
        if self._updating_visibility:
            self.log_debug("  Skipping refresh - we're updating visibility")
            return
        
        # Refresh to sync with QGIS
        self.log_debug("  Refreshing layers from QGIS visibility change")
        self.refresh_layers()
    
    def on_qgis_active_layer_changed(self, layer):
        """Handle active layer changed in QGIS - sync selection to our panel."""
        # Prevent circular updates
        if self._updating_selection:
            return
        
        if not layer:
            return
        
        try:
            self._updating_selection = True
            self.log_debug(f"QGIS active layer changed: {layer.name()} ({layer.id()})")
            
            # Find and select the layer in our tree
            self.select_layer_in_tree(layer.id())
        finally:
            self._updating_selection = False
    
    def select_layer_in_tree(self, layer_id):
        """Select a layer in our tree widget by layer ID."""
        def search_item(parent_item):
            """Recursively search for layer item."""
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                child_type = child.data(0, Qt.UserRole + 1)
                child_id = child.data(0, Qt.UserRole)
                
                if child_type == "layer" and child_id == layer_id:
                    return child
                
                # Search in children (groups)
                result = search_item(child)
                if result:
                    return result
            
            return None
        
        # Search at top level
        for i in range(self.layer_tree.topLevelItemCount()):
            top_item = self.layer_tree.topLevelItem(i)
            top_type = top_item.data(0, Qt.UserRole + 1)
            top_id = top_item.data(0, Qt.UserRole)
            
            if top_type == "layer" and top_id == layer_id:
                self.layer_tree.setCurrentItem(top_item)
                self.layer_tree.scrollToItem(top_item)
                self.log_debug(f"Selected layer at top level: {top_item.text(0)}")
                return
            
            # Search in children
            result = search_item(top_item)
            if result:
                self.layer_tree.setCurrentItem(result)
                self.layer_tree.scrollToItem(result)
                self.log_debug(f"Selected layer in tree: {result.text(0)}")
                return
        
        self.log_debug(f"Layer not found in tree: {layer_id}")
    
    def show_all_layers(self):
        """Show all layers or selected layers if any are selected."""
        selected_items = self.layer_tree.selectedItems()
        
        # If items are selected, only show those
        if selected_items:
            self.toggle_selected_visibility(True)
            return
        
        # Otherwise show all - recursively process all items
        self._updating_visibility = True
        self.layer_tree.itemChanged.disconnect(self.on_item_visibility_changed)
        
        try:
            def show_all_recursive(parent_item):
                """Recursively show all layers and groups."""
                for i in range(parent_item.childCount()):
                    item = parent_item.child(i)
                    item_type = item.data(0, Qt.UserRole + 1)
                    item_id = item.data(0, Qt.UserRole)
                    
                    # Set checkbox
                    item.setCheckState(0, Qt.Checked)
                    
                    # Update visibility in QGIS
                    if item_type == "layer":
                        VisibilityService.set_layer_visibility(item_id, True)
                    elif item_type == "group":
                        project = QgsProject.instance()
                        root = project.layerTreeRoot()
                        group_node = root.findGroup(item_id)
                        if group_node:
                            LayerOperationsService.set_group_visibility_recursive(group_node, True)
                    
                    # Recurse into children
                    if item.childCount() > 0:
                        show_all_recursive(item)
            
            # Process top-level items
            root = self.layer_tree.invisibleRootItem()
            show_all_recursive(root)
        
        finally:
            self.layer_tree.itemChanged.connect(self.on_item_visibility_changed)
            self._updating_visibility = False
    
    def hide_all_layers(self):
        """Hide all layers or selected layers if any are selected."""
        selected_items = self.layer_tree.selectedItems()
        
        # If items are selected, only hide those
        if selected_items:
            self.toggle_selected_visibility(False)
            return
        
        # Otherwise hide all - recursively process all items
        self._updating_visibility = True
        self.layer_tree.itemChanged.disconnect(self.on_item_visibility_changed)
        
        try:
            def hide_all_recursive(parent_item):
                """Recursively hide all layers and groups."""
                for i in range(parent_item.childCount()):
                    item = parent_item.child(i)
                    item_type = item.data(0, Qt.UserRole + 1)
                    item_id = item.data(0, Qt.UserRole)
                    
                    # Set checkbox
                    item.setCheckState(0, Qt.Unchecked)
                    
                    # Update visibility in QGIS
                    if item_type == "layer":
                        VisibilityService.set_layer_visibility(item_id, False)
                    elif item_type == "group":
                        project = QgsProject.instance()
                        root = project.layerTreeRoot()
                        group_node = root.findGroup(item_id)
                        if group_node:
                            LayerOperationsService.set_group_visibility_recursive(group_node, False)
                    
                    # Recurse into children
                    if item.childCount() > 0:
                        hide_all_recursive(item)
            
            # Process top-level items
            root = self.layer_tree.invisibleRootItem()
            hide_all_recursive(root)
        
        finally:
            self.layer_tree.itemChanged.connect(self.on_item_visibility_changed)
            self._updating_visibility = False
    
    def toggle_selected_visibility(self, visible):
        """Toggle visibility for all selected items."""
        selected_items = self.layer_tree.selectedItems()
        if not selected_items:
            return
        
        self.layer_tree.itemChanged.disconnect(self.on_item_visibility_changed)
        
        try:
            for item in selected_items:
                item_type = item.data(0, Qt.UserRole + 1)
                item_id = item.data(0, Qt.UserRole)
                
                # Set checkbox state
                item.setCheckState(0, Qt.Checked if visible else Qt.Unchecked)
                
                # Update actual layer/group visibility
                if item_type == "layer":
                    VisibilityService.set_layer_visibility(item_id, visible)
                elif item_type == "group":
                    # Get the QGIS group node and set visibility recursively
                    project = QgsProject.instance()
                    root = project.layerTreeRoot()
                    group_node = root.findGroup(item_id)
                    if group_node:
                        LayerOperationsService.set_group_visibility_recursive(group_node, visible)
        
        finally:
            self.layer_tree.itemChanged.connect(self.on_item_visibility_changed)
    
    def show_context_menu(self, position):
        """Show context menu for layer or group operations."""
        item = self.layer_tree.itemAt(position)
        if not item:
            return
        
        # Check if multiple layers are selected
        selected_items = self.layer_tree.selectedItems()
        if len(selected_items) > 1:
            # Multiple selection - check if all are layers
            layers = []
            project = QgsProject.instance()
            
            for sel_item in selected_items:
                sel_item_type = sel_item.data(0, Qt.UserRole + 1)
                if sel_item_type == "layer":
                    layer_id = sel_item.data(0, Qt.UserRole)
                    layer = project.mapLayer(layer_id)
                    if layer:
                        layers.append(layer)
            
            # Show multi-layer menu if we have multiple layers
            if len(layers) > 1:
                menu = LayerContextMenu.create_multi_layer_menu(layers, self.iface)
                menu.exec_(self.layer_tree.viewport().mapToGlobal(position))
                # Refresh after any group operations
                self.refresh_layers()
                return
        
        item_type = item.data(0, Qt.UserRole + 1)
        
        if item_type == "layer":
            # Layer context menu
            layer_id = item.data(0, Qt.UserRole)
            project = QgsProject.instance()
            layer = project.mapLayer(layer_id)
            
            if not layer:
                return
            
            # Create menu and pass rename callback
            menu = LayerContextMenu.create_layer_menu(
                layer, 
                self.iface,
                rename_callback=lambda: self.start_rename_item(item),
                debug_callback=self.log_debug
            )
            menu.exec_(self.layer_tree.viewport().mapToGlobal(position))
        
        elif item_type == "group":
            # Group context menu
            menu = QMenu(self)
            
            rename_action = menu.addAction(QIcon(":/images/themes/default/mActionEditTable.svg"), "Rename Group\\tF2")
            rename_action.triggered.connect(lambda: self.start_rename_item(item))
            
            menu.addSeparator()
            
            # Remove group
            group_name = item.data(0, Qt.UserRole)
            remove_action = menu.addAction(QIcon(":/images/themes/default/mActionRemoveLayer.svg"), "Remove Group")
            remove_action.triggered.connect(lambda: self.remove_group(group_name))
            
            menu.exec_(self.layer_tree.viewport().mapToGlobal(position))
    
    def show_header_context_menu(self, position):
        """Show context menu for column visibility control."""
        menu = LayerContextMenu.create_header_menu(self.layer_tree)
        
        # Connect to save settings when column visibility changes
        for action in menu.actions():
            if action.isCheckable():
                action.triggered.connect(self.save_column_visibility)
        
        menu.exec_(self.layer_tree.header().mapToGlobal(position))
    
    def restore_column_visibility(self):
        """Restore column visibility from saved settings."""
        settings = QSettings()
        header = self.layer_tree.header()
        
        # Column count (7: Layer Name, Type, Features/Size, CRS, File Type, File Size, Source)
        for col in range(1, 7):  # Skip column 0 (Layer Name - always visible)
            key = f"CeeThreeDeeQTools/LayersAdvanced/column_{col}_visible"
            is_visible = settings.value(key, True, type=bool)
            header.setSectionHidden(col, not is_visible)
    
    def save_column_visibility(self):
        """Save column visibility to settings."""
        settings = QSettings()
        header = self.layer_tree.header()
        
        for col in range(1, 7):  # Skip column 0 (Layer Name - always visible)
            key = f"CeeThreeDeeQTools/LayersAdvanced/column_{col}_visible"
            is_visible = not header.isSectionHidden(col)
            settings.setValue(key, is_visible)
    
    def eventFilter(self, obj, event):
        """Filter events to catch F2 key for renaming and Space for visibility toggle."""
        if obj == self.layer_tree and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_F2:
                # Get selected item
                selected_items = self.layer_tree.selectedItems()
                if selected_items:
                    item = selected_items[0]
                    item_type = item.data(0, Qt.UserRole + 1)
                    # Edit both layers and groups
                    if item_type in ["layer", "group"]:
                        self.start_rename_item(item)
                        return True
            
            elif event.key() == Qt.Key_Space:
                # Toggle visibility for selected items
                selected_items = self.layer_tree.selectedItems()
                if selected_items:
                    # Determine new state: if any selected item is unchecked, check all; otherwise uncheck all
                    any_unchecked = any(item.checkState(0) == Qt.Unchecked for item in selected_items)
                    self.toggle_selected_visibility(any_unchecked)
                    return True
        
        return super().eventFilter(obj, event)
    
    def on_item_double_clicked(self, item, column):
        """Handle double-click to rename layer or group."""
        EventHandlers.handle_item_double_click(self, item, column)
    
    def start_rename_item(self, item):
        """Start inline editing for layer or group name."""
        EventHandlers.start_rename(self, item)
    
    def on_item_name_changed(self, item, column):
        """Handle layer or group name change after inline editing."""
        # Disconnect this handler first to avoid recursion
        try:
            self.layer_tree.itemChanged.disconnect(self.on_item_name_changed)
        except TypeError:
            # Already disconnected, ignore
            pass
        
        # Check if this is a name change (column 0) or visibility change
        if column == 0:
            item_type = item.data(0, Qt.UserRole + 1)
            new_name = item.text(0)
            original_name = item.data(0, Qt.UserRole + 2)
            
            if item_type == "layer":
                # Get the layer
                layer_id = item.data(0, Qt.UserRole)
                project = QgsProject.instance()
                layer = project.mapLayer(layer_id)
                
                if layer and new_name and new_name != original_name:
                    layer.setName(new_name)
            
            elif item_type == "group":
                # Get the group from layer tree by name (avoid dangling pointer)
                old_group_name = item.data(0, Qt.UserRole)
                root = QgsProject.instance().layerTreeRoot()
                group_node = root.findGroup(old_group_name)
                
                if group_node and new_name and new_name != original_name:
                    group_node.setName(new_name)
                    # Update the stored name in the item
                    item.setData(0, Qt.UserRole, new_name)
            
            # Remove editable flag
            flags = item.flags()
            item.setFlags(flags & ~Qt.ItemIsEditable)
        else:
            # Not a name change, handle as visibility change
            self.on_item_visibility_changed(item, column)
        
        # Reconnect the visibility handler
        self.layer_tree.itemChanged.connect(self.on_item_visibility_changed)
    
    def move_layer_up(self):
        """Move selected layer(s) or group(s) up in the layer order."""
        selected_items = self.layer_tree.selectedItems()
        if not selected_items:
            return
        
        # For multiple selections, move each item up in order
        # Store IDs for reselection
        items_to_reselect = []
        
        for item in selected_items:
            item_type = item.data(0, Qt.UserRole + 1)
            item_id = item.data(0, Qt.UserRole)
            
            success = False
            if item_type == "layer":
                success = LayerOperationsService.move_layer_up(item_id)
            elif item_type == "group":
                success = LayerOperationsService.move_group_up(item_id)
            
            if success:
                items_to_reselect.append((item_id, item_type))
        
        if items_to_reselect:
            self.refresh_layers()
            # Reselect all moved items
            for item_id, item_type in items_to_reselect:
                self.reselect_item_by_id(item_id, item_type, clear_selection=False)
    
    def move_layer_down(self):
        """Move selected layer(s) or group(s) down in the layer order."""
        selected_items = self.layer_tree.selectedItems()
        if not selected_items:
            return
        
        # For multiple selections, move each item down in reverse order
        # to maintain relative positions
        items_to_reselect = []
        
        for item in reversed(selected_items):
            item_type = item.data(0, Qt.UserRole + 1)
            item_id = item.data(0, Qt.UserRole)
            
            success = False
            if item_type == "layer":
                success = LayerOperationsService.move_layer_down(item_id)
            elif item_type == "group":
                success = LayerOperationsService.move_group_down(item_id)
            
            if success:
                items_to_reselect.append((item_id, item_type))
        
        if items_to_reselect:
            self.refresh_layers()
            # Reselect all moved items
            for item_id, item_type in items_to_reselect:
                self.reselect_item_by_id(item_id, item_type, clear_selection=False)
    
    def reselect_item_by_id(self, item_id, item_type, clear_selection=True):
        """
        Find and reselect an item in the tree after refresh.
        
        Args:
            item_id: Layer ID or group name to reselect
            item_type: "layer" or "group"
            clear_selection: If True, clear existing selection first
        """
        root = self.layer_tree.invisibleRootItem()
        
        def search_item(parent_item):
            """Recursively search for the item."""
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                child_type = child.data(0, Qt.UserRole + 1)
                child_id = child.data(0, Qt.UserRole)
                
                # Check if this is the item we're looking for
                if child_type == item_type and child_id == item_id:
                    return child
                
                # Search in group children
                if child_type == "group":
                    found = search_item(child)
                    if found:
                        return found
            
            return None
        
        # Find and select the item
        item = search_item(root)
        if item:
            if clear_selection:
                self.layer_tree.setCurrentItem(item)
            else:
                # Add to selection without clearing
                item.setSelected(True)
            self.layer_tree.scrollToItem(item)
    
    def remove_group(self, group_name):
        """
        Remove a group from the layer tree.
        
        Args:
            group_name: Name of the group to remove
        """
        try:
            project = QgsProject.instance()
            root = project.layerTreeRoot()
            group_node = root.findGroup(group_name)
            
            if group_node:
                parent = group_node.parent()
                if parent:
                    parent.removeChildNode(group_node)
                    self.refresh_layers()
                    self.log_debug(f"Removed group: {group_name}")
        except Exception as e:
            self.log_debug(f"Error removing group: {e}")
    
    def closeEvent(self, event):
        """Handle widget close event."""
        # Save column visibility before closing
        self.save_column_visibility()
        
        # Disconnect signals
        try:
            # Disconnect tree widget signals
            try:
                self.layer_tree.dropCompleted.disconnect(self.on_drop_completed)
            except (AttributeError, TypeError):
                pass
            
            project = QgsProject.instance()
            try:
                project.readProject.disconnect(self.on_project_loaded)
            except (AttributeError, TypeError):
                pass
            project.layersAdded.disconnect(self.refresh_layers)
            project.layersRemoved.disconnect(self.refresh_layers)
            
            # Disconnect layer tree signals
            try:
                root = project.layerTreeRoot()
                root.addedChildren.disconnect(self.on_layer_tree_children_changed)
                root.removedChildren.disconnect(self.on_layer_tree_children_changed)
                root.visibilityChanged.disconnect(self.on_qgis_visibility_changed)
            except (AttributeError, TypeError):
                pass
                
            # Disconnect active layer signal
            try:
                self.iface.layerTreeView().currentLayerChanged.disconnect(self.on_qgis_active_layer_changed)
            except (AttributeError, TypeError):
                pass
            
            # Disconnect from all layers (legendChanged, rendererChanged, styleChanged)
            for layer in project.mapLayers().values():
                try:
                    layer.legendChanged.disconnect(self.on_legend_changed)
                except (AttributeError, TypeError):
                    pass
                try:
                    layer.rendererChanged.disconnect(self.on_renderer_changed)
                except (AttributeError, TypeError):
                    pass
                try:
                    layer.styleChanged.disconnect(self.on_layer_changed)
                except (AttributeError, TypeError):
                    pass
        except Exception:
            pass
        
        event.accept()
    
    def expand_all_groups(self):
        """Expand all groups in the tree."""
        self.layer_tree.expandAll()
        self.log_debug("Expanded all groups")
    
    def collapse_all_groups(self):
        """Collapse all groups in the tree."""
        self.layer_tree.collapseAll()
        self.log_debug("Collapsed all groups")
    
    def toggle_all_layers(self):
        """Toggle between expanding and collapsing all layers based on first layer's state."""
        # Find the first layer item to check its state
        def find_first_layer(item):
            """Recursively find the first layer item."""
            for i in range(item.childCount()):
                child = item.child(i)
                item_type = child.data(0, Qt.UserRole + 1)
                
                if item_type == "layer":
                    return child
                elif item_type == "group":
                    # Search within group
                    result = find_first_layer(child)
                    if result:
                        return result
            return None
        
        root = self.layer_tree.invisibleRootItem()
        first_layer = find_first_layer(root)
        
        if first_layer:
            # Check if first layer is expanded
            is_expanded = first_layer.isExpanded()
            
            if is_expanded:
                # Currently expanded, so collapse all
                self.collapse_all_layers()
                self.toggle_layers_action.setIcon(QIcon(":/images/themes/default/mActionExpandNewTree.svg"))
                self.toggle_layers_action.setText("Expand All Layers")
                self.toggle_layers_action.setToolTip("Expand all layers (show symbology)")
            else:
                # Currently collapsed, so expand all
                self.expand_all_layers()
                self.toggle_layers_action.setIcon(QIcon(":/images/themes/default/mActionCollapseNewTree.svg"))
                self.toggle_layers_action.setText("Collapse All Layers")
                self.toggle_layers_action.setToolTip("Collapse all layers (hide symbology)")
        else:
            # No layers found, default to expand
            self.expand_all_layers()
            self.toggle_layers_action.setIcon(QIcon(":/images/themes/default/mActionCollapseNewTree.svg"))
            self.toggle_layers_action.setText("Collapse All Layers")
            self.toggle_layers_action.setToolTip("Collapse all layers (hide symbology)")
    
    def expand_all_layers(self):
        """Expand all layer items (showing symbology) but not groups."""
        def expand_layers_recursive(item):
            """Recursively expand only layer items."""
            for i in range(item.childCount()):
                child = item.child(i)
                item_type = child.data(0, Qt.UserRole + 1)
                
                if item_type == "layer":
                    # Expand the layer to show symbology
                    self.layer_tree.expandItem(child)
                elif item_type == "group":
                    # Don't expand the group, but process its children
                    expand_layers_recursive(child)
        
        # Process top-level items
        root = self.layer_tree.invisibleRootItem()
        expand_layers_recursive(root)
        self.log_debug("Expanded all layers")
    
    def collapse_all_layers(self):
        """Collapse all layer items (hiding symbology) but not groups."""
        def collapse_layers_recursive(item):
            """Recursively collapse only layer items."""
            for i in range(item.childCount()):
                child = item.child(i)
                item_type = child.data(0, Qt.UserRole + 1)
                
                if item_type == "layer":
                    # Collapse the layer to hide symbology
                    self.layer_tree.collapseItem(child)
                elif item_type == "group":
                    # Don't collapse the group, but process its children
                    collapse_layers_recursive(child)
        
        # Process top-level items
        root = self.layer_tree.invisibleRootItem()
        collapse_layers_recursive(root)
        self.log_debug("Collapsed all layers")
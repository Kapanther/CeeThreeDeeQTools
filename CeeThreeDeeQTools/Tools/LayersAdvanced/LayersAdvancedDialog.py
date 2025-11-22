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
    QPushButton,
    QLabel,
    QCheckBox,
    QLineEdit,
    QMenu,
    QTextEdit
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
    
    def on_project_loaded(self):
        """Handle project loaded event - refresh layers after a delay to ensure layers are fully loaded."""
        # Use a single-shot timer to refresh after layers are fully loaded
        from qgis.PyQt.QtCore import QTimer
        QTimer.singleShot(100, self.refresh_layers)
    
    def connect_layer_signals(self, layers):
        """Connect to signals for newly added layers."""
        SignalManagerService.connect_layer_signals(self, layers)
        # Also connect CRS changes
        for layer in layers:
            try:
                layer.crsChanged.connect(self.on_layer_changed)
            except Exception:
                pass
    
    def on_renderer_changed(self):
        """Handle renderer/symbology changes (e.g., from QGIS layer styling panel)."""
        if not self._updating_visibility:
            sender = self.sender()
            # Update just the symbology checkboxes for the changed layer
            if sender:
                self.update_layer_symbology_checkboxes(sender)
            else:
                self.refresh_layers()
    
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
    
    def refresh_layers(self):
        """Refresh the layer list from the current project."""
        # Don't refresh if we're in the middle of updating visibility
        if self._updating_visibility:
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
            
            # Build tree from layer tree structure
            LayerTreeBuilder.build_tree_from_node(root, None, self.layer_tree)
            
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
        FilterService.filter_tree(self.layer_tree, text)
    
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
            SymbologyService.update_range_visibility(
                layer_id, range_index, visible, self.iface
            )
        finally:
            # Reconnect our handler
            if layer:
                try:
                    layer.rendererChanged.connect(self.on_renderer_changed)
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
        
        # Otherwise show all
        self.layer_tree.itemChanged.disconnect(self.on_item_visibility_changed)
        
        try:
            for i in range(self.layer_tree.topLevelItemCount()):
                item = self.layer_tree.topLevelItem(i)
                item.setCheckState(0, Qt.Checked)
                layer_id = item.data(0, Qt.UserRole)
                VisibilityService.set_layer_visibility(layer_id, True)
        
        finally:
            self.layer_tree.itemChanged.connect(self.on_item_visibility_changed)
    
    def hide_all_layers(self):
        """Hide all layers or selected layers if any are selected."""
        selected_items = self.layer_tree.selectedItems()
        
        # If items are selected, only hide those
        if selected_items:
            self.toggle_selected_visibility(False)
            return
        
        # Otherwise hide all
        self.layer_tree.itemChanged.disconnect(self.on_item_visibility_changed)
        
        try:
            for i in range(self.layer_tree.topLevelItemCount()):
                item = self.layer_tree.topLevelItem(i)
                item.setCheckState(0, Qt.Unchecked)
                layer_id = item.data(0, Qt.UserRole)
                VisibilityService.set_layer_visibility(layer_id, False)
        
        finally:
            self.layer_tree.itemChanged.connect(self.on_item_visibility_changed)
    
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
                rename_callback=lambda: self.start_rename_item(item)
            )
            menu.exec_(self.layer_tree.viewport().mapToGlobal(position))
        
        elif item_type == "group":
            # Group context menu - just rename for now
            menu = QMenu(self)
            
            rename_action = menu.addAction(QIcon(":/images/themes/default/mActionEditTable.svg"), "Rename Group\\tF2")
            rename_action.triggered.connect(lambda: self.start_rename_item(item))
            
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

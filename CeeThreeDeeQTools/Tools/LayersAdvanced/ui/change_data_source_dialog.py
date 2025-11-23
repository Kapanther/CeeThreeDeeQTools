"""
Custom Change Data Source Dialog with QGIS Browser integration.

Provides a dialog with QGIS file browser that can expand into geopackages.
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QDialogButtonBox,
    QLabel, QLineEdit, QPushButton
)
from qgis.PyQt.QtCore import Qt
from qgis.gui import QgsBrowserTreeView
from qgis.core import QgsDataItem, QgsMimeDataUtils, QgsLayerItem


class ChangeDataSourceDialog(QDialog):
    """
    Dialog for changing a layer's data source using QGIS browser.
    """
    
    def __init__(self, layer, browser_model, parent=None, debug_callback=None):
        """
        Initialize the dialog.
        
        Args:
            layer: QgsMapLayer to change data source for
            browser_model: QgsBrowserGuiModel instance (shared browser model)
            parent: Parent widget
            debug_callback: Optional callback for debug logging
        """
        super().__init__(parent)
        
        self.layer = layer
        self.browser_model = browser_model
        self.debug_callback = debug_callback
        self.selected_uri = None
        
        self.setWindowTitle(f"Change Data Source - {layer.name()}")
        self.setModal(True)
        self.resize(800, 600)
        
        self.log(f"DEBUG: Dialog initializing for layer: {layer.name()}")
        self.log(f"DEBUG: Current source: {layer.source()}")
        self.log(f"DEBUG: Browser model: {browser_model}")
        
        self._setup_ui()
        self._connect_signals()
        
        self.log(f"DEBUG: Dialog initialization complete")
    
    def log(self, message):
        """Log a message via callback or print."""
        if self.debug_callback:
            self.debug_callback(message)
        else:
            print(message)
    
    def _setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout()
        
        # Current source display
        current_layout = QHBoxLayout()
        current_layout.addWidget(QLabel("Current:"))
        self.current_source_edit = QLineEdit()
        self.current_source_edit.setText(self.layer.source())
        self.current_source_edit.setReadOnly(True)
        current_layout.addWidget(self.current_source_edit)
        layout.addLayout(current_layout)
        
        # New source display
        new_layout = QHBoxLayout()
        new_layout.addWidget(QLabel("New:"))
        self.new_source_edit = QLineEdit()
        self.new_source_edit.setReadOnly(True)
        self.new_source_edit.setPlaceholderText("Select a data source from the browser below...")
        new_layout.addWidget(self.new_source_edit)
        layout.addLayout(new_layout)
        
        # Browser tree view
        browser_label = QLabel("Select new data source:")
        layout.addWidget(browser_label)
        
        self.browser_tree = QgsBrowserTreeView(self)
        
        # Set the browser model
        self.log(f"DEBUG: Setting browser model on tree view")
        self.browser_tree.setBrowserModel(self.browser_model)
        
        # Set the model to show the root
        self.log(f"DEBUG: Browser model has {self.browser_model.rowCount()} root items")
        
        layout.addWidget(self.browser_tree)
        
        # Dialog buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.button_box.button(QDialogButtonBox.Ok).setEnabled(False)
        layout.addWidget(self.button_box)
        
        self.setLayout(layout)
    
    def showEvent(self, event):
        """Override show event to ensure signals are connected after tree is fully set up."""
        super().showEvent(event)
        
        # Try to connect selection signal now that dialog is shown
        if not hasattr(self, '_signals_connected'):
            self._signals_connected = True
            selection_model = self.browser_tree.selectionModel()
            if selection_model:
                self.log("DEBUG: Connecting selection signal in showEvent")
                selection_model.selectionChanged.connect(self._on_selection_changed)
    
    def _connect_signals(self):
        """Connect signals."""
        # Try to connect selection model if available
        selection_model = self.browser_tree.selectionModel()
        if selection_model:
            self.log("DEBUG: Selection model available, connecting signal")
            selection_model.selectionChanged.connect(self._on_selection_changed)
            self._signals_connected = True
        else:
            self.log("WARNING: No selection model available for browser tree yet")
            self._signals_connected = False
        
        self.browser_tree.doubleClicked.connect(self._on_double_click)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
    
    def _on_selection_changed(self, selected, deselected):
        """Handle selection changes in the browser tree."""
        indexes = self.browser_tree.selectionModel().selectedIndexes()
        
        if not indexes:
            self.new_source_edit.clear()
            self.button_box.button(QDialogButtonBox.Ok).setEnabled(False)
            return
        
        # Get the data item from the model
        index = indexes[0]
        data_item = self.browser_model.dataItem(index)
        
        self.log(f"DEBUG: Selected item: {data_item}")
        self.log(f"DEBUG: Item type: {type(data_item).__name__}")
        
        if isinstance(data_item, QgsLayerItem):
            # This is a layer item (e.g., a layer inside a geopackage)
            self.log(f"DEBUG: Layer item selected")
            self.log(f"DEBUG: Layer type: {data_item.mapLayerType()}")
            self.log(f"DEBUG: Provider key: {data_item.providerKey()}")
            
            # Get URI from mime data
            mime_uris = data_item.mimeUris()
            if mime_uris:
                uri = mime_uris[0]
                self.log(f"DEBUG: URI: {uri.uri}")
                self.log(f"DEBUG: URI name: {uri.name}")
                self.log(f"DEBUG: URI provider: {uri.providerKey}")
                
                self.selected_uri = uri.uri
                self.new_source_edit.setText(uri.uri)
                self.button_box.button(QDialogButtonBox.Ok).setEnabled(True)
            else:
                self.log(f"DEBUG: No mime URIs available")
                self.new_source_edit.clear()
                self.button_box.button(QDialogButtonBox.Ok).setEnabled(False)
        else:
            # Not a layer item (might be a directory, geopackage container, etc.)
            self.log(f"DEBUG: Not a layer item, clearing selection")
            self.new_source_edit.clear()
            self.button_box.button(QDialogButtonBox.Ok).setEnabled(False)
    
    def _on_double_click(self, index):
        """Handle double-click in browser tree."""
        data_item = self.browser_model.dataItem(index)
        
        if isinstance(data_item, QgsLayerItem):
            # Double-clicking a layer item accepts the dialog
            self.log(f"DEBUG: Double-clicked layer item, accepting dialog")
            self.accept()
    
    def get_selected_uri(self):
        """
        Get the selected URI.
        
        Returns:
            str: Selected URI or None if nothing selected
        """
        return self.selected_uri

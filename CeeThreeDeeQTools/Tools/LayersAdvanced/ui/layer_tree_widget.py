"""Tree widget for displaying layers."""

from qgis.PyQt.QtWidgets import QTreeWidget, QTreeWidgetItem
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsMapLayer


class LayerTreeWidget(QTreeWidget):
    """Custom tree widget for layer display and management."""
    
    # Signals
    layerVisibilityChanged = pyqtSignal(str, bool)  # layer_id, visible
    layerSelected = pyqtSignal(str)  # layer_id
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        
    def setup_ui(self):
        """Initialize the tree widget."""
        self.setHeaderLabels(["Layer Name", "Type", "Features/Size"])
        self.setColumnWidth(0, 200)
        self.setColumnWidth(1, 80)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.itemChanged.connect(self._on_item_changed)
        self.itemSelectionChanged.connect(self._on_selection_changed)
    
    def add_layer_item(self, layer, layer_info, is_visible):
        """
        Add a layer to the tree.
        
        Args:
            layer: QgsMapLayer object
            layer_info: Dictionary with 'type' and 'info' keys
            is_visible: Boolean indicating visibility
        
        Returns:
            QTreeWidgetItem: The created item
        """
        item = QTreeWidgetItem(self)
        
        # Set layer name and ID
        item.setText(0, layer.name())
        item.setData(0, Qt.UserRole, layer.id())
        
        # Set checkbox for visibility
        item.setCheckState(0, Qt.Checked if is_visible else Qt.Unchecked)
        
        # Set layer type and info
        item.setText(1, layer_info['type'])
        item.setText(2, layer_info['info'])
        
        # Set icon
        icon = self._get_layer_icon(layer)
        if icon:
            item.setIcon(0, icon)
        
        return item
    
    def _get_layer_icon(self, layer):
        """Get the appropriate icon for a layer type."""
        try:
            if layer.type() == QgsMapLayer.VectorLayer:
                return QIcon(":/images/themes/default/mIconVector.svg")
            elif layer.type() == QgsMapLayer.RasterLayer:
                return QIcon(":/images/themes/default/mIconRaster.svg")
        except Exception:
            pass
        return None
    
    def _on_item_changed(self, item, column):
        """Handle checkbox state change."""
        if column != 0:
            return
        
        layer_id = item.data(0, Qt.UserRole)
        is_checked = item.checkState(0) == Qt.Checked
        self.layerVisibilityChanged.emit(layer_id, is_checked)
    
    def _on_selection_changed(self):
        """Handle selection change."""
        selected_items = self.selectedItems()
        if selected_items:
            layer_id = selected_items[0].data(0, Qt.UserRole)
            self.layerSelected.emit(layer_id)
    
    def update_all_visibility(self, visible):
        """
        Update visibility for all items.
        
        Args:
            visible: Boolean indicating visibility state
        """
        self.itemChanged.disconnect(self._on_item_changed)
        
        try:
            check_state = Qt.Checked if visible else Qt.Unchecked
            for i in range(self.topLevelItemCount()):
                item = self.topLevelItem(i)
                item.setCheckState(0, check_state)
        finally:
            self.itemChanged.connect(self._on_item_changed)
    
    def filter_items(self, text):
        """
        Filter items based on search text.
        
        Args:
            text: Search string
        """
        text = text.lower()
        
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            layer_name = item.text(0).lower()
            should_show = text in layer_name if text else True
            item.setHidden(not should_show)
    
    def get_all_layer_ids(self):
        """Get all layer IDs from the tree."""
        layer_ids = []
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            layer_ids.append(item.data(0, Qt.UserRole))
        return layer_ids

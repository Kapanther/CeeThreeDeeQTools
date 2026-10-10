"""Toolbar and control widgets for Layers Advanced."""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton
)
from qgis.PyQt.QtCore import pyqtSignal


class ToolbarWidget(QWidget):
    """Widget containing toolbar controls (search, buttons, etc.)."""
    
    # Signals
    refreshRequested = pyqtSignal()
    filterChanged = pyqtSignal(str)
    showAllRequested = pyqtSignal()
    hideAllRequested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        """Initialize the toolbar UI."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        
        # Title and refresh
        self._setup_title_bar(layout)
        
        # Search/filter
        self._setup_search_bar(layout)
        
        # Action buttons
        self._setup_action_buttons(layout)
        
        # Info label
        self.info_label = QLabel("Total layers: 0")
        layout.addWidget(self.info_label)
    
    def _setup_title_bar(self, parent_layout):
        """Setup the title bar with refresh button."""
        title_layout = QHBoxLayout()
        title_label = QLabel("<h3>Layers Advanced</h3>")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setToolTip("Refresh the layer list")
        refresh_btn.clicked.connect(self.refreshRequested.emit)
        title_layout.addWidget(refresh_btn)
        
        parent_layout.addLayout(title_layout)
    
    def _setup_search_bar(self, parent_layout):
        """Setup the search/filter bar."""
        search_layout = QHBoxLayout()
        search_label = QLabel("Filter:")
        search_layout.addWidget(search_label)
        
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search layers...")
        self.search_box.textChanged.connect(self.filterChanged.emit)
        search_layout.addWidget(self.search_box)
        
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.search_box.clear)
        search_layout.addWidget(clear_btn)
        
        parent_layout.addLayout(search_layout)
    
    def _setup_action_buttons(self, parent_layout):
        """Setup action buttons (Show All, Hide All)."""
        button_layout = QHBoxLayout()
        
        show_all_btn = QPushButton("Show All")
        show_all_btn.clicked.connect(self.showAllRequested.emit)
        button_layout.addWidget(show_all_btn)
        
        hide_all_btn = QPushButton("Hide All")
        hide_all_btn.clicked.connect(self.hideAllRequested.emit)
        button_layout.addWidget(hide_all_btn)
        
        button_layout.addStretch()
        parent_layout.addLayout(button_layout)
    
    def update_info(self, layer_count):
        """Update the info label with layer count."""
        self.info_label.setText(f"Total layers: {layer_count}")
    
    def clear_filter(self):
        """Clear the search filter."""
        self.search_box.clear()

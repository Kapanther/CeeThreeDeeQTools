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
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QListWidget,
    QPushButton,
    QLabel,
    QFileDialog,
    QDialogButtonBox,
    QAbstractItemView,
    QMessageBox,
    QCheckBox  # Add QCheckBox import
)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsMapLayer
import os


class MirrorProjectDialog(QDialog):
    """
    Dialog for mirroring layers from the master project to child projects.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mirror Project - Export Layers")
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)
        
        self.selected_layers = []
        self.target_projects = []
        
        self.init_ui()
        self.load_master_project_layers()
    
    def init_ui(self):
        """Initialize the user interface."""
        main_layout = QVBoxLayout()
        
        # Title label
        title_label = QLabel("<h2>Mirror Project Tool</h2>")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # Master project info
        master_info = QLabel(f"<b>Master Project:</b> {QgsProject.instance().fileName() or 'Untitled Project'}")
        main_layout.addWidget(master_info)
        
        # Layer selection section
        layer_group = self.create_layer_selection_group()
        main_layout.addWidget(layer_group)
        
        # Target projects section
        projects_group = self.create_target_projects_group()
        main_layout.addWidget(projects_group)
        
        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)
        
        self.setLayout(main_layout)
    
    def create_layer_selection_group(self):
        """Create the layer selection group box."""
        group = QGroupBox("Select Layers to Export")
        layout = QVBoxLayout()
        
        # Instructions
        instructions = QLabel("Select the layers from the master project that you want to export to child projects:")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        
        # Layer list widget
        self.layer_list = QListWidget()
        self.layer_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.layer_list.itemSelectionChanged.connect(self.on_layer_selection_changed)
        layout.addWidget(self.layer_list)
        
        # Selection buttons
        button_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.select_all_layers)
        button_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self.deselect_all_layers)
        button_layout.addWidget(deselect_all_btn)
        
        button_layout.addStretch()
        
        self.selected_count_label = QLabel("Selected: 0 layers")
        button_layout.addWidget(self.selected_count_label)
        
        layout.addLayout(button_layout)
        
        # Options section
        options_group = QGroupBox("Export Options")
        options_layout = QVBoxLayout()
        
        # Skip layers with same name checkbox
        self.skip_same_name_checkbox = QCheckBox("Skip Importing Layers with Same Name")
        self.skip_same_name_checkbox.setChecked(True)  # Default to True
        self.skip_same_name_checkbox.setToolTip(
            "If checked, layers that already exist in the target project with the same name will be skipped.\n"
            "If unchecked, existing layers will be removed and replaced with the new layers."
        )
        self.skip_same_name_checkbox.stateChanged.connect(self.on_skip_same_name_changed)
        options_layout.addWidget(self.skip_same_name_checkbox)
        
        # Replace data source checkbox
        self.replace_data_source_checkbox = QCheckBox("Replace Data Source for Layers With Same Name")
        self.replace_data_source_checkbox.setChecked(False)  # Default to False
        self.replace_data_source_checkbox.setEnabled(False)  # Disabled by default (since skip is checked)
        self.replace_data_source_checkbox.setToolTip(
            "If checked, existing layers with the same name will have their data source updated\n"
            "to point to the new layer source, preserving symbology and other layer properties.\n"
            "This option is only available when 'Skip Importing Layers with Same Name' is unchecked."
        )
        options_layout.addWidget(self.replace_data_source_checkbox)
        
        # Update symbology checkbox
        self.update_symbology_checkbox = QCheckBox("Update Symbology")
        self.update_symbology_checkbox.setChecked(True)  # Default to True
        self.update_symbology_checkbox.setToolTip(
            "If checked, layer symbology (styling, labels, etc.) from the master project will be applied to the exported layers."
        )
        options_layout.addWidget(self.update_symbology_checkbox)
        
        # Fix layer order checkbox
        self.fix_layer_order_checkbox = QCheckBox("Fix Layer Order")
        self.fix_layer_order_checkbox.setChecked(True)  # Default to True
        self.fix_layer_order_checkbox.setToolTip(
            "If checked, layers in the target project will be reordered to match the layer order\n"
            "from the master project. This applies to both new and existing layers."
        )
        options_layout.addWidget(self.fix_layer_order_checkbox)
        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        group.setLayout(layout)
        return group
    
    def create_target_projects_group(self):
        """Create the target projects group box."""
        group = QGroupBox("Target Projects to Update")
        layout = QVBoxLayout()
        
        # Instructions
        instructions = QLabel("Add QGIS project files (.qgs/.qgz) that should receive the exported layers:")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        
        # Projects list widget
        self.projects_list = QListWidget()
        layout.addWidget(self.projects_list)
        
        # Project management buttons
        button_layout = QHBoxLayout()
        
        add_project_btn = QPushButton("Add Project(s)...")
        add_project_btn.clicked.connect(self.add_target_projects)
        button_layout.addWidget(add_project_btn)
        
        remove_project_btn = QPushButton("Remove Selected")
        remove_project_btn.clicked.connect(self.remove_selected_projects)
        button_layout.addWidget(remove_project_btn)
        
        clear_projects_btn = QPushButton("Clear All")
        clear_projects_btn.clicked.connect(self.clear_all_projects)
        button_layout.addWidget(clear_projects_btn)
        
        button_layout.addStretch()
        
        self.projects_count_label = QLabel("Target projects: 0")
        button_layout.addWidget(self.projects_count_label)
        
        layout.addLayout(button_layout)
        
        group.setLayout(layout)
        return group
    
    def load_master_project_layers(self):
        """Load all layers from the current master project."""
        project = QgsProject.instance()
        layers = project.mapLayers().values()
        
        self.layer_list.clear()
        
        for layer in layers:
            if layer and layer.isValid():
                # Create list item with layer name and type
                layer_type = self.get_layer_type_string(layer)
                item_text = f"{layer.name()} ({layer_type})"
                self.layer_list.addItem(item_text)
                # Store the layer ID as item data
                item = self.layer_list.item(self.layer_list.count() - 1)
                item.setData(Qt.UserRole, layer.id())
    
    def get_layer_type_string(self, layer):
        """Get a human-readable string for the layer type."""
        if layer.type() == QgsMapLayer.VectorLayer:
            return "Vector"
        elif layer.type() == QgsMapLayer.RasterLayer:
            return "Raster"
        elif layer.type() == QgsMapLayer.PluginLayer:
            return "Plugin"
        elif layer.type() == QgsMapLayer.MeshLayer:
            return "Mesh"
        elif layer.type() == QgsMapLayer.VectorTileLayer:
            return "Vector Tile"
        else:
            return "Unknown"
    
    def on_layer_selection_changed(self):
        """Handle layer selection changes."""
        selected_items = self.layer_list.selectedItems()
        self.selected_layers = [item.data(Qt.UserRole) for item in selected_items]
        self.selected_count_label.setText(f"Selected: {len(self.selected_layers)} layers")
    
    def on_skip_same_name_changed(self):
        """Handle skip same name checkbox state change."""
        # Enable/disable the replace data source option based on skip same name state
        is_skip_checked = self.skip_same_name_checkbox.isChecked()
        self.replace_data_source_checkbox.setEnabled(not is_skip_checked)
        
        # If skip is checked, uncheck replace data source
        if is_skip_checked:
            self.replace_data_source_checkbox.setChecked(False)
    
    def select_all_layers(self):
        """Select all layers in the list."""
        self.layer_list.selectAll()
    
    def deselect_all_layers(self):
        """Deselect all layers in the list."""
        self.layer_list.clearSelection()
    
    def add_target_projects(self):
        """Open file dialog to add target project files."""
        file_filter = "QGIS Project Files (*.qgs *.qgz);;All Files (*.*)"
        master_project_path = QgsProject.instance().fileName()
        start_dir = os.path.dirname(master_project_path) if master_project_path else ""
        
        project_files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Target QGIS Projects",
            start_dir,
            file_filter
        )
        
        if project_files:
            for project_file in project_files:
                # Don't add the master project itself
                if project_file == master_project_path:
                    QMessageBox.warning(
                        self,
                        "Invalid Selection",
                        "Cannot add the master project as a target project."
                    )
                    continue
                
                # Don't add duplicates
                if project_file not in self.target_projects:
                    self.target_projects.append(project_file)
                    self.projects_list.addItem(project_file)
            
            self.update_projects_count()
    
    def remove_selected_projects(self):
        """Remove selected projects from the list."""
        selected_items = self.projects_list.selectedItems()
        
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select projects to remove.")
            return
        
        for item in selected_items:
            project_path = item.text()
            if project_path in self.target_projects:
                self.target_projects.remove(project_path)
            self.projects_list.takeItem(self.projects_list.row(item))
        
        self.update_projects_count()
    
    def clear_all_projects(self):
        """Clear all target projects."""
        if self.target_projects:
            reply = QMessageBox.question(
                self,
                "Clear All Projects",
                "Are you sure you want to remove all target projects?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.target_projects.clear()
                self.projects_list.clear()
                self.update_projects_count()
    
    def update_projects_count(self):
        """Update the projects count label."""
        self.projects_count_label.setText(f"Target projects: {len(self.target_projects)}")
    
    def get_selected_layers(self):
        """Get the list of selected layer IDs."""
        return self.selected_layers
    
    def get_target_projects(self):
        """Get the list of target project file paths."""
        return self.target_projects
    
    def get_skip_same_name(self):
        """Get whether to skip layers with same name."""
        return self.skip_same_name_checkbox.isChecked()
    
    def get_replace_data_source(self):
        """Get whether to replace data source for layers with same name."""
        return self.replace_data_source_checkbox.isChecked()
    
    def get_update_symbology(self):
        """Get whether to update symbology."""
        return self.update_symbology_checkbox.isChecked()
    
    def get_fix_layer_order(self):
        """Get whether to fix layer order."""
        return self.fix_layer_order_checkbox.isChecked()

    def accept(self):
        """Validate and accept the dialog."""
        if not self.selected_layers:
            QMessageBox.warning(
                self,
                "No Layers Selected",
                "Please select at least one layer to export."
            )
            return
        
        if not self.target_projects:
            QMessageBox.warning(
                self,
                "No Target Projects",
                "Please add at least one target project."
            )
            return
        
        super().accept()

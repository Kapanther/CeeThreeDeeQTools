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
    QTextEdit,
    QCheckBox
)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsMapLayer
import os


class PackageLayerUpdaterDialog(QDialog):
    """
    Dialog for updating layers in geopackages from the active project.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Package Layer Updater")
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)
        
        self.selected_layers = []
        self.target_geopackages = []
        self.project_path = QgsProject.instance().fileName()  # Store project path for relative paths
        
        self.init_ui()
        self.load_project_layers()
        self.load_saved_geopackages()  # Load previously saved geopackages

    def init_ui(self):
        """Initialize the user interface."""
        main_layout = QVBoxLayout()
        
        # Title label
        title_label = QLabel("<h2>Package Layer Updater</h2>")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # Instructions
        instructions = QLabel(
            "This tool updates layers in geopackages with data from the active project. "
            "Select layers from the active project and geopackages to update."
        )
        instructions.setWordWrap(True)
        main_layout.addWidget(instructions)
        
        # Layer selection section
        layer_group = self.create_layer_selection_group()
        main_layout.addWidget(layer_group)
        
        # Geopackage selection section
        geopackage_group = self.create_geopackage_selection_group()
        main_layout.addWidget(geopackage_group)
        
        # Console / log area
        console_group = QGroupBox("Console")
        console_layout = QVBoxLayout()
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setAcceptRichText(False)
        self.console.setMinimumHeight(150)
        console_layout.addWidget(self.console)
        console_group.setLayout(console_layout)
        main_layout.addWidget(console_group)
        
        # Dialog buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = self.button_box.button(QDialogButtonBox.Ok)
        cancel_btn = self.button_box.button(QDialogButtonBox.Cancel)
        
        if ok_btn:
            ok_btn.setText("Update Geopackages")
            ok_btn.setToolTip("Update the selected geopackage layers with data from the active project.")
            ok_btn.setAutoDefault(False)
            ok_btn.setDefault(False)
        
        if cancel_btn:
            cancel_btn.setText("Exit")
            cancel_btn.setToolTip("Close this dialog.")
        
        self.button_box.rejected.connect(self.reject)
        self.button_box.accepted.connect(self._on_start_update)
        main_layout.addWidget(self.button_box)
        
        self.setLayout(main_layout)
        
        self._update_callback = None
        self._update_running = False
    
    def create_layer_selection_group(self):
        """Create the layer selection group box."""
        group = QGroupBox("Select Layers from Active Project")
        layout = QVBoxLayout()
        
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
        options_group = QGroupBox("Update Options")
        options_layout = QVBoxLayout()
        
        # Update new layers only checkbox
        self.update_new_only_checkbox = QCheckBox("Update New Layers Only (Skip Unchanged)")
        self.update_new_only_checkbox.setChecked(True)  # Changed from False to True - default to ON
        self.update_new_only_checkbox.setToolTip(
            "If checked, only layers that have been modified since the last update will be processed.\n"
            "The tool compares the source file's modification date with the last update timestamp in the geopackage."
        )
        options_layout.addWidget(self.update_new_only_checkbox)
        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        group.setLayout(layout)
        return group
    
    def create_geopackage_selection_group(self):
        """Create the geopackage selection group box."""
        group = QGroupBox("Select Geopackages to Update")
        layout = QVBoxLayout()
        
        # Instructions
        instructions = QLabel("Add geopackage files (.gpkg) that should be updated with data from the active project:")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        
        # Geopackages list widget
        self.geopackages_list = QListWidget()
        layout.addWidget(self.geopackages_list)
        
        # Geopackage management buttons
        button_layout = QHBoxLayout()
        
        add_gpkg_btn = QPushButton("Add Geopackage(s)...")
        add_gpkg_btn.clicked.connect(self.add_target_geopackages)
        button_layout.addWidget(add_gpkg_btn)
        
        remove_gpkg_btn = QPushButton("Remove Selected")
        remove_gpkg_btn.clicked.connect(self.remove_selected_geopackages)
        button_layout.addWidget(remove_gpkg_btn)
        
        clear_gpkg_btn = QPushButton("Clear All")
        clear_gpkg_btn.clicked.connect(self.clear_all_geopackages)
        button_layout.addWidget(clear_gpkg_btn)
        
        button_layout.addStretch()
        
        self.geopackages_count_label = QLabel("Geopackages: 0")
        button_layout.addWidget(self.geopackages_count_label)
        
        layout.addLayout(button_layout)
        group.setLayout(layout)
        return group
    
    def load_project_layers(self):
        """Load all layers from the current project."""
        project = QgsProject.instance()
        layers = project.mapLayers().values()
        
        self.layer_list.clear()
        
        for layer in layers:
            if layer and layer.isValid():
                # Include both vector and raster layers
                if layer.type() == QgsMapLayer.VectorLayer:
                    item_text = f"{layer.name()} (Vector - {layer.geometryType().name if hasattr(layer, 'geometryType') else 'Unknown'})"
                    self.layer_list.addItem(item_text)
                    item = self.layer_list.item(self.layer_list.count() - 1)
                    item.setData(Qt.UserRole, layer.id())
                elif layer.type() == QgsMapLayer.RasterLayer:
                    item_text = f"{layer.name()} (Raster)"
                    self.layer_list.addItem(item_text)
                    item = self.layer_list.item(self.layer_list.count() - 1)
                    item.setData(Qt.UserRole, layer.id())

    def on_layer_selection_changed(self):
        """Handle layer selection changes."""
        selected_items = self.layer_list.selectedItems()
        self.selected_layers = [item.data(Qt.UserRole) for item in selected_items]
        self.selected_count_label.setText(f"Selected: {len(self.selected_layers)} layers")
    
    def select_all_layers(self):
        """Select all layers in the list."""
        self.layer_list.selectAll()
    
    def deselect_all_layers(self):
        """Deselect all layers in the list."""
        self.layer_list.clearSelection()
    
    def add_target_geopackages(self):
        """Open file dialog to add target geopackage files."""
        file_filter = "GeoPackage Files (*.gpkg);;All Files (*.*)"
        project_path = QgsProject.instance().fileName()
        start_dir = os.path.dirname(project_path) if project_path else ""
        
        gpkg_files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select GeoPackage Files",
            start_dir,
            file_filter
        )
        
        if gpkg_files:
            for gpkg_file in gpkg_files:
                if gpkg_file not in self.target_geopackages:
                    self.target_geopackages.append(gpkg_file)
                    self.geopackages_list.addItem(gpkg_file)
                else:
                    QMessageBox.information(
                        self,
                        "Already Added",
                        f"This geopackage is already in the list:\n\n{gpkg_file}"
                    )
            
            self.update_geopackages_count()
            self.save_geopackages_to_project()  # Save selections when modified

    def remove_selected_geopackages(self):
        """Remove selected geopackages from the list."""
        selected_items = self.geopackages_list.selectedItems()
        
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select geopackages to remove.")
            return
        
        for item in selected_items:
            gpkg_path = item.text()
            if gpkg_path in self.target_geopackages:
                self.target_geopackages.remove(gpkg_path)
            self.geopackages_list.takeItem(self.geopackages_list.row(item))
        
        self.update_geopackages_count()
        self.save_geopackages_to_project()  # Save selections when modified

    def clear_all_geopackages(self):
        """Clear all geopackages."""
        if self.target_geopackages:
            reply = QMessageBox.question(
                self,
                "Clear All Geopackages",
                "Are you sure you want to remove all geopackages?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.target_geopackages.clear()
                self.geopackages_list.clear()
                self.update_geopackages_count()
                self.save_geopackages_to_project()  # Save selections when modified

    def update_geopackages_count(self):
        """Update the geopackages count label."""
        self.geopackages_count_label.setText(f"Geopackages: {len(self.target_geopackages)}")
    
    def get_selected_layers(self):
        """Get the list of selected layer IDs."""
        return self.selected_layers
    
    def get_target_geopackages(self):
        """Get the list of target geopackage file paths."""
        return self.target_geopackages
    
    def get_update_new_only(self):
        """Get whether to update only new/modified layers."""
        return self.update_new_only_checkbox.isChecked()
    
    def append_console(self, message: str):
        """Append a line to the console."""
        try:
            self.console.append(str(message))
        except Exception:
            pass
    
    def clear_console(self):
        """Clear the console."""
        try:
            self.console.clear()
        except Exception:
            pass
    
    def display_results(self, results: dict):
        """Display the update results in the console."""
        try:
            self.append_console("\n=== Package Layer Updater - Results ===")
            self.append_console(f"Success: {results.get('success', False)}")
            self.append_console(f"Geopackages updated: {results.get('geopackages_updated', 0)}")
            self.append_console(f"Layers updated: {results.get('layers_updated', 0)}")
            self.append_console(f"Layers skipped: {results.get('layers_skipped', 0)}")
            
            warnings = results.get('warnings', [])
            errors = results.get('errors', [])
            
            if warnings:
                self.append_console(f"\nWarnings ({len(warnings)}):")
                for w in warnings:
                    self.append_console(f"  - {w}")
            
            if errors:
                self.append_console(f"\nErrors ({len(errors)}):")
                for e in errors:
                    self.append_console(f"  - {e}")
            
            self.append_console("\n=== End Results ===\n")
        except Exception:
            pass
    
    def set_update_callback(self, callback):
        """Register a callback that performs the update."""
        self._update_callback = callback
    
    def _on_start_update(self):
        """Handler for Update button."""
        if self._update_running:
            return
        
        # Validate selections
        if not self.selected_layers:
            QMessageBox.warning(self, "No Layers Selected", "Please select at least one layer to update.")
            return
        
        if not self.target_geopackages:
            QMessageBox.warning(self, "No Geopackages", "Please add at least one geopackage.")
            return
        
        if not self._update_callback:
            QMessageBox.critical(self, "No Update Callback", "No update callback has been registered.")
            return
        
        # Run update
        try:
            self._update_running = True
            self.button_box.button(QDialogButtonBox.Ok).setEnabled(False)
            
            self.clear_console()
            self.append_console("Starting geopackage update...\n")
            
            def progress_cb(message, percent):
                try:
                    self.append_console(f"[{percent}%] {message}")
                except Exception:
                    pass
            
            self._update_callback(progress_cb)
        
        finally:
            try:
                self.button_box.button(QDialogButtonBox.Ok).setEnabled(True)
            except Exception:
                pass
            self._update_running = False
    
    def save_geopackages_to_project(self):
        """
        Save the target geopackages to the QGIS project custom properties.
        Paths are stored as relative paths when possible for portability.
        """
        try:
            project = QgsProject.instance()
            
            if not project.fileName():
                # Project not saved yet, can't use relative paths
                return
            
            project_dir = os.path.dirname(project.fileName())
            
            # Convert to relative paths
            relative_paths = []
            for gpkg_path in self.target_geopackages:
                try:
                    # Try to make relative path
                    rel_path = os.path.relpath(gpkg_path, project_dir)
                    # Only use relative path if it doesn't start with ".."
                    # (i.e., geopackage is within or below project directory)
                    if not rel_path.startswith('..'):
                        relative_paths.append(f"REL:{rel_path}")
                    else:
                        # Use absolute path if outside project tree
                        relative_paths.append(f"ABS:{gpkg_path}")
                except Exception:
                    # If relpath fails, use absolute
                    relative_paths.append(f"ABS:{gpkg_path}")
            
            # Save to project custom properties
            project.writeEntry("PackageLayerUpdater", "target_geopackages", relative_paths)
            
            print(f"Saved {len(relative_paths)} geopackage paths to project")
            
        except Exception as e:
            print(f"Error saving geopackages to project: {e}")

    def load_saved_geopackages(self):
        """
        Load previously saved geopackages from the QGIS project custom properties.
        Converts relative paths back to absolute paths.
        """
        try:
            project = QgsProject.instance()
            
            if not project.fileName():
                # Project not saved yet, nothing to load
                return
            
            project_dir = os.path.dirname(project.fileName())
            
            # Read from project custom properties
            saved_paths, ok = project.readListEntry("PackageLayerUpdater", "target_geopackages")
            
            if not ok or not saved_paths:
                return
            
            # Convert back to absolute paths and add to list
            loaded_count = 0
            for path_entry in saved_paths:
                try:
                    if path_entry.startswith("REL:"):
                        # Relative path - convert to absolute
                        rel_path = path_entry[4:]  # Remove "REL:" prefix
                        abs_path = os.path.normpath(os.path.join(project_dir, rel_path))
                    elif path_entry.startswith("ABS:"):
                        # Absolute path - use as is
                        abs_path = path_entry[4:]  # Remove "ABS:" prefix
                    else:
                        # Legacy format (no prefix) - assume relative
                        abs_path = os.path.normpath(os.path.join(project_dir, path_entry))
                    
                    # Check if file exists
                    if os.path.exists(abs_path):
                        if abs_path not in self.target_geopackages:
                            self.target_geopackages.append(abs_path)
                            self.geopackages_list.addItem(abs_path)
                            loaded_count += 1
                    else:
                        print(f"Skipping non-existent geopackage: {abs_path}")
                
                except Exception as e:
                    print(f"Error loading geopackage path '{path_entry}': {e}")
            
            if loaded_count > 0:
                self.update_geopackages_count()
                self.append_console(f"Loaded {loaded_count} saved geopackage(s) from project")
                print(f"Loaded {loaded_count} geopackage paths from project")
        
        except Exception as e:
            print(f"Error loading saved geopackages: {e}")

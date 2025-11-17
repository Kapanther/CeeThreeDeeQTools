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
        
        # Fix FIDs checkbox
        self.fix_fids_checkbox = QCheckBox("Fix Invalid FIDs")
        self.fix_fids_checkbox.setChecked(False)  # Default to OFF
        self.fix_fids_checkbox.setToolTip(
            "If checked, FID problems (duplicates, NULL values, etc.) will be automatically fixed.\n"
            "Duplicate FIDs will be renumbered to the next available values.\n"
            "If unchecked, layers with invalid FIDs will be skipped with a warning,\n"
            "since geopackages require unique, non-NULL FID values."
        )
        options_layout.addWidget(self.fix_fids_checkbox)
        
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
                # Store as relative path if possible, otherwise absolute
                stored_path = self._make_portable_path(gpkg_file)
                
                # Check for duplicates before adding (compare resolved absolute paths)
                if not self._is_duplicate_path(stored_path):
                    self.target_geopackages.append(stored_path)
                    # Display the path (relative if possible)
                    display_path = self._get_display_path(stored_path)
                    self.geopackages_list.addItem(display_path)
                else:
                    QMessageBox.information(
                        self,
                        "Already Added",
                        f"This geopackage is already in the list:\n\n{self._get_display_path(stored_path)}"
                    )
            
            self.update_geopackages_count()
            self.save_geopackages_to_project()

    def _make_portable_path(self, absolute_path):
        """
        Convert an absolute path to a relative path if possible for portability.
        
        Args:
            absolute_path: Absolute path to convert
        
        Returns:
            str: Relative path if within project tree, otherwise absolute path
        """
        try:
            project_path = QgsProject.instance().fileName()
            if not project_path:
                return os.path.normpath(absolute_path)
            
            project_dir = os.path.dirname(project_path)
            rel_path = os.path.relpath(absolute_path, project_dir)
            
            # Only use relative path if it doesn't go up beyond project dir
            if not rel_path.startswith('..'):
                return rel_path
            else:
                return os.path.normpath(absolute_path)
        except Exception:
            return os.path.normpath(absolute_path)

    def _resolve_to_absolute(self, stored_path):
        """
        Resolve a stored path (relative or absolute) to an absolute path.
        
        Args:
            stored_path: Path as stored (may be relative or absolute)
        
        Returns:
            str: Absolute normalized path
        """
        try:
            # If already absolute, just normalize
            if os.path.isabs(stored_path):
                return os.path.normpath(stored_path)
            
            # Otherwise, resolve relative to project directory
            project_path = QgsProject.instance().fileName()
            if project_path:
                project_dir = os.path.dirname(project_path)
                return os.path.normpath(os.path.join(project_dir, stored_path))
            
            # Fallback: normalize as-is
            return os.path.normpath(stored_path)
        except Exception:
            return os.path.normpath(stored_path)

    def _is_duplicate_path(self, new_path):
        """
        Check if a path already exists in the target_geopackages list.
        
        Args:
            new_path: Path to check (may be relative or absolute)
        
        Returns:
            bool: True if path already exists
        """
        new_abs = self._resolve_to_absolute(new_path)
        for existing_path in self.target_geopackages:
            existing_abs = self._resolve_to_absolute(existing_path)
            if new_abs == existing_abs:
                return True
        return False

    def _get_display_path(self, stored_path):
        """
        Get a display-friendly version of a stored path.
        
        Args:
            stored_path: Path as stored (may be relative or absolute)
        
        Returns:
            str: Same path for display (relative paths stay relative, absolute stay absolute)
        """
        # For display, we just show what's stored (already portable/relative if possible)
        return stored_path

    def remove_selected_geopackages(self):
        """Remove selected geopackages from the list."""
        selected_items = self.geopackages_list.selectedItems()
        
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select geopackages to remove.")
            return
        
        for item in selected_items:
            display_path = item.text()
            
            # Find and remove the matching stored path
            # Compare resolved absolute paths
            display_abs = self._resolve_to_absolute(display_path)
            for stored_path in self.target_geopackages[:]:  # Iterate over copy
                if self._resolve_to_absolute(stored_path) == display_abs:
                    self.target_geopackages.remove(stored_path)
                    break
            
            self.geopackages_list.takeItem(self.geopackages_list.row(item))
        
        self.update_geopackages_count()
        self.save_geopackages_to_project()

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
                self.save_geopackages_to_project()

    def update_geopackages_count(self):
        """Update the geopackages count label."""
        self.geopackages_count_label.setText(f"Geopackages: {len(self.target_geopackages)}")

    def get_selected_layers(self):
        """Get the list of selected layer IDs."""
        return self.selected_layers

    def get_target_geopackages(self):
        """
        Get the list of target geopackage file paths (resolved to absolute).
        
        Returns:
            list: List of absolute paths to geopackages
        """
        # Return absolute paths for use by the logic layer
        return [self._resolve_to_absolute(p) for p in self.target_geopackages]

    def save_geopackages_to_project(self):
        """
        Save the target geopackages to the QGIS project custom properties.
        Paths are already stored as relative when possible.
        """
        try:
            project = QgsProject.instance()
            
            if not project.fileName():
                return
            
            # Save paths as-is (already portable/relative when possible)
            project.writeEntry("PackageLayerUpdater", "target_geopackages", self.target_geopackages)
            
            print(f"Saved {len(self.target_geopackages)} geopackage paths to project")
            
        except Exception as e:
            print(f"Error saving geopackages to project: {e}")

    def load_saved_geopackages(self):
        """
        Load previously saved geopackages from the QGIS project custom properties.
        """
        try:
            project = QgsProject.instance()
            
            if not project.fileName():
                return
            
            # Read from project custom properties
            saved_paths, ok = project.readListEntry("PackageLayerUpdater", "target_geopackages")
            
            if not ok or not saved_paths:
                return
            
            # Load paths and verify they exist
            loaded_count = 0
            for stored_path in saved_paths:
                try:
                    # Resolve to absolute to check if file exists
                    abs_path = self._resolve_to_absolute(stored_path)
                    
                    if os.path.exists(abs_path):
                        # Check for duplicates
                        if not self._is_duplicate_path(stored_path):
                            self.target_geopackages.append(stored_path)
                            # Display the path (already relative if it was stored that way)
                            self.geopackages_list.addItem(self._get_display_path(stored_path))
                            loaded_count += 1
                    else:
                        print(f"Skipping non-existent geopackage: {abs_path}")
                
                except Exception as e:
                    print(f"Error loading geopackage path '{stored_path}': {e}")
            
            if loaded_count > 0:
                self.update_geopackages_count()
                self.append_console(f"Loaded {loaded_count} saved geopackage(s) from project")
                print(f"Loaded {loaded_count} geopackage paths from project")
        
        except Exception as e:
            print(f"Error loading saved geopackages: {e}")

    def get_update_new_only(self):
        """Get whether to update only new/modified layers."""
        return self.update_new_only_checkbox.isChecked()
    
    def get_fix_fids(self):
        """Get whether to fix duplicate FIDs."""
        return self.fix_fids_checkbox.isChecked()

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
            # Display warnings first (these appear during processing)
            warnings = results.get('warnings', [])
            if warnings:
                for w in warnings:
                    self.append_console(f"{w}")
            
            # Display errors
            errors = results.get('errors', [])
            if errors:
                self.append_console(f"\nErrors ({len(errors)}):")
                for e in errors:
                    self.append_console(f"  - {e}")
            
            # Display summary last
            self.append_console("\n=== Package Layer Updater - Results ===")
            self.append_console(f"Success: {results.get('success', False)}")
            self.append_console(f"Geopackages updated: {results.get('geopackages_updated', 0)}")
            self.append_console(f"Layers updated: {results.get('layers_updated', 0)}")
            self.append_console(f"Layers skipped: {results.get('layers_skipped', 0)}")
            
            layers_not_found = results.get('layers_not_found', 0)
            if layers_not_found > 0:
                self.append_console(f"Layers not found in any geopackage: {layers_not_found}")
            
            fids_fixed = results.get('fids_fixed', 0)
            if fids_fixed > 0:
                self.append_console(f"FIDs fixed: {fids_fixed}")
            
            self.append_console("=== End Results ===\n")
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

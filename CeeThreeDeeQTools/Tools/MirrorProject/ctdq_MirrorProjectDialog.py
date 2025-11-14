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
    QCheckBox,  # Add QCheckBox import
    QTextEdit  # add QTextEdit import for console
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
        self.setMinimumWidth(1200)  # Increased width to accommodate layouts
        self.setMinimumHeight(600)
        
        self.selected_layers = []
        self.target_projects = []
        self.selected_themes = []  # Add selected themes list
        self.selected_layouts = []  # Add selected layouts list
        self.master_project_path = QgsProject.instance().fileName()  # Store master project path
        
        self.init_ui()
        self.load_master_project_layers()
        self.load_master_project_themes()  # Load themes
        self.load_master_project_layouts()  # Load layouts

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
        # Relabel buttons to be clearer and reduce accidental activation
        ok_btn = self.button_box.button(QDialogButtonBox.Ok)
        cancel_btn = self.button_box.button(QDialogButtonBox.Cancel)
        if ok_btn:
            ok_btn.setText("Run Mirror Project")
            ok_btn.setToolTip("Run the mirror export. The dialog will remain open so you can review the console output.")
            # Prevent Enter key from triggering the run accidentally
            try:
                ok_btn.setAutoDefault(False)
                ok_btn.setDefault(False)
            except Exception:
                pass
        if cancel_btn:
            cancel_btn.setText("Exit")
            cancel_btn.setToolTip("Close this dialog (any running export should be cancelled first).")

        # Connect Cancel to close dialog
        self.button_box.rejected.connect(self.reject)
        # Connect OK to custom start-export handler (does not close dialog)
        self.button_box.accepted.connect(self._on_start_export)
        main_layout.addWidget(self.button_box)
        
        self.setLayout(main_layout)
        # callback placeholder; plugin will set via set_export_callback
        self._export_callback = None
        self._export_running = False
    
    def create_layer_selection_group(self):
        """Create the layer selection group box."""
        group = QGroupBox("Select Layers, Themes, and Layouts to Export")
        layout = QVBoxLayout()
        
        # Instructions
        instructions = QLabel("Select the layers, map themes, and print layouts from the master project that you want to export to child projects:")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        
        # Create horizontal layout for layers, themes, and layouts side-by-side
        lists_layout = QHBoxLayout()
        
        # Layer selection (left side)
        layer_container = QVBoxLayout()
        layer_label = QLabel("<b>Layers</b>")
        layer_container.addWidget(layer_label)
        
        self.layer_list = QListWidget()
        self.layer_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.layer_list.itemSelectionChanged.connect(self.on_layer_selection_changed)
        layer_container.addWidget(self.layer_list)
        
        # Layer selection buttons
        layer_button_layout = QHBoxLayout()
        select_all_layers_btn = QPushButton("Select All")
        select_all_layers_btn.clicked.connect(self.select_all_layers)
        layer_button_layout.addWidget(select_all_layers_btn)
        
        deselect_all_layers_btn = QPushButton("Deselect All")
        deselect_all_layers_btn.clicked.connect(self.deselect_all_layers)
        layer_button_layout.addWidget(deselect_all_layers_btn)
        layer_container.addLayout(layer_button_layout)
        
        self.selected_count_label = QLabel("Selected: 0 layers")
        layer_container.addWidget(self.selected_count_label)
        
        lists_layout.addLayout(layer_container)
        
        # Theme selection (middle)
        theme_container = QVBoxLayout()
        theme_label = QLabel("<b>Map Themes</b>")
        theme_container.addWidget(theme_label)
        
        self.theme_list = QListWidget()
        self.theme_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.theme_list.itemSelectionChanged.connect(self.on_theme_selection_changed)
        theme_container.addWidget(self.theme_list)
        
        # Theme selection buttons
        theme_button_layout = QHBoxLayout()
        select_all_themes_btn = QPushButton("Select All")
        select_all_themes_btn.clicked.connect(self.select_all_themes)
        theme_button_layout.addWidget(select_all_themes_btn)
        
        deselect_all_themes_btn = QPushButton("Deselect All")
        deselect_all_themes_btn.clicked.connect(self.deselect_all_themes)
        theme_button_layout.addWidget(deselect_all_themes_btn)
        theme_container.addLayout(theme_button_layout)
        
        self.selected_themes_count_label = QLabel("Selected: 0 themes")
        theme_container.addWidget(self.selected_themes_count_label)
        
        lists_layout.addLayout(theme_container)
        
        # Layout selection (right side)
        layout_container = QVBoxLayout()
        layout_label = QLabel("<b>Print Layouts</b>")
        layout_container.addWidget(layout_label)
        
        self.layout_list = QListWidget()
        self.layout_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.layout_list.itemSelectionChanged.connect(self.on_layout_selection_changed)
        layout_container.addWidget(self.layout_list)
        
        # Layout selection buttons
        layout_button_layout = QHBoxLayout()
        select_all_layouts_btn = QPushButton("Select All")
        select_all_layouts_btn.clicked.connect(self.select_all_layouts)
        layout_button_layout.addWidget(select_all_layouts_btn)
        
        deselect_all_layouts_btn = QPushButton("Deselect All")
        deselect_all_layouts_btn.clicked.connect(self.deselect_all_layouts)
        layout_button_layout.addWidget(deselect_all_layouts_btn)
        layout_container.addLayout(layout_button_layout)
        
        self.selected_layouts_count_label = QLabel("Selected: 0 layouts")
        layout_container.addWidget(self.selected_layouts_count_label)
        
        lists_layout.addLayout(layout_container)
        
        layout.addLayout(lists_layout)
        
        # Options section
        options_group = QGroupBox("Export Options")
        options_layout = QHBoxLayout()  # Changed from QVBoxLayout to QHBoxLayout
        
        # Existing Layer Handling sub-panel
        existing_group = QGroupBox("Existing Layer Handling")
        existing_layout = QVBoxLayout()
        
        # Replace data source checkbox (now independent)
        self.replace_data_source_checkbox = QCheckBox("Replace Data Source for Layers With Same Name")
        self.replace_data_source_checkbox.setChecked(False)  # Default to False
        self.replace_data_source_checkbox.setToolTip(
            "If checked, existing layers with the same name will have their data source updated\n"
            "to point to the new layer source, preserving symbology and other layer properties."
        )
        existing_layout.addWidget(self.replace_data_source_checkbox)
        
        # Update symbology checkbox (now in existing handling)
        self.update_symbology_checkbox = QCheckBox("Update Symbology")
        self.update_symbology_checkbox.setChecked(True)  # Default to True
        self.update_symbology_checkbox.setToolTip(
            "If checked, layer symbology (styling, labels, etc.) from the master project will be applied to the exported layers."
        )
        existing_layout.addWidget(self.update_symbology_checkbox)
        
        # Preserve layer filters checkbox
        self.preserve_layer_filters_checkbox = QCheckBox("Preserve Layer Filters")
        self.preserve_layer_filters_checkbox.setChecked(True)  # Default to True
        self.preserve_layer_filters_checkbox.setToolTip(
            "If checked, existing layer filters in the child projects will be preserved.\n"
            "If unchecked, filters from the master project will be applied."
        )
        existing_layout.addWidget(self.preserve_layer_filters_checkbox)
        
        # Preserve auxiliary tables checkbox (new)
        self.preserve_auxiliary_tables_checkbox = QCheckBox("Preserve Auxiliary Tables (Label Drags, etc.)")
        self.preserve_auxiliary_tables_checkbox.setChecked(True)  # Default to True
        self.preserve_auxiliary_tables_checkbox.setToolTip(
            "If checked, auxiliary data in child projects will be preserved.\n"
            "This includes label drag positions, custom label rotations, and other manually adjusted properties.\n"
            "If unchecked, auxiliary data from the master project will be applied."
        )
        existing_layout.addWidget(self.preserve_auxiliary_tables_checkbox)
        
        existing_group.setLayout(existing_layout)
        options_layout.addWidget(existing_group)
        
        # New Layer Handling sub-panel
        new_group = QGroupBox("New Layer Handling")
        new_layout = QVBoxLayout()
        
        # Fix layer order checkbox moved here
        self.fix_layer_order_checkbox = QCheckBox("Fix Layer Order")
        self.fix_layer_order_checkbox.setChecked(True)  # Default to True
        self.fix_layer_order_checkbox.setToolTip(
            "If checked, layers in the target project will be reordered to match the layer order\n"
            "from the master project. This applies to both new and existing layers."
        )
        new_layout.addWidget(self.fix_layer_order_checkbox)

        # Add layer groups checkbox (new)
        self.add_layer_groups_checkbox = QCheckBox("Add Layer Groups from Master")
        self.add_layer_groups_checkbox.setChecked(True)  # Default to True
        self.add_layer_groups_checkbox.setToolTip(
            "If checked, layer groups from the master project will be replicated in the target projects.\n"
            "Layers will be organized into the same groups as in the master project."
        )
        new_layout.addWidget(self.add_layer_groups_checkbox)

        new_group.setLayout(new_layout)
        options_layout.addWidget(new_group)

        othersettings_group = QGroupBox("Other Settings")
        othersettings_layout = QVBoxLayout()

        # Create backups checkbox (new)
        self.create_backups_checkbox = QCheckBox("Create Project Backups (MirrorProjectBackup folder)")
        self.create_backups_checkbox.setChecked(True)  # Default to True
        self.create_backups_checkbox.setToolTip(
            "If checked, a backup copy of each target project will be created in a folder\n"
            "'MirrorProjectBackup' next to the project file before it is modified."
        )
        othersettings_layout.addWidget(self.create_backups_checkbox)

        othersettings_group.setLayout(othersettings_layout)              
        options_layout.addWidget(othersettings_group)

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
    
    def select_all_layers(self):
        """Select all layers in the list."""
        self.layer_list.selectAll()
    
    def deselect_all_layers(self):
        """Deselect all layers in the list."""
        self.layer_list.clearSelection()
    
    def load_master_project_themes(self):
        """Load all map themes from the current master project."""
        project = QgsProject.instance()
        theme_collection = project.mapThemeCollection()
        
        self.theme_list.clear()
        
        theme_names = theme_collection.mapThemes()
        for theme_name in theme_names:
            self.theme_list.addItem(theme_name)
        
        if not theme_names:
            # Add a placeholder if no themes exist
            item = self.theme_list.addItem("(No map themes in master project)")
            self.theme_list.item(0).setFlags(Qt.NoItemFlags)  # Make it unselectable

    def on_theme_selection_changed(self):
        """Handle theme selection changes."""
        selected_items = self.theme_list.selectedItems()
        self.selected_themes = [item.text() for item in selected_items]
        self.selected_themes_count_label.setText(f"Selected: {len(self.selected_themes)} themes")
    
    def select_all_themes(self):
        """Select all themes in the list."""
        self.theme_list.selectAll()
    
    def deselect_all_themes(self):
        """Deselect all themes in the list."""
        self.theme_list.clearSelection()
    
    def load_master_project_layouts(self):
        """Load all print layouts from the current master project."""
        project = QgsProject.instance()
        layout_manager = project.layoutManager()
        
        self.layout_list.clear()
        
        layouts = layout_manager.layouts()
        for layout in layouts:
            self.layout_list.addItem(layout.name())
        
        if not layouts:
            # Add a placeholder if no layouts exist
            self.layout_list.addItem("(No print layouts in master project)")
            self.layout_list.item(0).setFlags(Qt.NoItemFlags)  # Make it unselectable

    def on_layout_selection_changed(self):
        """Handle layout selection changes."""
        selected_items = self.layout_list.selectedItems()
        self.selected_layouts = [item.text() for item in selected_items]
        self.selected_layouts_count_label.setText(f"Selected: {len(self.selected_layouts)} layouts")
    
    def select_all_layouts(self):
        """Select all layouts in the list."""
        self.layout_list.selectAll()
    
    def deselect_all_layouts(self):
        """Deselect all layouts in the list."""
        self.layout_list.clearSelection()
    
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
                if project_file == self.master_project_path:
                    QMessageBox.warning(
                        self,
                        "Invalid Selection",
                        f"Cannot add the master project as a target project.\n\nMaster project:\n{self.master_project_path}"
                    )
                    continue
                
                # Don't add duplicates
                if project_file not in self.target_projects:
                    self.target_projects.append(project_file)
                    self.projects_list.addItem(project_file)
                else:
                    QMessageBox.information(
                        self,
                        "Already Added",
                        f"This project is already in the target list:\n\n{project_file}"
                    )
            
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
    
    def get_selected_themes(self):
        """Get the list of selected theme names."""
        return self.selected_themes
    
    def get_selected_layouts(self):
        """Get the list of selected layout names."""
        return self.selected_layouts

    def get_target_projects(self):
        """Get the list of target project file paths."""
        return self.target_projects
    
    def get_replace_data_source(self):
        """Get whether to replace data source for layers with same name."""
        return self.replace_data_source_checkbox.isChecked()
    
    def get_update_symbology(self):
        """Get whether to update symbology."""
        return self.update_symbology_checkbox.isChecked()
    
    def get_fix_layer_order(self):
        """Get whether to fix layer order."""
        return self.fix_layer_order_checkbox.isChecked()

    def get_add_layer_groups(self):
        """Get whether to add layer groups from master project."""
        return self.add_layer_groups_checkbox.isChecked()

    def get_create_backups(self):
        """Get whether to create backups of target projects before editing."""
        return self.create_backups_checkbox.isChecked()

    def get_preserve_layer_filters(self):
        """Get whether to preserve layer filters in child projects."""
        return self.preserve_layer_filters_checkbox.isChecked()

    def get_preserve_auxiliary_tables(self):
        """Get whether to preserve auxiliary tables in child projects."""
        return self.preserve_auxiliary_tables_checkbox.isChecked()

    def append_console(self, message: str):
        """Append a line to the console (thread-safe-ish for single-threaded use)."""
        try:
            # Ensure message is string and add newline
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
        """
        Display the export results dict in the console in a readable format.
        """
        try:
            self.append_console("\n=== Mirror Project - Results ===")
            self.append_console(f"Success: {results.get('success', False)}")
            self.append_console(f"Projects updated: {results.get('projects_updated', 0)}")
            self.append_console(f"Layers exported: {results.get('layers_exported', 0)}")
            self.append_console(f"Themes exported: {results.get('themes_exported', 0)}")
            self.append_console(f"Layouts exported: {results.get('layouts_exported', 0)}")
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

    def set_export_callback(self, callback):
        """Register a callback that performs the export. The callback will be called when OK is pressed.
        The callback should accept a single argument: a function to use as a progress callback: (message, percent)."""
        self._export_callback = callback

    def _on_start_export(self):
        """Handler for OK button. Validate inputs then call the registered export callback without closing the dialog."""
        if self._export_running:
            return

        # Validate selections (same checks as previous accept)
        if not self.selected_layers:
            QMessageBox.warning(self, "No Layers Selected", "Please select at least one layer to export.")
            return
        if not self.target_projects:
            QMessageBox.warning(self, "No Target Projects", "Please add at least one target project.")
            return

        # Double-check that master project is not in the target list
        if self.master_project_path in self.target_projects:
            QMessageBox.critical(
                self,
                "Invalid Configuration",
                f"The master project cannot be in the target projects list.\n\nMaster project:\n{self.master_project_path}\n\nPlease remove it from the target list."
            )
            return

        if not self._export_callback:
            QMessageBox.critical(self, "No Export Callback", "No export callback has been registered.")
            return

        # Run export (synchronous) but keep dialog open. Disable OK to prevent re-entry.
        try:
            self._export_running = True
            self.button_box.button(QDialogButtonBox.Ok).setEnabled(False)
            # Clear console and start
            self.clear_console()
            self.append_console("Starting mirror export...\n")
            # Call the plugin-provided callback; it must accept (append_log, progress_callback) or similar.
            # We pass two helpers: append_console and a progress updater lambda
            def progress_cb(message, percent):
                # Ensure message is visible in console as well
                try:
                    self.append_console(f"[{percent}%] {message}")
                except Exception:
                    pass

            # Call export callback (plugin is responsible for catching exceptions and writing results)
            self._export_callback(progress_cb)

        finally:
            # Re-enable OK
            try:
                self.button_box.button(QDialogButtonBox.Ok).setEnabled(True)
            except Exception:
                pass
            self._export_running = False

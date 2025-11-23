"""Context menu for layer operations."""

from qgis.PyQt.QtWidgets import QMenu, QApplication, QInputDialog
from qgis.PyQt.QtCore import QObject, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsVectorLayer,
    QgsRasterLayer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject
)
from qgis.gui import QgsProjectionSelectionDialog
from ..services.layer_service import LayerService
from ..services.visibility_service import VisibilityService


class LayerContextMenu:
    """Handles context menu creation and actions for layers."""
    
    @staticmethod
    def create_layer_menu(layer, iface, rename_callback=None, debug_callback=None):
        """
        Create context menu for a layer with all standard actions.
        
        Args:
            layer: QgsMapLayer object
            iface: QgisInterface instance
            rename_callback: Optional callback for rename action
            debug_callback: Optional callback for debug logging
        
        Returns:
            QMenu: The created menu
        """
        menu = QMenu()
        
        # Zoom to layer
        zoom_action = menu.addAction(QIcon(":/images/themes/default/mActionZoomToLayer.svg"), "Zoom to Layer")
        zoom_action.triggered.connect(lambda: LayerContextMenu.zoom_to_layer(layer, iface))
        
        # Zoom to selected features (for vector layers)
        if isinstance(layer, QgsVectorLayer) and layer.selectedFeatureCount() > 0:
            zoom_selected_action = menu.addAction(QIcon(":/images/themes/default/mActionZoomToSelected.svg"), "Zoom to Selected")
            zoom_selected_action.triggered.connect(lambda: iface.mapCanvas().zoomToSelected(layer))
        
        menu.addSeparator()
        
        # Show attribute table (for vector layers)
        if isinstance(layer, QgsVectorLayer):
            attr_table_action = menu.addAction(QIcon(":/images/themes/default/mActionOpenTable.svg"), "Open Attribute Table")
            attr_table_action.triggered.connect(lambda: iface.showAttributeTable(layer))
        
        # Show properties
        props_action = menu.addAction(QIcon(":/images/themes/default/mActionOptions.svg"), "Properties...")
        props_action.triggered.connect(lambda: iface.showLayerProperties(layer))
        
        # Layer styling panel
        style_action = menu.addAction(QIcon(":/images/themes/default/mActionStyleManager.svg"), "Edit Layer Style")
        style_action.triggered.connect(lambda: LayerContextMenu.open_layer_styling_panel(layer, iface))
        
        menu.addSeparator()
        
        # Toggle editing (for vector layers)
        if isinstance(layer, QgsVectorLayer):
            if layer.isEditable():
                toggle_edit_action = menu.addAction(QIcon(":/images/themes/default/mActionToggleEditing.svg"), "Toggle Editing (On)")
                toggle_edit_action.triggered.connect(lambda: layer.rollBack())
            else:
                toggle_edit_action = menu.addAction(QIcon(":/images/themes/default/mActionToggleEditing.svg"), "Toggle Editing")
                toggle_edit_action.triggered.connect(lambda: layer.startEditing())
            menu.addSeparator()
        
        # Duplicate layer
        duplicate_action = menu.addAction(QIcon(":/images/themes/default/mActionDuplicateLayer.svg"), "Duplicate Layer")
        duplicate_action.triggered.connect(lambda: LayerContextMenu.duplicate_layer(layer))
        
        # Rename layer (triggers inline editing)
        rename_action = menu.addAction(QIcon(":/images/themes/default/mActionEditableEdits.svg"), "Rename Layer\tF2")
        if rename_callback:
            rename_action.triggered.connect(rename_callback)
        
        menu.addSeparator()
        
        # Change Data Source
        change_source_action = menu.addAction(QIcon(":/images/themes/default/mActionChangeLabelProperties.svg"), "Change Data Source...")
        change_source_action.triggered.connect(lambda: LayerContextMenu.change_data_source(layer, iface, debug_callback))
        
        # Set layer CRS
        set_crs_action = menu.addAction(QIcon(":/images/themes/default/mActionSetProjection.svg"), "Set Layer CRS...")
        set_crs_action.triggered.connect(lambda: LayerContextMenu.set_layer_crs(layer, iface))
        
        menu.addSeparator()
        
        # Remove layer
        remove_action = menu.addAction(QIcon(":/images/themes/default/mActionRemoveLayer.svg"), "Remove Layer")
        remove_action.triggered.connect(lambda: LayerContextMenu.remove_layer(layer))
        
        menu.addSeparator()
        
        # Copy layer info
        copy_info_action = menu.addAction(QIcon(":/images/themes/default/mActionEditCopy.svg"), "Copy Layer Info")
        copy_info_action.triggered.connect(lambda: LayerContextMenu.copy_layer_info(layer))
        
        return menu
    
    @staticmethod
    def create_header_menu(tree_widget):
        """
        Create context menu for column header visibility control.
        
        Args:
            tree_widget: QTreeWidget instance
        
        Returns:
            QMenu: The created menu
        """
        menu = QMenu()
        header = tree_widget.header()
        
        # Column names
        column_names = ["Layer Name", "Type", "Features/Size", "CRS", "File Type", "File Size", "Source"]
        
        for col in range(len(column_names)):
            action = menu.addAction(column_names[col])
            action.setCheckable(True)
            action.setChecked(not header.isSectionHidden(col))
            
            # Use actual checkbox icon instead of checkmark
            if not header.isSectionHidden(col):
                action.setIcon(QIcon(":/images/themes/default/mIconSelected.svg"))
            
            # Don't allow hiding the first column (Layer Name)
            if col == 0:
                action.setEnabled(False)
            else:
                # Connect to toggle column visibility
                action.triggered.connect(lambda checked, column=col, h=header: h.setSectionHidden(column, not checked))
        
        return menu
    
    @staticmethod
    def zoom_to_layer(layer, iface):
        """
        Zoom map canvas to layer extent with CRS transformation.
        
        Args:
            layer: QgsMapLayer to zoom to
            iface: QgisInterface instance
        """
        try:
            extent = layer.extent()
            layer_crs = layer.crs()
            canvas_crs = iface.mapCanvas().mapSettings().destinationCrs()
            
            # Transform extent to canvas CRS if needed
            if layer_crs != canvas_crs:
                transform = QgsCoordinateTransform(layer_crs, canvas_crs, QgsProject.instance())
                extent = transform.transformBoundingBox(extent)
            
            # Add a small buffer (5%) to the extent
            extent.scale(1.05)
            
            iface.mapCanvas().setExtent(extent)
            iface.mapCanvas().refresh()
        except Exception as e:
            print(f"Error zooming to layer: {e}")
    
    @staticmethod
    def copy_layer_info(layer):
        """
        Copy layer information to clipboard.
        
        Args:
            layer: QgsMapLayer to get info from
        """
        try:
            info = LayerService.get_detailed_layer_info(layer)
            QApplication.clipboard().setText(info)
        except Exception as e:
            print(f"Error copying layer info: {e}")
    
    @staticmethod
    def duplicate_layer(layer):
        """
        Duplicate a layer in the project.
        
        Args:
            layer: QgsMapLayer to duplicate
        """
        try:
            project = QgsProject.instance()
            
            # Clone the layer
            if isinstance(layer, QgsVectorLayer):
                duplicated = layer.clone()
            elif isinstance(layer, QgsRasterLayer):
                duplicated = layer.clone()
            else:
                duplicated = layer.clone()
            
            # Set new name
            duplicated.setName(f"{layer.name()} copy")
            
            # Add to project
            project.addMapLayer(duplicated)
        except Exception as e:
            print(f"Error duplicating layer: {e}")
    
    @staticmethod
    def rename_layer(layer, iface):
        """
        Rename a layer with input dialog.
        
        Args:
            layer: QgsMapLayer to rename
            iface: QgisInterface instance
        """
        try:
            current_name = layer.name()
            
            # Show input dialog
            new_name, ok = QInputDialog.getText(
                iface.mainWindow(),
                "Rename Layer",
                "Enter new layer name:",
                text=current_name
            )
            
            if ok and new_name and new_name != current_name:
                layer.setName(new_name)
        except Exception as e:
            print(f"Error renaming layer: {e}")
    
    @staticmethod
    def set_layer_crs(layer, iface):
        """
        Set layer CRS with projection selector dialog.
        
        Args:
            layer: QgsMapLayer to set CRS for
            iface: QgisInterface instance
        """
        try:
            # Get current CRS
            current_crs = layer.crs()
            
            # Show CRS selection dialog
            crs_dialog = QgsProjectionSelectionDialog(iface.mainWindow())
            crs_dialog.setCrs(current_crs)
            crs_dialog.setWindowTitle("Select Layer CRS")
            
            if crs_dialog.exec_():
                new_crs = crs_dialog.crs()
                if new_crs.isValid() and new_crs != current_crs:
                    layer.setCrs(new_crs)
                    # Refresh the layer
                    layer.triggerRepaint()
        except Exception as e:
            print(f"Error setting layer CRS: {e}")
    
    @staticmethod
    def change_data_source(layer, iface, debug_callback=None):
        """
        Open data source selection dialog for a layer.
        
        Args:
            layer: QgsMapLayer to change data source for
            iface: QgisInterface instance
            debug_callback: Optional callback for debug logging
        """
        def log(msg):
            """Helper to log to debug callback or print."""
            if debug_callback:
                debug_callback(msg)
            else:
                print(msg)
        
        try:
            from qgis.gui import QgsDataSourceSelectDialog
            from qgis.core import Qgis, QgsVectorLayer, QgsRasterLayer
            
            log(f"DEBUG: change_data_source called for layer: {layer.name()}")
            log(f"DEBUG: Layer provider: {layer.providerType()}")
            log(f"DEBUG: Layer source: {layer.source()}")
            
            # Determine layer type for filtering
            if isinstance(layer, QgsVectorLayer):
                layer_type = Qgis.LayerType.Vector
                log(f"DEBUG: Layer is Vector")
            elif isinstance(layer, QgsRasterLayer):
                layer_type = Qgis.LayerType.Raster
                log(f"DEBUG: Layer is Raster")
            else:
                layer_type = Qgis.LayerType.Vector  # Default
                log(f"DEBUG: Layer type unknown, defaulting to Vector")
            
            # Create the data source selection dialog
            # This is the same dialog QGIS uses internally
            dialog = QgsDataSourceSelectDialog(
                None,  # browser model (None = create default)
                True,  # setFilterByLayerType
                layer_type,  # layer type to filter by
                iface.mainWindow()
            )
            
            dialog.setWindowTitle(f"Change Data Source - {layer.name()}")
            dialog.setDescription(f"Current source: {layer.source()}")
            
            log(f"DEBUG: Created QgsDataSourceSelectDialog")
            
            # Try to expand to the current file's directory
            current_source = layer.source()
            if '|' in current_source:
                current_source = current_source.split('|')[0]
            
            import os
            if os.path.isfile(current_source):
                dir_path = os.path.dirname(current_source)
                log(f"DEBUG: Expanding to directory: {dir_path}")
                dialog.expandPath(dir_path)
            
            # Show the dialog
            if dialog.exec_():
                uri = dialog.uri()
                log(f"DEBUG: Dialog accepted")
                log(f"DEBUG: Selected URI: {uri.uri if uri else 'None'}")
                log(f"DEBUG: Selected name: {uri.name if uri else 'None'}")
                log(f"DEBUG: Selected provider: {uri.providerKey if uri else 'None'}")
                
                if uri and uri.uri:
                    new_source = uri.uri
                    
                    if new_source != layer.source():
                        # Update the layer's data source
                        log(f"DEBUG: Updating data source to: {new_source}")
                        layer.setDataSource(new_source, layer.name(), layer.providerType())
                        layer.reload()
                        layer.triggerRepaint()
                        
                        # Emit dataChanged signal to refresh UI
                        from qgis.core import QgsProject
                        QgsProject.instance().layerTreeRoot().layerOrderChanged.emit()
                        
                        # Refresh the canvas
                        iface.mapCanvas().refresh()
                        
                        log(f"DEBUG: Data source updated successfully")
                        log(f"DEBUG: New layer source: {layer.source()}")
                    else:
                        log(f"DEBUG: Source unchanged")
                else:
                    log(f"DEBUG: No valid URI selected")
            else:
                log(f"DEBUG: Dialog cancelled")
                
        except Exception as e:
            log(f"ERROR in change_data_source: {e}")
            import traceback
            log(traceback.format_exc())
    
    @staticmethod
    def _change_data_source_fallback(layer, iface, debug_callback=None):
        """
        Fallback file dialog for changing data source.
        
        Args:
            layer: QgsMapLayer to change data source for
            iface: QgisInterface instance
            debug_callback: Optional callback for debug logging
        """
        def log(msg):
            """Helper to log to debug callback or print."""
            if debug_callback:
                debug_callback(msg)
            else:
                print(msg)
        
        from qgis.PyQt.QtWidgets import QFileDialog
        import os
        
        log(f"DEBUG: _change_data_source_fallback called for layer: {layer.name()}")
        
        # Get the directory of the current layer's source
        current_source = layer.source()
        log(f"DEBUG: Current source: {current_source}")
        
        start_dir = ""
        
        # Try to extract directory from current source
        if current_source:
            # Handle different source formats (file paths, URIs, etc.)
            if '|' in current_source:
                # Has layer subset specification (e.g., "file.gpkg|layername=layer1")
                current_source = current_source.split('|')[0]
            
            if os.path.isfile(current_source):
                start_dir = os.path.dirname(current_source)
                log(f"DEBUG: Starting in directory: {start_dir}")
            elif os.path.isdir(current_source):
                start_dir = current_source
                log(f"DEBUG: Starting in directory (is dir): {start_dir}")
        
        # Determine file filter based on layer type
        if isinstance(layer, QgsVectorLayer):
            file_filter = "All Vector Files (*.shp *.gpkg *.geojson *.kml *.gml);;Shapefiles (*.shp);;GeoPackage (*.gpkg);;GeoJSON (*.geojson);;All Files (*.*)"
        elif isinstance(layer, QgsRasterLayer):
            file_filter = "All Raster Files (*.tif *.tiff *.img *.asc *.grd);;GeoTIFF (*.tif *.tiff);;All Files (*.*)"
        else:
            file_filter = "All Files (*.*)"
        
        log(f"DEBUG: Using filter: {file_filter}")
        
        # Open file dialog starting in the current file's directory
        new_source, _ = QFileDialog.getOpenFileName(
            iface.mainWindow(),
            "Change Data Source",
            start_dir,  # Start in the current file's directory
            file_filter
        )
        
        if new_source:
            log(f"DEBUG: User selected: {new_source}")
            try:
                # Update the layer's data source
                provider_name = layer.providerType()
                layer.setDataSource(new_source, layer.name(), provider_name)
                layer.reload()
                layer.triggerRepaint()
                log(f"DEBUG: Data source updated successfully")
            except Exception as e:
                log(f"ERROR updating data source: {e}")
                import traceback
                log(traceback.format_exc())
        else:
            log(f"DEBUG: User cancelled file selection")
    
    @staticmethod
    def remove_layer(layer):
        """
        Remove a layer from the project.
        
        Args:
            layer: QgsMapLayer to remove
        """
        try:
            project = QgsProject.instance()
            project.removeMapLayer(layer.id())
        except Exception as e:
            print(f"Error removing layer: {e}")
    
    @staticmethod
    def open_layer_styling_panel(layer, iface):
        """
        Open the QGIS Layer Styling Panel for a layer.
        
        Args:
            layer: QgsMapLayer to style
            iface: QgisInterface instance
        """
        try:
            # Get the layer styling dock widget
            styling_dock = iface.mainWindow().findChild(QObject, "LayerStyling")
            
            if styling_dock:
                # If it exists, make sure it's visible
                if not styling_dock.isVisible():
                    styling_dock.setVisible(True)
            else:
                # If it doesn't exist, create it using the action
                # Find and trigger the Layer Styling Panel action
                actions = iface.mainWindow().findChildren(QObject)
                for action in actions:
                    if hasattr(action, 'objectName') and action.objectName() == "mActionStyleDock":
                        if hasattr(action, 'trigger'):
                            action.trigger()
                        break
            
            # Set the current layer in the styling panel
            iface.setActiveLayer(layer)
            
        except Exception as e:
            print(f"Error opening layer styling panel: {e}")
    
    @staticmethod
    def create_multi_layer_menu(layers, iface):
        """
        Create context menu for multiple selected layers.
        
        Args:
            layers: List of QgsMapLayer objects
            iface: QgisInterface instance
        
        Returns:
            QMenu: The created menu
        """
        from ..services.layer_operations_service import LayerOperationsService
        
        menu = QMenu()
        
        # Add to Group submenu
        add_to_group_menu = menu.addMenu(QIcon(":/images/themes/default/mActionAddGroup.svg"), "Add to Group")
        
        # Get all existing groups
        groups = LayerOperationsService.get_all_groups()
        
        if groups:
            for group_name in sorted(groups):
                group_action = add_to_group_menu.addAction(group_name)
                layer_ids = [layer.id() for layer in layers]
                group_action.triggered.connect(
                    lambda checked, gname=group_name, lids=layer_ids: 
                    LayerOperationsService.move_layers_to_group(lids, gname)
                )
        
        # Add separator and "New Group" option
        add_to_group_menu.addSeparator()
        new_group_action = add_to_group_menu.addAction(QIcon(":/images/themes/default/mActionNewFolder.svg"), "New Group...")
        new_group_action.triggered.connect(
            lambda: LayerContextMenu._create_new_group_and_move_layers(layers, iface)
        )
        
        menu.addSeparator()
        
        # Remove layers
        remove_action = menu.addAction(
            QIcon(":/images/themes/default/mActionRemoveLayer.svg"), 
            f"Remove {len(layers)} Layers"
        )
        remove_action.triggered.connect(
            lambda: LayerContextMenu._remove_multiple_layers(layers)
        )
        
        return menu
    
    @staticmethod
    def _create_new_group_and_move_layers(layers, iface):
        """
        Create a new group and move layers to it.
        
        Args:
            layers: List of QgsMapLayer objects to move
            iface: QgisInterface instance
        """
        from ..services.layer_operations_service import LayerOperationsService
        
        try:
            # Prompt for group name
            group_name, ok = QInputDialog.getText(
                iface.mainWindow(),
                "New Group",
                "Enter group name:"
            )
            
            if ok and group_name:
                # Create the group
                project = QgsProject.instance()
                root = project.layerTreeRoot()
                new_group = root.addGroup(group_name)
                
                # Move layers to the new group
                layer_ids = [layer.id() for layer in layers]
                LayerOperationsService.move_layers_to_group(layer_ids, group_name)
        
        except Exception as e:
            print(f"Error creating new group: {e}")
    
    @staticmethod
    def _remove_multiple_layers(layers):
        """
        Remove multiple layers from the project.
        
        Args:
            layers: List of QgsMapLayer objects to remove
        """
        try:
            project = QgsProject.instance()
            for layer in layers:
                project.removeMapLayer(layer.id())
        except Exception as e:
            print(f"Error removing layers: {e}")



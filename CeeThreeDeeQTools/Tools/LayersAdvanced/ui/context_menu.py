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
    def create_layer_menu(layer, iface, rename_callback=None):
        """
        Create context menu for a layer with all standard actions.
        
        Args:
            layer: QgsMapLayer object
            iface: QgisInterface instance
            rename_callback: Optional callback for rename action
        
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



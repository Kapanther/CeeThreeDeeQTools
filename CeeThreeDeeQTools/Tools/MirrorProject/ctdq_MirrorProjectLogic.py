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

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsMapLayer,
    QgsLayerTreeLayer,
    QgsReadWriteContext,
    QgsLayerTree,
    QgsLayerTreeGroup
)
from qgis.PyQt.QtXml import QDomDocument
import os


class MirrorProjectLogic:
    """
    Logic for mirroring layers from master project to child projects.
    """
    
    @staticmethod
    def export_layers_to_projects(
        layer_ids: list,
        target_projects: list,
        skip_same_name: bool = True,
        replace_data_source: bool = False,
        update_symbology: bool = True,
        fix_layer_order: bool = True,
        progress_callback=None
    ):
        """
        Export selected layers to target projects.
        
        Args:
            layer_ids: List of layer IDs to export
            target_projects: List of target project file paths
            skip_same_name: Skip layers that already exist with same name
            replace_data_source: Replace data source for existing layers
            update_symbology: Update symbology from master project
            fix_layer_order: Fix layer order to match master project
            progress_callback: Optional callback function(message, progress) for progress updates
        
        Returns:
            dict: Results with success/error information
        """
        results = {
            'success': True,
            'projects_updated': 0,
            'layers_exported': 0,
            'errors': [],
            'warnings': []
        }
        
        # Get master project
        master_project = QgsProject.instance()
        
        # Get layer objects from IDs and build order map
        layers_to_export = []
        layer_order_map = {}  # Map of layer name to order index
        
        # Get the master project layer order from the layer tree
        master_layer_order = MirrorProjectLogic._get_layer_order_from_tree(master_project)
        
        for layer_id in layer_ids:
            layer = master_project.mapLayer(layer_id)
            if layer and layer.isValid():
                layers_to_export.append(layer)
                # Store the order index from master project
                if layer.name() in master_layer_order:
                    layer_order_map[layer.name()] = master_layer_order[layer.name()]
            else:
                results['warnings'].append(f"Layer with ID {layer_id} not found or invalid")
        
        if not layers_to_export:
            results['success'] = False
            results['errors'].append("No valid layers to export")
            return results
        
        total_steps = len(target_projects) * len(layers_to_export)
        current_step = 0
        
        # Process each target project
        for project_path in target_projects:
            try:
                if progress_callback:
                    progress_callback(f"Processing project: {os.path.basename(project_path)}", 
                                    int((current_step / total_steps) * 100))
                
                # Load the target project
                target_project = QgsProject()
                if not target_project.read(project_path):
                    results['errors'].append(f"Failed to read project: {project_path}")
                    continue
                
                project_modified = False
                layers_to_reorder = []  # Track layers that need reordering
                
                # Export each layer
                for layer in layers_to_export:
                    current_step += 1
                    
                    try:
                        if progress_callback:
                            progress_callback(
                                f"Exporting layer '{layer.name()}' to {os.path.basename(project_path)}", 
                                int((current_step / total_steps) * 100)
                            )
                        
                        # Check if layer with same name already exists
                        existing_layer = MirrorProjectLogic._find_layer_by_name(
                            target_project, layer.name()
                        )
                        
                        if existing_layer:
                            if skip_same_name:
                                results['warnings'].append(
                                    f"Skipped '{layer.name()}' in {os.path.basename(project_path)} (already exists)"
                                )
                                # Still track for reordering if needed
                                if fix_layer_order and layer.name() in layer_order_map:
                                    layers_to_reorder.append((layer.name(), layer_order_map[layer.name()]))
                                continue
                            elif replace_data_source:
                                # Replace data source of existing layer
                                if MirrorProjectLogic._replace_layer_data_source(
                                    existing_layer, layer, update_symbology
                                ):
                                    results['layers_exported'] += 1
                                    project_modified = True
                                    # Track for reordering
                                    if fix_layer_order and layer.name() in layer_order_map:
                                        layers_to_reorder.append((layer.name(), layer_order_map[layer.name()]))
                                else:
                                    results['warnings'].append(
                                        f"Failed to replace data source for '{layer.name()}' in {os.path.basename(project_path)}"
                                    )
                                continue
                            else:
                                # Remove existing layer and add new one
                                target_project.removeMapLayer(existing_layer.id())
                        
                        # Clone and add the layer
                        if MirrorProjectLogic._clone_layer_to_project(
                            layer, target_project, update_symbology
                        ):
                            results['layers_exported'] += 1
                            project_modified = True
                            # Track for reordering
                            if fix_layer_order and layer.name() in layer_order_map:
                                layers_to_reorder.append((layer.name(), layer_order_map[layer.name()]))
                        else:
                            results['warnings'].append(
                                f"Failed to export '{layer.name()}' to {os.path.basename(project_path)}"
                            )
                    
                    except Exception as layer_error:
                        results['errors'].append(
                            f"Error exporting layer '{layer.name()}' to {os.path.basename(project_path)}: {str(layer_error)}"
                        )
                
                # Fix layer order if requested and layers were added/modified
                if fix_layer_order and layers_to_reorder:
                    if MirrorProjectLogic._fix_layer_order(target_project, layers_to_reorder, master_layer_order):
                        project_modified = True
                        results['warnings'].append(f"Fixed layer order in {os.path.basename(project_path)}")
                
                # Save the target project if it was modified
                if project_modified:
                    if target_project.write(project_path):
                        results['projects_updated'] += 1
                    else:
                        results['errors'].append(f"Failed to save project: {project_path}")
                
            except Exception as project_error:
                results['errors'].append(f"Error processing project {project_path}: {str(project_error)}")
        
        if results['errors']:
            results['success'] = False
        
        return results
    
    @staticmethod
    def _find_layer_by_name(project: QgsProject, layer_name: str):
        """Find a layer in the project by name."""
        for layer_id, layer in project.mapLayers().items():
            if layer.name() == layer_name:
                return layer
        return None
    
    @staticmethod
    def _clone_layer_to_project(
        source_layer: QgsMapLayer,
        target_project: QgsProject,
        copy_symbology: bool = True
    ) -> bool:
        """
        Clone a layer and add it to the target project.
        
        Args:
            source_layer: The layer to clone
            target_project: The project to add the layer to
            copy_symbology: Whether to copy symbology
        
        Returns:
            bool: True if successful
        """
        try:
            # Create XML document to serialize layer
            doc = QDomDocument("layer")
            context = QgsReadWriteContext()
            
            # Write layer to XML
            layer_elem = doc.createElement("maplayer")
            doc.appendChild(layer_elem)
            
            if not source_layer.writeLayerXml(layer_elem, doc, context):
                return False
            
            # Create new layer from XML
            if source_layer.type() == QgsMapLayer.VectorLayer:
                cloned_layer = QgsVectorLayer()
            elif source_layer.type() == QgsMapLayer.RasterLayer:
                cloned_layer = QgsRasterLayer()
            else:
                return False
            
            # Read layer from XML
            if not cloned_layer.readLayerXml(layer_elem, context):
                return False
            
            # Set layer name
            cloned_layer.setName(source_layer.name())
            
            # Copy symbology if requested
            if copy_symbology:
                if source_layer.type() == QgsMapLayer.VectorLayer:
                    # Copy renderer
                    if source_layer.renderer():
                        cloned_layer.setRenderer(source_layer.renderer().clone())
                    
                    # Copy labeling
                    if source_layer.labeling():
                        cloned_layer.setLabeling(source_layer.labeling().clone())
                        cloned_layer.setLabelsEnabled(source_layer.labelsEnabled())
                elif source_layer.type() == QgsMapLayer.RasterLayer:
                    # Copy renderer for raster
                    if source_layer.renderer():
                        cloned_layer.setRenderer(source_layer.renderer().clone())
            
            # Add layer to target project
            if not target_project.addMapLayer(cloned_layer, False):
                return False
            
            # Add to layer tree at the root
            root = target_project.layerTreeRoot()
            root.addLayer(cloned_layer)
            
            return True
        
        except Exception as e:
            print(f"Error cloning layer: {e}")
            return False
    
    @staticmethod
    def _replace_layer_data_source(
        existing_layer: QgsMapLayer,
        source_layer: QgsMapLayer,
        update_symbology: bool = False
    ) -> bool:
        """
        Replace the data source of an existing layer.
        
        Args:
            existing_layer: The layer to update
            source_layer: The source layer with new data source
            update_symbology: Whether to also update symbology
        
        Returns:
            bool: True if successful
        """
        try:
            # Get the data source from the source layer
            new_source = source_layer.source()
            new_provider = source_layer.providerType()
            
            # Set the new data source
            existing_layer.setDataSource(new_source, existing_layer.name(), new_provider)
            
            # Update symbology if requested
            if update_symbology:
                if source_layer.type() == QgsMapLayer.VectorLayer:
                    # Copy renderer
                    if source_layer.renderer():
                        existing_layer.setRenderer(source_layer.renderer().clone())
                    
                    # Copy labeling
                    if source_layer.labeling():
                        existing_layer.setLabeling(source_layer.labeling().clone())
                        existing_layer.setLabelsEnabled(source_layer.labelsEnabled())
                elif source_layer.type() == QgsMapLayer.RasterLayer:
                    # Copy renderer for raster
                    if source_layer.renderer():
                        existing_layer.setRenderer(source_layer.renderer().clone())
            
            return True
        
        except Exception as e:
            print(f"Error replacing data source: {e}")
            return False
    
    @staticmethod
    def _get_layer_order_from_tree(project: QgsProject) -> dict:
        """
        Get the layer order from the project's layer tree.
        
        Args:
            project: The project to get layer order from
        
        Returns:
            dict: Map of layer name to order index (0 = top, higher = lower)
        """
        layer_order = {}
        root = project.layerTreeRoot()
        
        def traverse_tree(node, order_list):
            """Recursively traverse the layer tree to build order."""
            if isinstance(node, QgsLayerTreeLayer):
                layer = node.layer()
                if layer:
                    order_list.append(layer.name())
            elif isinstance(node, QgsLayerTreeGroup):
                for child in node.children():
                    traverse_tree(child, order_list)
        
        order_list = []
        traverse_tree(root, order_list)
        
        # Build index map (reverse so 0 is at the top)
        for idx, layer_name in enumerate(order_list):
            layer_order[layer_name] = idx
        
        return layer_order
    
    @staticmethod
    def _fix_layer_order(
        target_project: QgsProject,
        layers_to_order: list,
        master_layer_order: dict
    ) -> bool:
        """
        Fix the layer order in the target project to match the master project.
        
        Args:
            target_project: The project to fix layer order in
            layers_to_order: List of (layer_name, order_index) tuples
            master_layer_order: Complete layer order map from master project
        
        Returns:
            bool: True if successful
        """
        try:
            root = target_project.layerTreeRoot()
            
            # Sort layers by their order in the master project
            layers_to_order.sort(key=lambda x: x[1])
            
            # Move each layer to its correct position
            for layer_name, desired_order in layers_to_order:
                # Find the layer in the target project
                layer = MirrorProjectLogic._find_layer_by_name(target_project, layer_name)
                if not layer:
                    continue
                
                # Find the layer tree node
                layer_tree_layer = root.findLayer(layer.id())
                if not layer_tree_layer:
                    continue
                
                # Calculate insertion index based on other layers
                # We need to find where this layer should be inserted
                parent = layer_tree_layer.parent()
                if not parent:
                    parent = root
                
                # Remove the layer from its current position
                parent.removeChildNode(layer_tree_layer)
                
                # Find the correct insertion index
                insertion_index = 0
                for i, child in enumerate(parent.children()):
                    if isinstance(child, QgsLayerTreeLayer):
                        child_layer = child.layer()
                        if child_layer and child_layer.name() in master_layer_order:
                            child_order = master_layer_order[child_layer.name()]
                            if child_order < desired_order:
                                insertion_index = i + 1
                            else:
                                break
                
                # Insert at the calculated position
                parent.insertChildNode(insertion_index, layer_tree_layer)
            
            return True
        
        except Exception as e:
            print(f"Error fixing layer order: {e}")
            return False

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
import shutil
from datetime import datetime


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
        progress_callback=None,
        create_backups: bool = True,
        add_layer_groups: bool = True,
        selected_themes: list = None,
        selected_layouts: list = None,
        preserve_layer_filters: bool = True
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
            create_backups: Create backup of target project files before modification
            add_layer_groups: Add layer groups from master project to target projects
            selected_themes: List of theme names to export
            selected_layouts: List of layout names to export
            preserve_layer_filters: Preserve existing layer filters in child projects
        
        Returns:
            dict: Results with success/error information
        """
        results = {
            'success': True,
            'projects_updated': 0,
            'layers_exported': 0,
            'themes_exported': 0,
            'layouts_exported': 0,
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
                # Create backup of the project file if requested
                if create_backups and os.path.exists(project_path):
                    try:
                        backup_dir = os.path.join(os.path.dirname(project_path), "MirrorProjectBackup")
                        if not os.path.exists(backup_dir):
                            os.makedirs(backup_dir, exist_ok=True)
                        base = os.path.basename(project_path)
                        name, ext = os.path.splitext(base)
                        stamp = datetime.now().strftime("_@%Y-%m-%d_%H-%M-%S")
                        backup_name = f"{name}{stamp}{ext}"
                        backup_path = os.path.join(backup_dir, backup_name)
                        shutil.copy2(project_path, backup_path)
                        results['warnings'].append(f"Backup created: {os.path.relpath(backup_path)}")
                    except Exception as backup_err:
                        results['warnings'].append(f"Failed to create backup for {project_path}: {str(backup_err)}")

                if progress_callback:
                    progress_callback(f"Processing project: {os.path.basename(project_path)}", 
                                    int((current_step / total_steps) * 100))
                
                # Load the target project
                target_project = QgsProject()
                if not target_project.read(project_path):
                    results['errors'].append(f"Failed to read project: {project_path}")
                    continue
                
                project_modified = False
                
                # Export each layer
                for layer in layers_to_export:
                    current_step += 1
                    
                    try:
                        if progress_callback:
                            progress_callback(
                                f"Exporting layer '{layer.name()}' to {os.path.basename(project_path)}", 
                                int((current_step / total_steps) * 100)
                            )
                        
                        # FIRST: Check if layer exists and preserve filter BEFORE any operations
                        existing_filter = None
                        existing_layer = MirrorProjectLogic._find_layer_by_name(
                            target_project, layer.name()
                        )
                        
                        if existing_layer and preserve_layer_filters:
                            try:
                                if hasattr(existing_layer, 'subsetString'):
                                    existing_filter = existing_layer.subsetString()
                                    if existing_filter:
                                        results['warnings'].append(
                                            f"Captured existing filter for '{layer.name()}': {existing_filter}"
                                        )
                                    else:
                                        results['warnings'].append(
                                            f"Layer '{layer.name()}' exists but has no filter"
                                        )
                            except Exception as e:
                                results['warnings'].append(
                                    f"Could not read filter from '{layer.name()}': {str(e)}"
                                )
                        
                        # Now handle the layer based on options
                        if existing_layer:
                            if skip_same_name:
                                results['warnings'].append(
                                    f"Skipped '{layer.name()}' in {os.path.basename(project_path)} (already exists)"
                                )
                                continue
                            elif replace_data_source:
                                # Replace data source of existing layer
                                if MirrorProjectLogic._replace_layer_data_source(
                                    existing_layer, layer, update_symbology, existing_filter, preserve_layer_filters, results
                                ):
                                    results['layers_exported'] += 1
                                    project_modified = True
                                else:
                                    results['warnings'].append(
                                        f"Failed to replace data source for '{layer.name()}' in {os.path.basename(project_path)}"
                                    )
                                continue
                            else:
                                # Remove existing layer and add new one
                                target_project.removeMapLayer(existing_layer.id())
                                results['warnings'].append(
                                    f"Removed existing layer '{layer.name()}' to replace with new one"
                                )
                        
                        # Clone and add the layer (with preserved filter if applicable)
                        if MirrorProjectLogic._clone_layer_to_project(
                            layer, target_project, update_symbology, results, existing_filter, preserve_layer_filters
                        ):
                            results['layers_exported'] += 1
                            project_modified = True
                        else:
                            # Error details already added by _clone_layer_to_project
                            pass
                    
                    except Exception as layer_error:
                        results['errors'].append(
                            f"Error exporting layer '{layer.name()}' to {os.path.basename(project_path)}: {str(layer_error)}"
                        )
                
                # Fix layer order if requested (run after all layers are imported)
                if fix_layer_order and project_modified:
                    if progress_callback:
                        progress_callback(f"Fixing layer order in {os.path.basename(project_path)}", 
                                        int((current_step / total_steps) * 100))
                    if MirrorProjectLogic._fix_layer_order(target_project, master_layer_order, results, add_layer_groups, master_project):
                        project_modified = True
                        results['warnings'].append(f"Reordered layers in {os.path.basename(project_path)} to match master project")
                    else:
                        results['warnings'].append(f"Could not fix layer order in {os.path.basename(project_path)}")
                
                # Export map themes if requested
                if selected_themes:
                    if progress_callback:
                        progress_callback(f"Exporting map themes to {os.path.basename(project_path)}", 
                                        int((current_step / total_steps) * 100))
                    themes_exported = MirrorProjectLogic._export_map_themes(
                        master_project, 
                        target_project, 
                        selected_themes, 
                        results
                    )
                    if themes_exported > 0:
                        project_modified = True
                        results['themes_exported'] += themes_exported
                
                # Export print layouts if requested (done LAST after layers and themes)
                if selected_layouts:
                    if progress_callback:
                        progress_callback(f"Exporting print layouts to {os.path.basename(project_path)}", 
                                        int((current_step / total_steps) * 100))
                    layouts_exported = MirrorProjectLogic._export_print_layouts(
                        master_project, 
                        target_project, 
                        selected_layouts, 
                        results
                    )
                    if layouts_exported > 0:
                        project_modified = True
                        results['layouts_exported'] += layouts_exported
                
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
        copy_symbology: bool = True,
        results: dict = None,
        existing_filter: str = None,
        preserve_layer_filters: bool = True
    ) -> bool:
        """
        Clone a layer and add it to the target project.
        
        Args:
            source_layer: The layer to clone
            target_project: The project to add the layer to
            copy_symbology: Whether to copy symbology
            results: Optional results dict to append error messages to
            existing_filter: Previously captured filter to restore
            preserve_layer_filters: Whether to preserve the filter
        
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
                error_msg = f"Failed to export '{source_layer.name()}': Could not serialize layer to XML"
                if results:
                    results['errors'].append(error_msg)
                print(error_msg)
                return False
            
            # Create new layer from XML
            if source_layer.type() == QgsMapLayer.VectorLayer:
                cloned_layer = QgsVectorLayer()
            elif source_layer.type() == QgsMapLayer.RasterLayer:
                cloned_layer = QgsRasterLayer()
            else:
                error_msg = f"Failed to export '{source_layer.name()}': Unsupported layer type ({source_layer.type()})"
                if results:
                    results['errors'].append(error_msg)
                print(error_msg)
                return False
            
            # Read layer from XML
            if not cloned_layer.readLayerXml(layer_elem, context):
                error_msg = f"Failed to export '{source_layer.name()}': Could not deserialize layer from XML"
                if results:
                    results['errors'].append(error_msg)
                print(error_msg)
                return False
            
            # Set layer name
            cloned_layer.setName(source_layer.name())
            
            # Copy symbology if requested
            if copy_symbology:
                if source_layer.type() == QgsMapLayer.VectorLayer:
                    # Copy renderer
                    if source_layer.renderer():
                        try:
                            cloned_layer.setRenderer(source_layer.renderer().clone())
                        except Exception as e:
                            error_msg = f"Warning for '{source_layer.name()}': Could not copy renderer - {str(e)}"
                            if results:
                                results['warnings'].append(error_msg)
                            print(error_msg)
                    
                    # Copy labeling
                    if source_layer.labeling():
                        try:
                            cloned_layer.setLabeling(source_layer.labeling().clone())
                            cloned_layer.setLabelsEnabled(source_layer.labelsEnabled())
                        except Exception as e:
                            error_msg = f"Warning for '{source_layer.name()}': Could not copy labeling - {str(e)}"
                            if results:
                                results['warnings'].append(error_msg)
                            print(error_msg)
                elif source_layer.type() == QgsMapLayer.RasterLayer:
                    # Copy renderer for raster
                    if source_layer.renderer():
                        try:
                            cloned_layer.setRenderer(source_layer.renderer().clone())
                        except Exception as e:
                            error_msg = f"Warning for '{source_layer.name()}': Could not copy raster renderer - {str(e)}"
                            if results:
                                results['warnings'].append(error_msg)
                            print(error_msg)
            
            # Add layer to target project
            if not target_project.addMapLayer(cloned_layer, False):
                error_msg = f"Failed to export '{source_layer.name()}': Could not add layer to target project"
                if results:
                    results['errors'].append(error_msg)
                print(error_msg)
                return False
            
            # Add to layer tree at the root
            root = target_project.layerTreeRoot()
            try:
                root.addLayer(cloned_layer)
            except Exception as e:
                error_msg = f"Warning for '{source_layer.name()}': Could not add to layer tree - {str(e)}"
                if results:
                    results['warnings'].append(error_msg)
                print(error_msg)
                # Not a fatal error if layer is already in project
            
            # Apply the preserved filter AFTER the layer is fully added
            if existing_filter and preserve_layer_filters:
                try:
                    if hasattr(cloned_layer, 'setSubsetString'):
                        success = cloned_layer.setSubsetString(existing_filter)
                        if success:
                            if results:
                                results['warnings'].append(
                                    f"✓ Restored filter for '{source_layer.name()}': {existing_filter}"
                                )
                        else:
                            if results:
                                results['warnings'].append(
                                    f"✗ Failed to restore filter for '{source_layer.name()}': setSubsetString returned False"
                                )
                    else:
                        if results:
                            results['warnings'].append(
                                f"Layer '{source_layer.name()}' does not support filters (not a vector layer)"
                            )
                except Exception as e:
                    error_msg = f"✗ Exception restoring filter for '{source_layer.name()}': {str(e)}"
                    if results:
                        results['warnings'].append(error_msg)
                    print(error_msg)
            elif preserve_layer_filters and not existing_filter:
                if results:
                    results['warnings'].append(
                        f"No filter to preserve for '{source_layer.name()}'"
                    )
            
            return True
        
        except Exception as e:
            error_msg = f"Failed to export '{source_layer.name()}': Unexpected error - {str(e)}"
            if results:
                results['errors'].append(error_msg)
            print(error_msg)
            return False

    @staticmethod
    def _replace_layer_data_source(
        existing_layer: QgsMapLayer,
        source_layer: QgsMapLayer,
        update_symbology: bool = False,
        existing_filter: str = None,
        preserve_layer_filters: bool = True,
        results: dict = None
    ) -> bool:
        """
        Replace the data source of an existing layer.
        
        Args:
            existing_layer: The layer to update
            source_layer: The source layer with new data source
            update_symbology: Whether to also update symbology
            existing_filter: Previously captured filter to restore
            preserve_layer_filters: Whether to preserve the filter
            results: Optional results dict for messages
        
        Returns:
            bool: True if successful
        """
        try:
            # Get the data source from the source layer
            new_source = source_layer.source()
            new_provider = source_layer.providerType()
            
            # Set the new data source
            existing_layer.setDataSource(new_source, existing_layer.name(), new_provider)
            
            # Restore the preserved filter AFTER data source update
            if existing_filter and preserve_layer_filters:
                try:
                    if hasattr(existing_layer, 'setSubsetString'):
                        success = existing_layer.setSubsetString(existing_filter)
                        if success:
                            if results:
                                results['warnings'].append(
                                    f"✓ Restored filter after data source update for '{existing_layer.name()}': {existing_filter}"
                                )
                        else:
                            if results:
                                results['warnings'].append(
                                    f"✗ Failed to restore filter for '{existing_layer.name()}': setSubsetString returned False"
                                )
                except Exception as e:
                    error_msg = f"✗ Exception restoring filter for '{existing_layer.name()}': {str(e)}"
                    if results:
                        results['warnings'].append(error_msg)
                    print(error_msg)
            
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
        master_layer_order: dict,
        results: dict = None,
        add_layer_groups: bool = True,
        master_project: QgsProject = None
    ) -> bool:
        """
        Fix the layer order in the target project to match the master project.
        Also replicates group structure if requested.
        
        Args:
            target_project: The project to fix layer order in
            master_layer_order: Complete layer order map from master project
            results: Optional results dict to append messages to
            add_layer_groups: Whether to add layer groups from master project
            master_project: The master project to copy groups from
        
        Returns:
            bool: True if successful
        """
        try:
            target_root = target_project.layerTreeRoot()
            
            # Build a map of master project layer tree structure
            if add_layer_groups and master_project:
                # Get the complete layer tree structure from master
                master_structure = MirrorProjectLogic._get_layer_tree_structure(master_project)
                
                # Replicate the group structure and move layers into correct groups
                if MirrorProjectLogic._replicate_structure_and_order(
                    master_structure, 
                    target_project, 
                    master_layer_order, 
                    results
                ):
                    if results:
                        results['warnings'].append("Replicated layer groups and order from master project")
                    return True
                else:
                    if results:
                        results['warnings'].append("Failed to fully replicate master project structure")
                    return False
            
            # Fallback: simple reordering without groups (original logic)
            # Build a list of layers in target project that exist in master order
            layers_to_order = []
            for layer_id, layer in target_project.mapLayers().items():
                if layer and layer.name() in master_layer_order:
                    layers_to_order.append((layer.name(), master_layer_order[layer.name()]))
            
            layers_to_order.sort(key=lambda x: x[1])
            
            if not layers_to_order:
                if results:
                    results['warnings'].append("No layers to reorder (no matching layer names found)")
                return True
            
            if results:
                results['warnings'].append(f"Reordering {len(layers_to_order)} layers (no groups)")
            
            # Move each layer to root in correct order
            for layer_name, desired_order in layers_to_order:
                try:
                    layer = MirrorProjectLogic._find_layer_by_name(target_project, layer_name)
                    if not layer:
                        continue
                    
                    layer_tree_layer = target_root.findLayer(layer.id())
                    if not layer_tree_layer:
                        continue
                    
                    parent = layer_tree_layer.parent()
                    if not parent:
                        parent = target_root
                    
                    current_index = parent.children().index(layer_tree_layer)
                    
                    # Calculate insertion index at root
                    insertion_index = 0
                    for i, child in enumerate(target_root.children()):
                        if isinstance(child, QgsLayerTreeLayer):
                            child_layer = child.layer()
                            if child_layer and child_layer.name() in master_layer_order:
                                child_order = master_layer_order[child_layer.name()]
                                if child_order < desired_order:
                                    insertion_index = i + 1
                                else:
                                    break
                    
                    if parent != target_root or current_index != insertion_index:
                        cloned_node = layer_tree_layer.clone()
                        parent.removeChildNode(layer_tree_layer)
                        target_root.insertChildNode(insertion_index, cloned_node)
                
                except Exception as layer_err:
                    error_msg = f"Error reordering layer '{layer_name}': {str(layer_err)}"
                    if results:
                        results['warnings'].append(error_msg)
                    print(error_msg)
            
            return True
        
        except Exception as e:
            error_msg = f"Error fixing layer order: {e}"
            if results:
                results['warnings'].append(error_msg)
            print(error_msg)
            return False

    @staticmethod
    def _get_layer_tree_structure(project: QgsProject) -> dict:
        """
        Get the complete layer tree structure from a project, including groups and layer positions.
        
        Args:
            project: The project to analyze
        
        Returns:
            dict: Tree structure with groups and layers
        """
        structure = {'type': 'root', 'children': []}
        root = project.layerTreeRoot()
        
        def traverse(node, parent_struct):
            for child in node.children():
                if isinstance(child, QgsLayerTreeGroup):
                    group_struct = {
                        'type': 'group',
                        'name': child.name(),
                        'children': []
                    }
                    parent_struct['children'].append(group_struct)
                    traverse(child, group_struct)
                elif isinstance(child, QgsLayerTreeLayer):
                    layer = child.layer()
                    if layer:
                        layer_struct = {
                            'type': 'layer',
                            'name': layer.name(),
                            'id': layer.id()
                        }
                        parent_struct['children'].append(layer_struct)
        
        traverse(root, structure)
        return structure

    @staticmethod
    def _replicate_structure_and_order(
        master_structure: dict,
        target_project: QgsProject,
        master_layer_order: dict,
        results: dict = None
    ) -> bool:
        """
        Replicate the master project's group structure and move layers into correct positions.
        Groups and layers are placed in the exact order from the master project.
        
        Args:
            master_structure: The master project's layer tree structure
            target_project: The target project to update
            master_layer_order: Layer order map from master
            results: Optional results dict for messages
        
        Returns:
            bool: True if successful
        """
        try:
            target_root = target_project.layerTreeRoot()
            
            # Recursive function to replicate structure and order
            def replicate_node(master_node, target_parent, position):
                """
                Recursively replicate the master node structure into the target parent.
                
                Args:
                    master_node: The master node to replicate
                    target_parent: The target parent node
                    position: The position index to insert at
                """
                for i, child in enumerate(master_node.get('children', [])):
                    if child['type'] == 'group':
                        group_name = child['name']
                        
                        # Find or create the group
                        target_group = target_parent.findGroup(group_name)
                        
                        if not target_group:
                            # Create new group at the correct position
                            target_group = target_parent.insertGroup(position + i, group_name)
                            if results:
                                parent_name = target_parent.name() if isinstance(target_parent, QgsLayerTreeGroup) else "root"
                                results['warnings'].append(f"Created group '{group_name}' in '{parent_name}' at position {position + i}")
                        else:
                            # Group exists - move it to correct position if needed
                            current_index = target_parent.children().index(target_group)
                            desired_index = position + i
                            
                            if current_index != desired_index:
                                # Remove and re-insert at correct position
                                cloned_group = target_group.clone()
                                target_parent.removeChildNode(target_group)
                                target_parent.insertChildNode(desired_index, cloned_group)
                                target_group = cloned_group
                                
                                if results:
                                    parent_name = target_parent.name() if isinstance(target_parent, QgsLayerTreeGroup) else "root"
                                    results['warnings'].append(f"Moved group '{group_name}' in '{parent_name}' to position {desired_index}")
                        
                        # Recursively replicate the group's children
                        replicate_node(child, target_group, 0)
                    
                    elif child['type'] == 'layer':
                        layer_name = child['name']
                        
                        # Find the layer in target project
                        layer = MirrorProjectLogic._find_layer_by_name(target_project, layer_name)
                        if not layer:
                            continue
                        
                        # Find the layer's current tree node
                        layer_tree_node = target_root.findLayer(layer.id())
                        if not layer_tree_node:
                            continue
                        
                        current_parent = layer_tree_node.parent()
                        if not current_parent:
                            current_parent = target_root
                        
                        desired_index = position + i
                        
                        # Check if layer needs to be moved
                        if current_parent != target_parent:
                            # Layer is in wrong parent - move it
                            cloned_node = layer_tree_node.clone()
                            current_parent.removeChildNode(layer_tree_node)
                            target_parent.insertChildNode(desired_index, cloned_node)
                            
                            if results:
                                parent_name = target_parent.name() if isinstance(target_parent, QgsLayerTreeGroup) else "root"
                                results['warnings'].append(f"Moved layer '{layer_name}' to '{parent_name}' at position {desired_index}")
                        else:
                            # Layer is in correct parent - check if position is correct
                            current_index = current_parent.children().index(layer_tree_node)
                            
                            if current_index != desired_index:
                                # Reorder within the same parent
                                cloned_node = layer_tree_node.clone()
                                current_parent.removeChildNode(layer_tree_node)
                                current_parent.insertChildNode(desired_index, cloned_node)
                                
                                if results:
                                    parent_name = target_parent.name() if isinstance(target_parent, QgsLayerTreeGroup) else "root"
                                    results['warnings'].append(f"Reordered layer '{layer_name}' in '{parent_name}' to position {desired_index}")
            
            # Start replication from the root
            replicate_node(master_structure, target_root, 0)
            
            return True
        
        except Exception as e:
            error_msg = f"Error replicating structure and order: {e}"
            if results:
                results['warnings'].append(error_msg)
            print(error_msg)
            return False

    @staticmethod
    def _replicate_layer_groups(
        master_project: QgsProject,
        target_project: QgsProject,
        results: dict = None
    ) -> bool:
        """
        DEPRECATED: Use _replicate_structure_and_order instead.
        This method is kept for backward compatibility but does nothing.
        """
        return True
    
    @staticmethod
    def _export_map_themes(
        master_project: QgsProject,
        target_project: QgsProject,
        selected_themes: list,
        results: dict = None
    ) -> int:
        """
        Export map themes from master project to target project.
        
        Args:
            master_project: The master project to copy themes from
            target_project: The target project to add themes to
            selected_themes: List of theme names to export
            results: Optional results dict for messages
        
        Returns:
            int: Number of themes successfully exported
        """
        themes_exported = 0
        
        try:
            master_theme_collection = master_project.mapThemeCollection()
            target_theme_collection = target_project.mapThemeCollection()
            
            for theme_name in selected_themes:
                try:
                    # Check if theme exists in master
                    if not master_theme_collection.hasMapTheme(theme_name):
                        if results:
                            results['warnings'].append(f"Theme '{theme_name}' not found in master project")
                        continue
                    
                    # Get the theme record from master
                    theme_record = master_theme_collection.mapThemeState(theme_name)
                    
                    # Check if theme already exists in target
                    if target_theme_collection.hasMapTheme(theme_name):
                        # Update existing theme
                        target_theme_collection.update(theme_name, theme_record)
                        if results:
                            results['warnings'].append(f"Updated existing theme '{theme_name}'")
                    else:
                        # Insert new theme
                        target_theme_collection.insert(theme_name, theme_record)
                        if results:
                            results['warnings'].append(f"Created new theme '{theme_name}'")
                    
                    themes_exported += 1
                
                except Exception as theme_err:
                    error_msg = f"Error exporting theme '{theme_name}': {str(theme_err)}"
                    if results:
                        results['errors'].append(error_msg)
                    print(error_msg)
            
            return themes_exported
        
        except Exception as e:
            error_msg = f"Error exporting map themes: {e}"
            if results:
                results['errors'].append(error_msg)
            print(error_msg)
            return themes_exported
    
    @staticmethod
    def _export_print_layouts(
        master_project: QgsProject,
        target_project: QgsProject,
        selected_layouts: list,
        results: dict = None
    ) -> int:
        """
        Export print layouts from master project to target project using template files.
        
        Args:
            master_project: The master project to copy layouts from
            target_project: The target project to add layouts to
            selected_layouts: List of layout names to export
            results: Optional results dict for messages
        
        Returns:
            int: Number of layouts successfully exported
        """
        layouts_exported = 0
        
        try:
            import tempfile
            import uuid
            from qgis.core import QgsReadWriteContext, QgsPrintLayout
            from qgis.PyQt.QtXml import QDomDocument
            
            master_layout_manager = master_project.layoutManager()
            target_layout_manager = target_project.layoutManager()
            
            for layout_name in selected_layouts:
                try:
                    # Check if layout exists in master
                    master_layout = master_layout_manager.layoutByName(layout_name)
                    if not master_layout:
                        if results:
                            results['warnings'].append(f"Layout '{layout_name}' not found in master project")
                        continue
                    
                    # Check if layout already exists in target
                    existing_layout = target_layout_manager.layoutByName(layout_name)
                    if existing_layout:
                        # Remove existing layout before adding new one
                        target_layout_manager.removeLayout(existing_layout)
                        if results:
                            results['warnings'].append(f"Removed existing layout '{layout_name}' before replacing")
                    
                    # Create a temporary template file
                    temp_template_path = os.path.join(
                        tempfile.gettempdir(), 
                        f"layout_template_{uuid.uuid4().hex}.qpt"
                    )
                    
                    try:
                        # Save the layout as a template
                        if not master_layout.saveAsTemplate(temp_template_path, QgsReadWriteContext()):
                            error_msg = f"Failed to save layout '{layout_name}' as template"
                            if results:
                                results['errors'].append(error_msg)
                            print(error_msg)
                            continue
                        
                        # Read the template file
                        with open(temp_template_path, 'r', encoding='utf-8') as f:
                            template_content = f.read()
                        
                        # Parse the template XML
                        doc = QDomDocument()
                        if not doc.setContent(template_content):
                            error_msg = f"Failed to parse template XML for layout '{layout_name}'"
                            if results:
                                results['errors'].append(error_msg)
                            print(error_msg)
                            continue
                        
                        # Create a new layout in the target project
                        new_layout = QgsPrintLayout(target_project)
                        new_layout.setName(layout_name)
                        new_layout.initializeDefaults()
                        
                        # Read the layout from the template XML
                        if not new_layout.loadFromTemplate(doc, QgsReadWriteContext()):
                            error_msg = f"Failed to load layout '{layout_name}' from template"
                            if results:
                                results['errors'].append(error_msg)
                            print(error_msg)
                            continue
                        
                        # Add the new layout to target project
                        if not target_layout_manager.addLayout(new_layout):
                            error_msg = f"Failed to add layout '{layout_name}' to target project"
                            if results:
                                results['errors'].append(error_msg)
                            print(error_msg)
                            continue
                        
                        if results:
                            results['warnings'].append(f"Exported layout '{layout_name}'")
                        
                        layouts_exported += 1
                    
                    finally:
                        # Clean up temporary template file
                        try:
                            if os.path.exists(temp_template_path):
                                os.remove(temp_template_path)
                        except Exception as cleanup_err:
                            print(f"Warning: Could not remove temporary template file: {cleanup_err}")
                
                except Exception as layout_err:
                    error_msg = f"Error exporting layout '{layout_name}': {str(layout_err)}"
                    if results:
                        results['errors'].append(error_msg)
                    print(error_msg)
            
            return layouts_exported
        
        except Exception as e:
            error_msg = f"Error exporting print layouts: {e}"
            if results:
                results['errors'].append(error_msg)
            print(error_msg)
            return layouts_exported

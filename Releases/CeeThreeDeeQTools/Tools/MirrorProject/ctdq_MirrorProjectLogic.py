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
        preserve_layer_filters: bool = True,
        preserve_auxiliary_tables: bool = True  # NEW parameter
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
            preserve_auxiliary_tables: Preserve auxiliary storage (label drags, etc.) in child projects
        
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
                        
                        # Find if layer exists in target
                        existing_layer = MirrorProjectLogic._find_layer_by_name(
                            target_project, layer.name()
                        )
                        
                        if existing_layer:
                            # Layer exists - update it in place (NEVER remove it)
                            if replace_data_source:
                                # Update data source AND symbology if requested
                                if MirrorProjectLogic._update_layer_in_place(
                                    existing_layer, 
                                    layer, 
                                    update_symbology,  # Pass the update_symbology flag
                                    preserve_layer_filters,
                                    preserve_auxiliary_tables,
                                    results
                                ):
                                    results['layers_exported'] += 1
                                    project_modified = True
                                else:
                                    results['warnings'].append(
                                        f"Failed to update layer '{layer.name()}' in {os.path.basename(project_path)}"
                                    )
                            else:
                                # Skip - layer exists and we're not replacing
                                if skip_same_name:
                                    results['warnings'].append(
                                        f"Skipped '{layer.name()}' in {os.path.basename(project_path)} (already exists)"
                                    )
                                else:
                                    # Layer exists but not configured to update - could optionally update symbology only
                                    if update_symbology:
                                        # Update only symbology without changing data source
                                        if MirrorProjectLogic._update_symbology_only(
                                            existing_layer,
                                            layer,
                                            preserve_layer_filters,
                                            preserve_auxiliary_tables,
                                            results
                                        ):
                                            results['warnings'].append(
                                                f"Updated symbology for existing layer '{layer.name()}' in {os.path.basename(project_path)}"
                                            )
                                        else:
                                            results['warnings'].append(
                                                f"Failed to update symbology for '{layer.name()}' in {os.path.basename(project_path)}"
                                            )
                                    else:
                                        results['warnings'].append(
                                            f"Layer '{layer.name()}' already exists in {os.path.basename(project_path)} - not updated"
                                        )
                        else:
                            # Layer doesn't exist - add it as new
                            if MirrorProjectLogic._add_new_layer_to_project(
                                layer, 
                                target_project, 
                                update_symbology, 
                                results
                            ):
                                results['layers_exported'] += 1
                                project_modified = True
                            else:
                                # Error already logged
                                pass
                    
                    except Exception as layer_error:
                        results['errors'].append(
                            f"Error exporting layer '{layer.name()}' to {os.path.basename(project_path)}: {str(layer_error)}"
                        )
                
                # Fix layer order if requested (AFTER all layers are added)
                if fix_layer_order:
                    if progress_callback:
                        progress_callback(
                            f"Fixing layer order in {os.path.basename(project_path)}...", 
                            int((current_step / total_steps) * 100)
                        )
                    MirrorProjectLogic._fix_layer_order(
                        master_project, 
                        target_project, 
                        results,
                        preserve_auxiliary_tables  # Pass the preserve flag
                    )

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
    def _clone_auxiliary_storage(aux_layer, results: dict = None) -> dict:
        """
        Clone auxiliary storage data from a layer.
        Returns a dict containing the auxiliary data that can be restored later.
        
        Args:
            aux_layer: The QgsAuxiliaryLayer to clone
            results: Optional results dict for messages
        
        Returns:
            dict: Cloned auxiliary data or None if failed
        """
        try:
            if not aux_layer:
                if results:
                    results['warnings'].append("DEBUG _clone_auxiliary_storage: aux_layer is None")
                return None
            
            feature_count = aux_layer.featureCount()
            if results:
                results['warnings'].append(f"DEBUG _clone_auxiliary_storage: Feature count = {feature_count}")
            
            if feature_count == 0:
                if results:
                    results['warnings'].append("DEBUG _clone_auxiliary_storage: No features to clone (count=0)")
                return None
            
            # Store auxiliary layer data
            auxiliary_data = {
                'features': [],
                'fields': aux_layer.fields(),
                'feature_count': feature_count
            }
            
            if results:
                results['warnings'].append(f"DEBUG _clone_auxiliary_storage: Fields = {[f.name() for f in aux_layer.fields()]}")
            
            # Copy all features from auxiliary layer
            feature_list = list(aux_layer.getFeatures())
            if results:
                results['warnings'].append(f"DEBUG _clone_auxiliary_storage: Retrieved {len(feature_list)} features from iterator")
            
            for idx, feature in enumerate(feature_list):
                attr_map = dict(feature.attributeMap())
                auxiliary_data['features'].append(attr_map)
                if results and idx < 3:  # Log first 3 features
                    results['warnings'].append(f"DEBUG _clone_auxiliary_storage: Feature {idx}: {attr_map}")
            
            if results:
                results['warnings'].append(f"DEBUG _clone_auxiliary_storage: Successfully cloned {len(auxiliary_data['features'])} features")
            
            return auxiliary_data
        
        except Exception as e:
            if results:
                results['warnings'].append(f"DEBUG _clone_auxiliary_storage: ERROR - {str(e)}")
            print(f"Error cloning auxiliary storage: {e}")
            import traceback
            traceback.print_exc()
            return None

    @staticmethod
    def _restore_auxiliary_storage(layer, auxiliary_data: dict, results: dict = None) -> bool:
        """
        Restore auxiliary storage data to a layer.
        
        Args:
            layer: The layer to restore auxiliary data to
            auxiliary_data: Dict containing auxiliary data from _clone_auxiliary_storage
            results: Optional results dict for messages
        
        Returns:
            bool: True if successful
        """
        try:
            if results:
                results['warnings'].append(f"DEBUG _restore_auxiliary_storage: Starting restore for layer '{layer.name()}'")
            
            if not auxiliary_data:
                if results:
                    results['warnings'].append("DEBUG _restore_auxiliary_storage: auxiliary_data is None")
                return False
            
            if not auxiliary_data.get('features'):
                if results:
                    results['warnings'].append("DEBUG _restore_auxiliary_storage: No features in auxiliary_data")
                return False
            
            if results:
                results['warnings'].append(f"DEBUG _restore_auxiliary_storage: Restoring {len(auxiliary_data['features'])} features")
            
            # Get or create auxiliary layer
            aux_layer = layer.auxiliaryLayer()
            if results:
                results['warnings'].append(f"DEBUG _restore_auxiliary_storage: Initial aux_layer = {aux_layer}")
            
            if not aux_layer:
                # Create auxiliary layer if it doesn't exist
                if results:
                    results['warnings'].append("DEBUG _restore_auxiliary_storage: Attempting to create auxiliary layer")
                
                from qgis.core import QgsAuxiliaryStorage
                project = layer.project()
                if results:
                    results['warnings'].append(f"DEBUG _restore_auxiliary_storage: Layer project = {project}")
                
                if project:
                    aux_storage = project.auxiliaryStorage()
                    if results:
                        results['warnings'].append(f"DEBUG _restore_auxiliary_storage: Auxiliary storage = {aux_storage}")
                    
                    if aux_storage:
                        layer_fields = layer.fields()
                        if layer_fields.count() > 0:
                            aux_layer = aux_storage.createAuxiliaryLayer(layer_fields[0], layer)
                            if results:
                                results['warnings'].append(f"DEBUG _restore_auxiliary_storage: Created aux_layer = {aux_layer}")
                            
                            if aux_layer:
                                layer.setAuxiliaryLayer(aux_layer)
                                if results:
                                    results['warnings'].append("DEBUG _restore_auxiliary_storage: Set auxiliary layer on main layer")
                        else:
                            if results:
                                results['warnings'].append("DEBUG _restore_auxiliary_storage: Layer has no fields")
            
            if not aux_layer:
                if results:
                    results['warnings'].append(f"DEBUG _restore_auxiliary_storage: Could not create/get auxiliary layer for '{layer.name()}'")
                return False
            
            # Clear existing auxiliary features
            if results:
                results['warnings'].append(f"DEBUG _restore_auxiliary_storage: Current aux layer feature count = {aux_layer.featureCount()}")
            
            aux_layer.startEditing()
            all_feature_ids = list(aux_layer.allFeatureIds())
            if results:
                results['warnings'].append(f"DEBUG _restore_auxiliary_storage: Deleting {len(all_feature_ids)} existing features")
            
            aux_layer.deleteFeatures(all_feature_ids)
            
            # Restore features
            from qgis.core import QgsFeature
            added_count = 0
            
            for idx, feature_data in enumerate(auxiliary_data['features']):
                feature = QgsFeature(aux_layer.fields())
                
                for field_name, value in feature_data.items():
                    field_idx = aux_layer.fields().indexOf(field_name)
                    if field_idx >= 0:
                        feature.setAttribute(field_idx, value)
                    elif results and idx < 3:
                        results['warnings'].append(f"DEBUG _restore_auxiliary_storage: Field '{field_name}' not found in aux layer")
                
                if aux_layer.addFeature(feature):
                    added_count += 1
                elif results and idx < 3:
                    results['warnings'].append(f"DEBUG _restore_auxiliary_storage: Failed to add feature {idx}")
            
            if results:
                results['warnings'].append(f"DEBUG _restore_auxiliary_storage: Added {added_count} features to aux layer")
            
            commit_result = aux_layer.commitChanges()
            if results:
                results['warnings'].append(f"DEBUG _restore_auxiliary_storage: Commit result = {commit_result}")
            
            if not commit_result:
                errors = aux_layer.commitErrors()
                if results:
                    results['warnings'].append(f"DEBUG _restore_auxiliary_storage: Commit errors = {errors}")
            
            # Verify restoration
            final_count = aux_layer.featureCount()
            if results:
                results['warnings'].append(f"DEBUG _restore_auxiliary_storage: Final aux layer feature count = {final_count}")
            
            if final_count > 0:
                if results:
                    results['warnings'].append(
                        f"✓ Restored {final_count} auxiliary features for '{layer.name()}'"
                    )
                return True
            else:
                if results:
                    results['warnings'].append(
                        f"✗ Auxiliary layer for '{layer.name()}' is empty after restore attempt"
                    )
                return False
        
        except Exception as e:
            if results:
                results['warnings'].append(f"DEBUG _restore_auxiliary_storage: EXCEPTION - {str(e)}")
            print(f"Error restoring auxiliary storage: {e}")
            import traceback
            traceback.print_exc()
            return False

    @staticmethod
    def _clone_layer_to_project(
        source_layer: QgsMapLayer,
        target_project: QgsProject,
        copy_symbology: bool = True,
        results: dict = None,
        existing_filter: str = None,
        preserve_layer_filters: bool = True,
        existing_auxiliary_storage: dict = None,
        preserve_auxiliary_tables: bool = True
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
            existing_auxiliary_storage: Previously captured auxiliary data to restore
            preserve_auxiliary_tables: Whether to preserve auxiliary storage
        
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
            
            # Add layer to target project FIRST (before copying symbology)
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
            
            # Copy symbology if requested (AFTER layer is in project)
            if copy_symbology:
                if results:
                    results['warnings'].append(f"DEBUG: Copying symbology for '{source_layer.name()}'")
                
                if source_layer.type() == QgsMapLayer.VectorLayer:
                    # Copy renderer
                    if source_layer.renderer():
                        try:
                            cloned_layer.setRenderer(source_layer.renderer().clone())
                            if results:
                                results['warnings'].append(f"DEBUG: Copied renderer for '{source_layer.name()}'")
                        except Exception as e:
                            error_msg = f"Warning for '{source_layer.name()}': Could not copy renderer - {str(e)}"
                            if results:
                                results['warnings'].append(error_msg)
                            print(error_msg)
                    
                    # Copy labeling (always copy, auxiliary preservation will be handled differently)
                    if source_layer.labeling():
                        try:
                            if results:
                                results['warnings'].append(f"DEBUG: About to copy labeling for '{source_layer.name()}'")
                            
                            cloned_layer.setLabeling(source_layer.labeling().clone())
                            cloned_layer.setLabelsEnabled(source_layer.labelsEnabled())
                            
                            if results:
                                results['warnings'].append(f"DEBUG: Copied labeling for '{source_layer.name()}'")
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
            
            # Apply the preserved filter AFTER the layer is fully configured
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
                except Exception as e:
                    error_msg = f"✗ Exception restoring filter for '{source_layer.name()}': {str(e)}"
                    if results:
                        results['warnings'].append(error_msg)
                    print(error_msg)
            
            # Restore auxiliary storage if we had preserved it (will be handled differently in future)
            if existing_auxiliary_storage and preserve_auxiliary_tables:
                if results:
                    results['warnings'].append(f"DEBUG: Auxiliary preservation requested for '{source_layer.name()}' but not yet implemented correctly")
            
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
        existing_auxiliary_storage: dict = None,
        preserve_auxiliary_tables: bool = True,
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
            existing_auxiliary_storage: Previously captured auxiliary data to restore
            preserve_auxiliary_tables: Whether to preserve auxiliary storage
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
            
            # Update symbology if requested
            if update_symbology:
                if results:
                    results['warnings'].append(f"DEBUG: Updating symbology for '{existing_layer.name()}'")
                
                if source_layer.type() == QgsMapLayer.VectorLayer:
                    # Copy renderer
                    if source_layer.renderer():
                        existing_layer.setRenderer(source_layer.renderer().clone())
                        if results:
                            results['warnings'].append(f"DEBUG: Updated renderer for '{existing_layer.name()}'")
                    
                    # Copy labeling (always copy, auxiliary preservation will be handled differently)
                    if source_layer.labeling():
                        if results:
                            results['warnings'].append(f"DEBUG: About to update labeling for '{existing_layer.name()}'")
                        
                        existing_layer.setLabeling(source_layer.labeling().clone())
                        existing_layer.setLabelsEnabled(source_layer.labelsEnabled())
                        
                        if results:
                            results['warnings'].append(f"DEBUG: Updated labeling for '{existing_layer.name()}'")
                
                elif source_layer.type() == QgsMapLayer.RasterLayer:
                    # Copy renderer for raster
                    if source_layer.renderer():
                        existing_layer.setRenderer(source_layer.renderer().clone())
            
            # Restore the preserved filter AFTER data source and symbology updates
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
            
            # Auxiliary storage restoration (will be handled differently in future)
            if existing_auxiliary_storage and preserve_auxiliary_tables:
                if results:
                    results['warnings'].append(f"DEBUG: Auxiliary preservation requested for '{existing_layer.name()}' but not yet implemented correctly")
            
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
        master_project: QgsProject,
        target_project: QgsProject,
        results: dict = None,
        preserve_auxiliary_tables: bool = True
    ):
        """
        Reorder layers and groups in target project to match master project structure.
        Creates groups as needed and positions layers correctly within them.
        
        Args:
            master_project: The master project
            target_project: The target project to update
            results: Optional results dict for messages
            preserve_auxiliary_tables: Not used - layers are never removed
        """
        try:
            if results:
                results['warnings'].append("Replicating layer tree structure from master project...")
            
            # Get the master project's layer tree structure
            master_root = master_project.layerTreeRoot()
            target_root = target_project.layerTreeRoot()
            
            # Build a map of target layers by name for quick lookup
            target_layers = {}
            for layer in target_project.mapLayers().values():
                target_layers[layer.name()] = layer
            
            # Recursive function to replicate structure
            def replicate_tree_node(master_node, target_parent):
                """
                Recursively replicate a master tree node (group or layer) into the target parent.
                
                Args:
                    master_node: The master node to replicate
                    target_parent: The target parent node to add to
                """
                for child in master_node.children():
                    if isinstance(child, QgsLayerTreeGroup):
                        # It's a group - find or create it in target
                        group_name = child.name()
                        target_group = target_parent.findGroup(group_name)
                        
                        if not target_group:
                            # Group doesn't exist - create it
                            target_group = target_parent.addGroup(group_name)
                            if results:
                                parent_name = target_parent.name() if isinstance(target_parent, QgsLayerTreeGroup) else "root"
                                results['warnings'].append(f"Created group '{group_name}' in '{parent_name}'")
                        
                        # Recursively replicate children of this group
                        replicate_tree_node(child, target_group)
                    
                    elif isinstance(child, QgsLayerTreeLayer):
                        # It's a layer - find it in target and move/add it
                        master_layer = child.layer()
                        if not master_layer:
                            continue
                        
                        layer_name = master_layer.name()
                        
                        # Check if this layer exists in target project
                        if layer_name not in target_layers:
                            if results:
                                results['warnings'].append(f"Layer '{layer_name}' not in target project, skipping position")
                            continue
                        
                        target_layer = target_layers[layer_name]
                        
                        # Find this layer's current node in target tree
                        existing_node = target_root.findLayer(target_layer.id())
                        
                        if existing_node:
                            # Layer exists somewhere in tree - need to move it
                            current_parent = existing_node.parent()
                            
                            if current_parent != target_parent:
                                # Layer is in wrong parent - move it
                                cloned_node = existing_node.clone()
                                current_parent.removeChildNode(existing_node)
                                target_parent.addChildNode(cloned_node)
                                
                                if results:
                                    current_parent_name = current_parent.name() if isinstance(current_parent, QgsLayerTreeGroup) else "root"
                                    target_parent_name = target_parent.name() if isinstance(target_parent, QgsLayerTreeGroup) else "root"
                                    results['warnings'].append(
                                        f"Moved layer '{layer_name}' from '{current_parent_name}' to '{target_parent_name}'"
                                    )
                            else:
                                # Layer is in correct parent, but might need reordering within parent
                                # We'll handle order in a second pass
                                pass
            
            # First pass: replicate structure (groups and layer parent assignments)
            replicate_tree_node(master_root, target_root)
            
            # Second pass: fix ordering within each group/parent
            def fix_ordering(master_node, target_node):
                """
                Fix the order of children in target_node to match master_node.
                
                Args:
                    master_node: The master node to match order from
                    target_node: The target node to reorder
                """
                master_children = master_node.children()
                target_children_map = {}
                
                # Build map of target children by name/layer
                for target_child in target_node.children():
                    if isinstance(target_child, QgsLayerTreeGroup):
                        target_children_map[f"group:{target_child.name()}"] = target_child
                    elif isinstance(target_child, QgsLayerTreeLayer):
                        if target_child.layer():
                            target_children_map[f"layer:{target_child.layer().name()}"] = target_child
                
                # Reorder to match master
                for index, master_child in enumerate(master_children):
                    if isinstance(master_child, QgsLayerTreeGroup):
                        key = f"group:{master_child.name()}"
                        if key in target_children_map:
                            target_child = target_children_map[key]
                            current_index = target_node.children().index(target_child)
                            
                            if current_index != index:
                                # Move to correct position
                                cloned = target_child.clone()
                                target_node.removeChildNode(target_child)
                                target_node.insertChildNode(index, cloned)
                                
                                if results:
                                    parent_name = target_node.name() if isinstance(target_node, QgsLayerTreeGroup) else "root"
                                    results['warnings'].append(
                                        f"Reordered group '{master_child.name()}' to position {index} in '{parent_name}'"
                                    )
                        
                        # Recursively fix ordering within this group
                        fix_ordering(master_child, target_children_map[key])
                    
                    elif isinstance(master_child, QgsLayerTreeLayer):
                        if master_child.layer():
                            key = f"layer:{master_child.layer().name()}"
                            if key in target_children_map:
                                target_child = target_children_map[key]
                                current_index = target_node.children().index(target_child)
                                
                                if current_index != index:
                                    # Move to correct position
                                    cloned = target_child.clone()
                                    target_node.removeChildNode(target_child)
                                    target_node.insertChildNode(index, cloned)
                                    
                                    if results:
                                        parent_name = target_node.name() if isinstance(target_node, QgsLayerTreeGroup) else "root"
                                        results['warnings'].append(
                                            f"Reordered layer '{master_child.layer().name()}' to position {index} in '{parent_name}'"
                                        )
            
            # Apply ordering
            fix_ordering(master_root, target_root)
            
            if results:
                results['warnings'].append("✓ Layer tree structure and order synchronized with master project")
        
        except Exception as e:
            if results:
                results['warnings'].append(f"Error fixing layer order: {str(e)}")
            print(f"Error fixing layer order: {e}")
            import traceback
            traceback.print_exc()

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

    @staticmethod
    def _update_layer_in_place(
        existing_layer: QgsMapLayer,
        source_layer: QgsMapLayer,
        update_symbology: bool,
        preserve_layer_filters: bool,
        preserve_auxiliary_tables: bool,
        results: dict = None
    ) -> bool:
        """
        Update an existing layer in place WITHOUT removing it from the project.
        This preserves auxiliary data and layer tree position.
        
        Args:
            existing_layer: The existing layer in the target project
            source_layer: The source layer from master project
            update_symbology: Whether to update symbology
            preserve_layer_filters: Whether to preserve existing filters
            preserve_auxiliary_tables: Whether to preserve auxiliary data
            results: Optional results dict for messages
        
        Returns:
            bool: True if successful
        """
        try:
            # Preserve filter if requested
            existing_filter = None
            if preserve_layer_filters:
                try:
                    if hasattr(existing_layer, 'subsetString'):
                        existing_filter = existing_layer.subsetString()
                        if existing_filter and results:
                            results['warnings'].append(
                                f"Preserving filter for '{existing_layer.name()}': {existing_filter}"
                            )
                except Exception as e:
                    if results:
                        results['warnings'].append(f"Could not read filter: {str(e)}")
            
            # Update data source
            new_source = source_layer.source()
            new_provider = source_layer.providerType()
            existing_layer.setDataSource(new_source, existing_layer.name(), new_provider)
            
            if results:
                results['warnings'].append(f"Updated data source for '{existing_layer.name()}'")
            
            # Update symbology if requested
            if update_symbology:
                if source_layer.type() == QgsMapLayer.VectorLayer:
                    # Copy renderer
                    if source_layer.renderer():
                        try:
                            existing_layer.setRenderer(source_layer.renderer().clone())
                            if results:
                                results['warnings'].append(f"Updated renderer for '{existing_layer.name()}'")
                        except Exception as e:
                            if results:
                                results['warnings'].append(f"Could not update renderer: {str(e)}")
                    
                    # Copy labeling
                    if source_layer.labeling():
                        try:
                            existing_layer.setLabeling(source_layer.labeling().clone())
                            existing_layer.setLabelsEnabled(source_layer.labelsEnabled())
                            if results:
                                results['warnings'].append(f"Updated labeling for '{existing_layer.name()}'")
                            
                            # Restore data-defined overrides for auxiliary data
                            if preserve_auxiliary_tables:
                                MirrorProjectLogic._restore_labeling_auxiliary_overrides(
                                    existing_layer,
                                    results
                                )
                        except Exception as e:
                            if results:
                                results['warnings'].append(f"Could not update labeling: {str(e)}")
                
                elif source_layer.type() == QgsMapLayer.RasterLayer:
                    # Copy renderer for raster
                    if source_layer.renderer():
                        try:
                            existing_layer.setRenderer(source_layer.renderer().clone())
                        except Exception as e:
                            if results:
                                results['warnings'].append(f"Could not update raster renderer: {str(e)}")
            
            # Restore filter if we preserved it
            if existing_filter and preserve_layer_filters:
                try:
                    if hasattr(existing_layer, 'setSubsetString'):
                        success = existing_layer.setSubsetString(existing_filter)
                        if success and results:
                            results['warnings'].append(f"Restored filter for '{existing_layer.name()}'")
                        elif not success and results:
                            results['warnings'].append(f"Failed to restore filter for '{existing_layer.name()}'")
                except Exception as e:
                    if results:
                        results['warnings'].append(f"Error restoring filter: {str(e)}")
            
            # Verify auxiliary data is still present (if it was there before)
            if preserve_auxiliary_tables:
                try:
                    aux_layer = existing_layer.auxiliaryLayer()
                    if aux_layer and aux_layer.featureCount() > 0:
                        if results:
                            results['warnings'].append(
                                f"✓ Auxiliary data preserved for '{existing_layer.name()}' "
                                f"({aux_layer.featureCount()} features)"
                            )
                    elif results:
                        results['warnings'].append(
                            f"No auxiliary data found for '{existing_layer.name()}' after update"
                        )
                except Exception as e:
                    if results:
                        results['warnings'].append(f"Error checking auxiliary data: {str(e)}")
            
            return True
        
        except Exception as e:
            if results:
                results['errors'].append(f"Error updating layer in place: {str(e)}")
            print(f"Error updating layer in place: {e}")
            import traceback
            traceback.print_exc()
            return False

    @staticmethod
    def _restore_labeling_auxiliary_overrides(
        layer: QgsVectorLayer,
        results: dict = None
    ):
        """
        Restore data-defined overrides for labeling properties that connect to auxiliary storage.
        This reconnects label position, rotation, and other manually adjusted properties to the
        auxiliary storage fields after labeling configuration has been updated.
        Supports both simple and rule-based labeling.
        
        Args:
            layer: The vector layer to restore overrides for
            results: Optional results dict for messages
        """
        try:
            from qgis.core import QgsPalLayerSettings, QgsProperty, QgsRuleBasedLabeling
            
            # Get the auxiliary layer
            aux_layer = layer.auxiliaryLayer()
            if not aux_layer:
                if results:
                    results['warnings'].append(f"  ↳ No auxiliary layer found for '{layer.name()}' - cannot restore overrides")
                return
            
            # Check if auxiliary layer has any features
            if aux_layer.featureCount() == 0:
                if results:
                    results['warnings'].append(f"  ↳ Auxiliary layer for '{layer.name()}' has no features - no overrides to restore")
                return
            
            # Get the labeling configuration
            labeling = layer.labeling()
            if not labeling:
                if results:
                    results['warnings'].append(f"  ↳ No labeling configuration for '{layer.name()}'")
                return
            
            # Build a map of layer fields (which includes the joined auxiliary fields with prefix)
            layer_fields = {}
            for field in layer.fields():
                layer_fields[field.name().lower()] = field.name()
            
            if results:
                aux_field_names = [f for f in layer_fields.keys() if 'auxiliary_storage' in f]
                if aux_field_names:
                    results['warnings'].append(f"  ↳ Available auxiliary fields in layer: {', '.join(aux_field_names[:5])}{'...' if len(aux_field_names) > 5 else ''}")
            
            # Property mappings
            property_mappings = {
                'positionx': QgsPalLayerSettings.PositionX,
                'positiony': QgsPalLayerSettings.PositionY,
                'rotation': QgsPalLayerSettings.LabelRotation,
                'show': QgsPalLayerSettings.Show,
                'alwaysshow': QgsPalLayerSettings.AlwaysShow,
                'fontsize': QgsPalLayerSettings.Size,
                'color': QgsPalLayerSettings.Color,
                'fontfamily': QgsPalLayerSettings.Family,
                'fontstyle': QgsPalLayerSettings.FontStyle,
                'hali': QgsPalLayerSettings.Hali,
                'vali': QgsPalLayerSettings.Vali,
                'lineanchorpercent': QgsPalLayerSettings.LineAnchorPercent,
                'lineanchorclipping': QgsPalLayerSettings.LineAnchorClipping,
                'lineanchortype': QgsPalLayerSettings.LineAnchorType,
                'lineanchortextpoint': QgsPalLayerSettings.LineAnchorTextPoint,
            }
            
            # Helper function to restore overrides for a single settings object
            def restore_overrides_for_settings(settings, label_context=""):
                overrides_restored = 0
                for prop_suffix, property_key in property_mappings.items():
                    # The field name in the layer will be "auxiliary_storage_labeling_<property>"
                    field_name = f'auxiliary_storage_labeling_{prop_suffix}'
                    
                    if field_name.lower() in layer_fields:
                        # Get the actual field name (with proper casing)
                        actual_field_name = layer_fields[field_name.lower()]
                        
                        # Create a data-defined property that references this field
                        prop = QgsProperty.fromField(actual_field_name)
                        
                        # Set the data-defined override
                        data_defined = settings.dataDefinedProperties()
                        data_defined.setProperty(property_key, prop)
                        settings.setDataDefinedProperties(data_defined)
                        
                        overrides_restored += 1
                
                if overrides_restored > 0 and results:
                    context_str = f" ({label_context})" if label_context else ""
                    results['warnings'].append(f"  ↳   Restored {overrides_restored} overrides{context_str}")
                
                return overrides_restored
            
            total_overrides_restored = 0
            
            # Check labeling type
            labeling_type = labeling.type() if hasattr(labeling, 'type') else None
            
            if labeling_type == 'rule-based':
                # Rule-based labeling - need to process each rule
                if results:
                    results['warnings'].append(f"  ↳ Processing rule-based labeling for '{layer.name()}'")
                
                # Get the root rule
                root_rule = labeling.rootRule()
                
                # Recursive function to process all rules
                def process_rule(rule, depth=0):
                    nonlocal total_overrides_restored
                    
                    # Process this rule's settings if it has them
                    if rule.settings():
                        rule_label = rule.description() or f"Rule at depth {depth}"
                        count = restore_overrides_for_settings(rule.settings(), f"rule: {rule_label}")
                        total_overrides_restored += count
                    
                    # Process child rules recursively
                    for child_rule in rule.children():
                        process_rule(child_rule, depth + 1)
                
                # Start processing from root
                process_rule(root_rule)
                
                # Update the labeling with modified rules
                layer.setLabeling(labeling)
            
            elif labeling_type == 'simple' or hasattr(labeling, 'settings'):
                # Simple labeling
                if results:
                    results['warnings'].append(f"  ↳ Processing simple labeling for '{layer.name()}'")
                
                settings = labeling.settings()
                if settings:
                    total_overrides_restored = restore_overrides_for_settings(settings)
                    
                    # Update the labeling with modified settings
                    if hasattr(labeling, 'setSettings'):
                        labeling.setSettings(settings)
                        layer.setLabeling(labeling)
            
            else:
                if results:
                    results['warnings'].append(f"  ↳ Unknown labeling type '{labeling_type}' for '{layer.name()}'")
                return
            
            # Summary
            if total_overrides_restored > 0:
                if results:
                    results['warnings'].append(
                        f"  ↳ ✓ Restored {total_overrides_restored} data-defined overrides total for '{layer.name()}'"
                    )
            else:
                if results:
                    results['warnings'].append(
                        f"  ↳ ⚠ No matching auxiliary labeling fields found for '{layer.name()}'"
                    )
        
        except Exception as e:
            if results:
                results['warnings'].append(f"  ↳ Error restoring labeling overrides: {str(e)}")
            print(f"Error restoring labeling overrides: {e}")
            import traceback
            traceback.print_exc()
    
    @staticmethod
    def _update_symbology_only(
        existing_layer: QgsMapLayer,
        source_layer: QgsMapLayer,
        preserve_layer_filters: bool,
        preserve_auxiliary_tables: bool,
        results: dict = None
    ) -> bool:
        """
        Update only the symbology of an existing layer without changing its data source.
        This is used when a layer exists in the child project but we're not replacing the data source,
        but we still want to update the visual styling to match the master project.
        
        Args:
            existing_layer: The existing layer in the target project
            source_layer: The source layer from master project
            preserve_layer_filters: Whether to preserve existing filters
            preserve_auxiliary_tables: Whether to preserve auxiliary data
            results: Optional results dict for messages
        
        Returns:
            bool: True if successful
        """
        try:
            # Preserve filter if requested
            existing_filter = None
            if preserve_layer_filters:
                try:
                    if hasattr(existing_layer, 'subsetString'):
                        existing_filter = existing_layer.subsetString()
                        if existing_filter and results:
                            results['warnings'].append(
                                f"Preserving filter for '{existing_layer.name()}': {existing_filter}"
                            )
                except Exception as e:
                    if results:
                        results['warnings'].append(f"Could not read filter: {str(e)}")
            
            # Update symbology
            if source_layer.type() == QgsMapLayer.VectorLayer:
                # Copy renderer
                if source_layer.renderer():
                    try:
                        existing_layer.setRenderer(source_layer.renderer().clone())
                        if results:
                            results['warnings'].append(f"Updated renderer for '{existing_layer.name()}'")
                    except Exception as e:
                        if results:
                            results['warnings'].append(f"Could not update renderer: {str(e)}")
                
                # Copy labeling
                if source_layer.labeling():
                    try:
                        existing_layer.setLabeling(source_layer.labeling().clone())
                        existing_layer.setLabelsEnabled(source_layer.labelsEnabled())
                        if results:
                            results['warnings'].append(f"Updated labeling for '{existing_layer.name()}'")
                        
                        # Restore data-defined overrides for auxiliary data if preserving
                        if preserve_auxiliary_tables:
                            MirrorProjectLogic._restore_labeling_auxiliary_overrides(
                                existing_layer,
                                results
                            )
                    except Exception as e:
                        if results:
                            results['warnings'].append(f"Could not update labeling: {str(e)}")
            
            elif source_layer.type() == QgsMapLayer.RasterLayer:
                # Copy renderer for raster
                if source_layer.renderer():
                    try:
                        existing_layer.setRenderer(source_layer.renderer().clone())
                    except Exception as e:
                        if results:
                            results['warnings'].append(f"Could not update raster renderer: {str(e)}")
            
            # Restore filter if we preserved it
            if existing_filter and preserve_layer_filters:
                try:
                    if hasattr(existing_layer, 'setSubsetString'):
                        success = existing_layer.setSubsetString(existing_filter)
                        if success and results:
                            results['warnings'].append(f"Restored filter for '{existing_layer.name()}'")
                        elif not success and results:
                            results['warnings'].append(f"Failed to restore filter for '{existing_layer.name()}'")
                except Exception as e:
                    if results:
                        results['warnings'].append(f"Error restoring filter: {str(e)}")
            
            return True
        
        except Exception as e:
            if results:
                results['errors'].append(f"Error updating symbology only: {str(e)}")
            print(f"Error updating symbology only: {e}")
            import traceback
            traceback.print_exc()
            return False

    @staticmethod
    def _add_new_layer_to_project(
        layer: QgsMapLayer,
        target_project: QgsProject,
        update_symbology: bool,
        results: dict = None
    ) -> bool:
        """
        Add a new layer to the target project (layer doesn't exist yet).
        
        Args:
            layer: The layer to add
            target_project: The project to add to
            update_symbology: Whether to copy symbology
            results: Optional results dict for messages
        
        Returns:
            bool: True if successful
        """
        try:
            # Use the clone method to add the new layer
            return MirrorProjectLogic._clone_layer_to_project(
                layer,
                target_project,
                copy_symbology=update_symbology,
                results=results,
                existing_filter=None,  # No existing filter for new layers
                preserve_layer_filters=False,  # Not applicable for new layers
                existing_auxiliary_storage=None,  # No existing auxiliary for new layers
                preserve_auxiliary_tables=False  # Not applicable for new layers
            )
        except Exception as e:
            if results:
                results['errors'].append(f"Error adding new layer: {str(e)}")
            print(f"Error adding new layer: {e}")
            return False

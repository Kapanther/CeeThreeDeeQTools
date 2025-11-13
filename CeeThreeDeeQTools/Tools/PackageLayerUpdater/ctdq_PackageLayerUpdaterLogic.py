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

from qgis.core import QgsProject, QgsVectorLayer, QgsVectorFileWriter, QgsCoordinateTransformContext, QgsLayerMetadata
from osgeo import ogr
import os
from datetime import datetime
import sqlite3


class PackageLayerUpdaterLogic:
    """
    Logic for updating layers in geopackages from the active project.
    """
    
    @staticmethod
    def update_geopackage_layers(
        layer_ids: list,
        target_geopackages: list,
        progress_callback=None
    ):
        """
        Update layers in geopackages with data from the active project.
        
        Args:
            layer_ids: List of layer IDs from the active project
            target_geopackages: List of geopackage file paths to update
            progress_callback: Optional callback function(message, progress)
        
        Returns:
            dict: Results with success/error information
        """
        results = {
            'success': True,
            'geopackages_updated': 0,
            'layers_updated': 0,
            'errors': [],
            'warnings': []
        }
        
        # Get project
        project = QgsProject.instance()
        
        # Get layer objects from IDs
        layers_to_export = []
        for layer_id in layer_ids:
            layer = project.mapLayer(layer_id)
            if layer and layer.isValid():
                layers_to_export.append(layer)
            else:
                results['warnings'].append(f"Layer with ID {layer_id} not found or invalid")
        
        if not layers_to_export:
            results['success'] = False
            results['errors'].append("No valid layers to export")
            return results
        
        total_steps = len(target_geopackages) * len(layers_to_export)
        current_step = 0
        
        # Process each geopackage
        for gpkg_path in target_geopackages:
            try:
                if progress_callback:
                    progress_callback(
                        f"Processing geopackage: {os.path.basename(gpkg_path)}", 
                        int((current_step / total_steps) * 100)
                    )
                
                if not os.path.exists(gpkg_path):
                    results['errors'].append(f"Geopackage not found: {gpkg_path}")
                    continue
                
                gpkg_modified = False
                
                # Get list of layers in the geopackage
                gpkg_layers = PackageLayerUpdaterLogic._get_geopackage_layers(gpkg_path)
                
                if not gpkg_layers:
                    results['warnings'].append(f"No layers found in geopackage: {os.path.basename(gpkg_path)}")
                    continue
                
                results['warnings'].append(
                    f"Found {len(gpkg_layers)} layers in {os.path.basename(gpkg_path)}: {', '.join(gpkg_layers)}"
                )
                
                # Update each matching layer
                for layer in layers_to_export:
                    current_step += 1
                    
                    try:
                        if progress_callback:
                            progress_callback(
                                f"Checking layer '{layer.name()}' in {os.path.basename(gpkg_path)}", 
                                int((current_step / total_steps) * 100)
                            )
                        
                        # Check if layer name exists in geopackage
                        if layer.name() in gpkg_layers:
                            if PackageLayerUpdaterLogic._update_layer_in_geopackage(
                                layer, gpkg_path, results
                            ):
                                results['layers_updated'] += 1
                                gpkg_modified = True
                                results['warnings'].append(
                                    f"✓ Updated layer '{layer.name()}' in {os.path.basename(gpkg_path)}"
                                )
                            else:
                                results['warnings'].append(
                                    f"✗ Failed to update layer '{layer.name()}' in {os.path.basename(gpkg_path)}"
                                )
                        else:
                            results['warnings'].append(
                                f"Layer '{layer.name()}' not found in {os.path.basename(gpkg_path)}"
                            )
                    
                    except Exception as layer_error:
                        results['errors'].append(
                            f"Error updating layer '{layer.name()}' in {os.path.basename(gpkg_path)}: {str(layer_error)}"
                        )
                
                if gpkg_modified:
                    results['geopackages_updated'] += 1
            
            except Exception as gpkg_error:
                results['errors'].append(f"Error processing geopackage {gpkg_path}: {str(gpkg_error)}")
        
        if results['errors']:
            results['success'] = False
        
        return results
    
    @staticmethod
    def _get_geopackage_layers(gpkg_path: str) -> list:
        """Get list of layer names in a geopackage."""
        try:
            ds = ogr.Open(gpkg_path, 0)  # 0 = read-only
            if ds is None:
                return []
            
            layer_names = []
            for i in range(ds.GetLayerCount()):
                layer = ds.GetLayerByIndex(i)
                if layer:
                    layer_names.append(layer.GetName())
            
            ds = None
            return layer_names
        
        except Exception as e:
            print(f"Error reading geopackage layers: {e}")
            return []
    
    @staticmethod
    def _update_layer_in_geopackage(
        source_layer: QgsVectorLayer,
        gpkg_path: str,
        results: dict = None
    ) -> bool:
        """
        Update a layer in a geopackage with data from the source layer.
        
        Args:
            source_layer: The layer from the active project
            gpkg_path: Path to the geopackage
            results: Optional results dict for messages
        
        Returns:
            bool: True if successful
        """
        try:
            # First, preserve the existing layer's metadata history from the geopackage
            existing_history = PackageLayerUpdaterLogic._get_layer_history(gpkg_path, source_layer.name())
            
            if results and existing_history:
                results['warnings'].append(f"Preserved {len(existing_history)} existing history entries for '{source_layer.name()}'")
            
            # Delete the existing layer in the geopackage
            ds = ogr.Open(gpkg_path, 1)  # 1 = read-write
            if ds is None:
                if results:
                    results['errors'].append(f"Could not open geopackage for writing: {gpkg_path}")
                return False
            
            # Find and delete the layer
            for i in range(ds.GetLayerCount()):
                layer = ds.GetLayerByIndex(i)
                if layer and layer.GetName() == source_layer.name():
                    ds.DeleteLayer(i)
                    if results:
                        results['warnings'].append(f"Deleted existing layer '{source_layer.name()}' from geopackage")
                    break
            
            ds = None
            
            # Create new history entry
            new_history_entry = PackageLayerUpdaterLogic._create_history_entry(source_layer)
            
            # Combine existing history with new entry
            updated_history = existing_history + [new_history_entry] if existing_history else [new_history_entry]
            
            # Create a NEW metadata object with the updated history
            layer_metadata = QgsLayerMetadata()
            
            # Copy basic metadata from source layer
            source_metadata = source_layer.metadata()
            layer_metadata.setIdentifier(source_metadata.identifier())
            layer_metadata.setTitle(source_metadata.title() or source_layer.name())
            layer_metadata.setAbstract(source_metadata.abstract())
            layer_metadata.setKeywords(source_metadata.keywords())
            layer_metadata.setCategories(source_metadata.categories())
            layer_metadata.setContacts(source_metadata.contacts())
            layer_metadata.setLinks(source_metadata.links())
            
            # Set the updated history
            layer_metadata.setHistory(updated_history)
            
            if results:
                results['warnings'].append(f"Created metadata with {len(updated_history)} history entries")
                results['warnings'].append(f"  Latest: {new_history_entry}")
            
            # Write the layer to the geopackage WITH the new metadata
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = source_layer.name()
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
            options.layerMetadata = layer_metadata  # Pass metadata directly in options
            
            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                source_layer,
                gpkg_path,
                QgsCoordinateTransformContext(),
                options
            )
            
            if error[0] != QgsVectorFileWriter.NoError:
                if results:
                    results['errors'].append(
                        f"Error writing layer '{source_layer.name()}' to geopackage: {error[1]}"
                    )
                return False
            
            if results:
                results['warnings'].append(f"✓ Layer '{source_layer.name()}' written to geopackage")
            
            # Verify the history was saved
            import time
            time.sleep(0.15)  # Delay to ensure write is complete
            
            saved_history = PackageLayerUpdaterLogic._get_layer_history(gpkg_path, source_layer.name())
            if saved_history and len(saved_history) == len(updated_history):
                if results:
                    results['warnings'].append(
                        f"✓ Verified: History in geopackage has {len(saved_history)} entries (matches expected)"
                    )
            elif saved_history:
                if results:
                    results['warnings'].append(
                        f"⚠ History count mismatch: expected {len(updated_history)}, found {len(saved_history)}"
                    )
            else:
                if results:
                    results['warnings'].append(
                        f"⚠ Could not verify history in geopackage"
                    )
            
            return True
        
        except Exception as e:
            if results:
                results['errors'].append(f"Exception updating layer '{source_layer.name()}': {str(e)}")
            print(f"Error updating layer in geopackage: {e}")
            return False

    @staticmethod
    def _get_layer_history(gpkg_path: str, layer_name: str) -> list:
        """
        Get the existing history from a layer's metadata in the geopackage.
        First tries to read from the layer's QGIS metadata, then falls back to gpkg_contents description.
        
        Args:
            gpkg_path: Path to the geopackage
            layer_name: Name of the layer
        
        Returns:
            list: List of history entries (strings)
        """
        try:
            # Try to load the layer and read its QGIS metadata first
            uri = f"{gpkg_path}|layername={layer_name}"
            layer = QgsVectorLayer(uri, layer_name, "ogr")
            
            if layer.isValid():
                metadata = layer.metadata()
                history_list = metadata.history()
                
                if history_list:
                    print(f"Found {len(history_list)} history entries in layer metadata for '{layer_name}':")
                    for entry in history_list:
                        print(f"  - {entry}")
                    return history_list
            
            # Fallback: try to read from gpkg_contents description field
            conn = sqlite3.connect(gpkg_path)
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT description FROM gpkg_contents WHERE table_name = ?",
                (layer_name,)
            )
            result = cursor.fetchone()
            conn.close()
            
            if result and result[0]:
                description = result[0]
                if description.startswith("HISTORY:"):
                    history_text = description[8:]
                    history_list = [h.strip() for h in history_text.split('\n') if h.strip()]
                    print(f"Found {len(history_list)} history entries in gpkg_contents for '{layer_name}':")
                    for entry in history_list:
                        print(f"  - {entry}")
                    return history_list
            
            print(f"No history found for '{layer_name}'")
            return []
        
        except Exception as e:
            print(f"Error reading layer history: {e}")
            return []

    @staticmethod
    def _create_history_entry(source_layer: QgsVectorLayer) -> str:
        """
        Create a history entry string for the layer update.
        
        Args:
            source_layer: The source layer being written
        
        Returns:
            str: History entry in format "YYYY-MM-DD@HH-MM-SS; source_path"
        """
        timestamp = datetime.now().strftime("%Y-%m-%d@%H-%M-%S")
        source_path = source_layer.source()
        
        # Format: timestamp; source_path
        return f"{timestamp}; {source_path}"

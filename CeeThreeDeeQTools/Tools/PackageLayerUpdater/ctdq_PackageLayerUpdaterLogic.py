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

from qgis.core import QgsProject, QgsVectorLayer, QgsRasterLayer, QgsVectorFileWriter, QgsRasterFileWriter, QgsCoordinateTransformContext, QgsLayerMetadata
from osgeo import ogr, gdal
import os
from datetime import datetime
import sqlite3
import processing


class PackageLayerUpdaterLogic:
    """
    Logic for updating layers in geopackages from the active project.
    """
    
    @staticmethod
    def update_geopackage_layers(
        layer_ids: list,
        target_geopackages: list,
        progress_callback=None,
        update_new_only: bool = False,
        fix_fids: bool = False
    ):
        """
        Update layers in geopackages with data from the active project.
        
        Args:
            layer_ids: List of layer IDs from the active project
            target_geopackages: List of geopackage file paths to update
            progress_callback: Optional callback function(message, progress)
            update_new_only: Only update layers that have been modified since last update
            fix_fids: Fix duplicate FID values by renumbering
        
        Returns:
            dict: Results with success/error information
        """
        results = {
            'success': True,
            'geopackages_updated': 0,
            'layers_updated': 0,
            'layers_skipped': 0,
            'fids_fixed': 0,
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
                            # Check if we should skip this layer based on modification date
                            if update_new_only:
                                should_update = PackageLayerUpdaterLogic._should_update_layer(
                                    layer, gpkg_path, results
                                )
                                if not should_update:
                                    results['layers_skipped'] += 1
                                    results['warnings'].append(
                                        f"⊘ Skipped '{layer.name()}' in {os.path.basename(gpkg_path)} (not modified since last update)"
                                    )
                                    continue
                        
                            # Check for duplicate FIDs before updating (only for vector layers)
                            from qgis.core import QgsMapLayer
                            if layer.type() == QgsMapLayer.VectorLayer:
                                fid_check = PackageLayerUpdaterLogic._check_and_fix_duplicate_fids(
                                    layer, fix_fids, results
                                )
                                
                                if not fid_check['can_proceed']:
                                    results['layers_skipped'] += 1
                                    results['warnings'].append(
                                        f"⊘ Skipped '{layer.name()}' in {os.path.basename(gpkg_path)}: {fid_check['message']}"
                                    )
                                    continue
                                
                                if fid_check['fixed_count'] > 0:
                                    results['fids_fixed'] += fid_check['fixed_count']
                                    results['warnings'].append(
                                        f"✓ Fixed {fid_check['fixed_count']} duplicate FID(s) in '{layer.name()}'"
                                    )
                        
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
        """
        Get list of both vector and raster layer names in a geopackage.
        
        Args:
            gpkg_path: Path to the geopackage
        
        Returns:
            list: List of layer names (both vector and raster)
        """
        layer_names = []
        
        try:
            # Get vector layers using OGR
            ds = ogr.Open(gpkg_path, 0)  # 0 = read-only
            if ds is not None:
                for i in range(ds.GetLayerCount()):
                    layer = ds.GetLayerByIndex(i)
                    if layer:
                        layer_names.append(layer.GetName())
                        print(f"Found vector layer: {layer.GetName()}")
                ds = None
        except Exception as e:
            print(f"Error reading vector layers from geopackage: {e}")
        
        try:
            # Get raster layers using GDAL subdatasets
            print(f"Checking for rasters in: {gpkg_path}")
            ds = gdal.Open(gpkg_path, gdal.GA_ReadOnly)
            if ds is not None:
                # Check for subdatasets (rasters in geopackage)
                subdatasets = ds.GetSubDatasets()
                print(f"Found {len(subdatasets) if subdatasets else 0} subdatasets")
                
                if subdatasets:
                    for subdataset_desc, subdataset_name in subdatasets:
                        print(f"  Subdataset: {subdataset_name}")
                        print(f"  Description: {subdataset_desc}")
                        
                        # Extract the raster table name from the subdataset
                        try:
                            # Parse the table name from subdataset_name
                            # Format: GPKG:C:/path/file.gpkg:table_name
                            if ':' in subdataset_name:
                                parts = subdataset_name.split(':')
                                if len(parts) >= 3:
                                    table_name = parts[2]  # GPKG:path:table_name
                                    if table_name not in layer_names:
                                        layer_names.append(table_name)
                                        print(f"  Added raster layer: {table_name}")
                        except Exception as parse_err:
                            print(f"  Error parsing raster subdataset name: {parse_err}")
                else:
                    print("  No subdatasets found, checking metadata...")
                
                ds = None
        except Exception as e:
            print(f"Error reading raster layers from geopackage with GDAL: {e}")
        
        try:
            # Alternative method: Query gpkg_contents table directly
            conn = sqlite3.connect(gpkg_path)
            cursor = conn.cursor()
            
            # Get all table names from gpkg_contents
            cursor.execute("SELECT table_name, data_type FROM gpkg_contents")
            contents = cursor.fetchall()
            
            print(f"Contents from gpkg_contents table:")
            for table_name, data_type in contents:
                print(f"  {table_name} ({data_type})")
                
                # Add raster tables that aren't already in the list
                if data_type == 'tiles' or data_type == '2d-gridded-coverage':
                    if table_name not in layer_names:
                        layer_names.append(table_name)
                        print(f"  Added raster from gpkg_contents: {table_name}")
            
            conn.close()
        except Exception as e:
            print(f"Error querying gpkg_contents table: {e}")
        
        print(f"Total layers found: {len(layer_names)}")
        return layer_names
    
    @staticmethod
    def _update_layer_in_geopackage(
        source_layer,  # Can be QgsVectorLayer or QgsRasterLayer
        gpkg_path: str,
        results: dict = None
    ) -> bool:
        """
        Update a layer in a geopackage with data from the source layer.
        Supports both vector and raster layers.
        
        Args:
            source_layer: The layer from the active project (vector or raster)
            gpkg_path: Path to the geopackage
            results: Optional results dict for messages
        
        Returns:
            bool: True if successful
        """
        try:
            # Determine layer type
            from qgis.core import QgsMapLayer
            is_raster = source_layer.type() == QgsMapLayer.RasterLayer
            
            if is_raster:
                return PackageLayerUpdaterLogic._update_raster_layer_in_geopackage(
                    source_layer, gpkg_path, results
                )
            else:
                return PackageLayerUpdaterLogic._update_vector_layer_in_geopackage(
                    source_layer, gpkg_path, results
                )
        
        except Exception as e:
            if results:
                results['errors'].append(f"Exception updating layer '{source_layer.name()}': {str(e)}")
            print(f"Error updating layer in geopackage: {e}")
            return False

    @staticmethod
    def _update_vector_layer_in_geopackage(
        source_layer: QgsVectorLayer,
        gpkg_path: str,
        results: dict = None
    ) -> bool:
        """
        Update a vector layer in a geopackage with data from the source layer.
        
        Args:
            source_layer: The vector layer from the active project
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
                        results['warnings'].append(f"Deleted existing vector layer '{source_layer.name()}' from geopackage")
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
            options.saveMetadata = True
            
            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                source_layer,
                gpkg_path,
                QgsCoordinateTransformContext(),
                options
            )
            
            if error[0] != QgsVectorFileWriter.NoError:
                if results:
                    results['errors'].append(
                        f"Error writing vector layer '{source_layer.name()}' to geopackage: {error[1]}"
                    )
                return False
            
            if results:
                results['warnings'].append(f"✓ Vector layer '{source_layer.name()}' written to geopackage")
            
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
                results['errors'].append(f"Exception updating vector layer '{source_layer.name()}': {str(e)}")
            print(f"Error updating vector layer in geopackage: {e}")
            return False

    @staticmethod
    def _update_raster_layer_in_geopackage(
        source_layer: QgsRasterLayer,
        gpkg_path: str,
        results: dict = None
    ) -> bool:
        """
        Update a raster layer in a geopackage with data from the source layer.
        Uses QGIS processing framework's gdal:translate for proper geopackage handling.
        
        Args:
            source_layer: The raster layer from the active project
            gpkg_path: Path to the geopackage
            results: Optional results dict for messages
        
        Returns:
            bool: True if successful
        """
        try:
            # First, preserve the existing layer's metadata history
            existing_history = PackageLayerUpdaterLogic._get_layer_history(gpkg_path, source_layer.name())
            
            if results and existing_history:
                results['warnings'].append(f"Preserved {len(existing_history)} existing history entries for '{source_layer.name()}'")
            
            # Get the source raster file path
            source_path = source_layer.source().split('|')[0]
            
            if not os.path.exists(source_path):
                if results:
                    results['errors'].append(f"Source raster file not found: {source_path}")
                return False
            
            # Create new history entry
            new_history_entry = PackageLayerUpdaterLogic._create_history_entry(source_layer)
            
            # Combine existing history with new entry
            updated_history = existing_history + [new_history_entry] if existing_history else [new_history_entry]
            
            if results:
                results['warnings'].append(f"Updating raster '{source_layer.name()}' in geopackage (will overwrite if exists)")
            
            # Use QGIS processing framework's gdal:translate
            # APPEND_SUBDATASET will overwrite if the raster table already exists
            params = {
                'INPUT': source_path,
                'TARGET_CRS': None,
                'NODATA': None,
                'COPY_SUBDATASETS': False,
                'OPTIONS': '',
                'EXTRA': f'-co APPEND_SUBDATASET=YES -co RASTER_TABLE={source_layer.name()}',
                'DATA_TYPE': 0,  # Use same data type as source
                'OUTPUT': gpkg_path
            }
            
            # Run the processing algorithm
            result = processing.run("gdal:translate", params)
            
            if not result or 'OUTPUT' not in result:
                if results:
                    results['errors'].append(f"Failed to write raster '{source_layer.name()}' to geopackage")
                return False
            
            if results:
                results['warnings'].append(f"✓ Raster layer '{source_layer.name()}' written to geopackage")
                results['warnings'].append(f"  Latest: {new_history_entry}")
            
            # Write history metadata to the geopackage contents table
            import time
            time.sleep(0.3)  # Longer delay to ensure write is complete
            
            # Write history to gpkg_contents description field
            if PackageLayerUpdaterLogic._write_raster_history_to_gpkg(
                gpkg_path,
                source_layer.name(),
                updated_history,
                results
            ):
                if results:
                    results['warnings'].append(f"✓ History metadata saved for '{source_layer.name()}'")
            
            return True
        
        except Exception as e:
            if results:
                results['errors'].append(f"Exception updating raster layer '{source_layer.name()}': {str(e)}")
            print(f"Error updating raster layer in geopackage: {e}")
            import traceback
            traceback.print_exc()
            return False

    @staticmethod
    def _write_raster_history_to_gpkg(
        gpkg_path: str,
        layer_name: str,
        history_entries: list,
        results: dict = None
    ) -> bool:
        """
        Write history metadata for a raster layer directly to the geopackage.
        Note: Raster layers in geopackages don't support the rich metadata/history structure
        that vector layers have. History is stored in gpkg_contents.description field,
        which appears in Layer Properties → Information → More information → DESCRIPTION.
        
        Args:
            gpkg_path: Path to the geopackage
            layer_name: Name of the raster layer
            history_entries: List of history entry strings
            results: Optional results dict for messages
        
        Returns:
            bool: True if successful
        """
        try:
            # Connect to the geopackage database
            conn = sqlite3.connect(gpkg_path)
            cursor = conn.cursor()
            
            # Check if our specific table exists
            cursor.execute(
                "SELECT table_name FROM gpkg_contents WHERE table_name = ?",
                (layer_name,)
            )
            existing_row = cursor.fetchone()
            
            if not existing_row:
                # Try with LIKE pattern in case the table name has been modified
                cursor.execute(
                    "SELECT table_name FROM gpkg_contents WHERE table_name LIKE ?",
                    (f"%{layer_name}%",)
                )
                like_matches = cursor.fetchall()
                
                if like_matches:
                    layer_name = like_matches[0][0]
                    if results:
                        results['warnings'].append(f"Using table name '{layer_name}' for history update")
                else:
                    if results:
                        results['warnings'].append(f"Raster table '{layer_name}' not found in gpkg_contents")
                    conn.close()
                    return False
            
            # Format history as a text block with prefix
            history_text = "HISTORY:\n" + "\n".join(history_entries)
            
            # Update the description field in gpkg_contents
            cursor.execute(
                "UPDATE gpkg_contents SET description = ? WHERE table_name = ?",
                (history_text, layer_name)
            )
            
            rows_affected = cursor.rowcount
            conn.commit()
            conn.close()
            
            if rows_affected > 0:
                if results:
                    results['warnings'].append(
                        f"✓ Wrote {len(history_entries)} history entries for raster '{layer_name}'"
                    )
                    results['warnings'].append(
                        f"  Note: Raster history is in Layer Properties → Information → DESCRIPTION field"
                    )
                return True
            else:
                if results:
                    results['warnings'].append(
                        f"No rows updated when writing history for raster '{layer_name}'"
                    )
                return False
        
        except Exception as e:
            if results:
                results['errors'].append(f"Error writing raster history to geopackage: {str(e)}")
            print(f"Error writing raster history: {e}")
            import traceback
            traceback.print_exc()
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
            str: History entry in format "Updated;YYYY-MM-DD@HH-MM-SS;User;username;Source;path;DateModified;file_date"
        """
        timestamp = datetime.now().strftime("%Y-%m-%d@%H-%M-%S")
        source_path = source_layer.source()
        user = os.getenv('USERNAME') or os.getenv('USER') or 'UnknownUser'
        
        # Get the file modified date from the source file
        file_modified_date = "Unknown"
        try:
            # Extract the actual file path from the source
            # Handle cases like "C:/path/to/file.shp" or "C:/path/to/file.gpkg|layername=layer"
            file_path = source_path.split('|')[0]  # Remove any layername parameter
            
            if os.path.exists(file_path):
                # Get the modification time and format it
                mtime = os.path.getmtime(file_path)
                file_modified_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d@%H-%M-%S")
        except Exception as e:
            print(f"Could not get file modified date: {e}")
            file_modified_date = "Unknown"
        
        # Format the history entry to include all details
        return f"Updated;{timestamp};User;{user};DateModified;{file_modified_date};Source;{source_path}"
    
    @staticmethod
    def _should_update_layer(
        source_layer: QgsVectorLayer,
        gpkg_path: str,
        results: dict = None
    ) -> bool:
        """
        Determine if a layer should be updated based on modification dates.
        
        Args:
            source_layer: The layer from the active project
            gpkg_path: Path to the geopackage
            results: Optional results dict for messages
        
        Returns:
            bool: True if layer should be updated, False if it can be skipped
        """
        try:
            # Get the source file's modification date
            source_path = source_layer.source().split('|')[0]
            
            if not os.path.exists(source_path):
                if results:
                    results['warnings'].append(f"Cannot check modification date for '{source_layer.name()}': source file not found")
                return True  # Update anyway if we can't verify
            
            source_mtime = os.path.getmtime(source_path)
            source_date = datetime.fromtimestamp(source_mtime)
            
            if results:
                results['warnings'].append(f"Source file '{source_layer.name()}' modified: {source_date.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Get the existing history from the geopackage
            existing_history = PackageLayerUpdaterLogic._get_layer_history(gpkg_path, source_layer.name())
            
            if not existing_history:
                # No history = new layer, should update
                if results:
                    results['warnings'].append(f"Layer '{source_layer.name()}' has no history, will update")
                return True
            
            # Parse the most recent history entry
            latest_entry = existing_history[-1]  # Last entry is most recent
            parsed = PackageLayerUpdaterLogic._parse_history_entry(latest_entry)
            
            if not parsed or 'date_modified' not in parsed or parsed['date_modified'] is None:
                if results:
                    results['warnings'].append(f"Cannot parse history date for '{source_layer.name()}', will update")
                return True  # Update if we can't parse history
            
            # Get the history date
            history_date = parsed['date_modified']
            
            if results:
                results['warnings'].append(f"History date for '{source_layer.name()}': {history_date.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Compare modification dates with tolerance of 2 seconds (for filesystem precision)
            time_diff = (source_date - history_date).total_seconds()
            
            if results:
                results['warnings'].append(f"Time difference: {time_diff:.1f} seconds")
            
            if time_diff > 2.0:  # Source is more than 2 seconds newer
                if results:
                    results['warnings'].append(
                        f"✓ Layer '{source_layer.name()}' WILL UPDATE: "
                        f"source is {time_diff:.1f}s newer than history"
                    )
                return True
            else:
                if results:
                    results['warnings'].append(
                        f"⊘ Layer '{source_layer.name()}' WILL SKIP: "
                        f"source is not significantly newer (diff: {time_diff:.1f}s)"
                    )
                return False
        
        except Exception as e:
            if results:
                results['warnings'].append(f"Error checking if '{source_layer.name()}' should update: {str(e)}")
            print(f"Error in _should_update_layer: {e}")
            import traceback
            traceback.print_exc()
            return True  # Update anyway if there's an error

    @staticmethod
    def _parse_history_entry(history_entry: str) -> dict:
        """
        Parse a history entry string into a structured dictionary.
        
        Args:
            history_entry: History string in format "Updated;timestamp;User;username;DateModified;file_date;Source;path"
        
        Returns:
            dict: Parsed history with keys: action, timestamp, user, date_modified, source
                  Returns empty dict if parsing fails
        """
        try:
            # Split by semicolon
            parts = history_entry.split(';')
            
            if len(parts) < 8:  # Need at least: Updated, timestamp, User, username, DateModified, date, Source, path
                print(f"History entry has insufficient parts: {history_entry}")
                return {}
            
            parsed = {
                'action': parts[0].strip(),
                'timestamp': None,
                'user': None,
                'date_modified': None,
                'source': None
            }
            
            # Parse timestamp (parts[1])
            try:
                timestamp_str = parts[1].strip()
                parsed['timestamp'] = datetime.strptime(timestamp_str, "%Y-%m-%d@%H-%M-%S")
            except Exception as e:
                print(f"Could not parse timestamp '{parts[1]}': {e}")
            
            # Parse user (parts[3])
            if len(parts) > 3:
                parsed['user'] = parts[3].strip()
            
            # Parse date modified (parts[5])
            if len(parts) > 5:
                try:
                    date_modified_str = parts[5].strip()
                    if date_modified_str != "Unknown":
                        parsed['date_modified'] = datetime.strptime(date_modified_str, "%Y-%m-%d@%H-%M-%S")
                except Exception as e:
                    print(f"Could not parse date modified '{parts[5]}': {e}")
            
            # Parse source (parts[7])
            if len(parts) > 7:
                parsed['source'] = parts[7].strip()
            
            return parsed
        
        except Exception as e:
            print(f"Error parsing history entry: {e}")
            return {}

    @staticmethod
    def _check_and_fix_duplicate_fids(
        layer: QgsVectorLayer,
        fix_fids: bool,
        results: dict = None
    ) -> dict:
        """
        Check for duplicate FID values in a layer and optionally fix them.
        
        Args:
            layer: The vector layer to check
            fix_fids: Whether to fix duplicate FIDs
            results: Optional results dict for messages
        
        Returns:
            dict: Result with keys:
                - can_proceed: bool, whether the layer can be exported
                - fixed_count: int, number of FIDs that were fixed
                - message: str, description of what happened
        """
        result = {
            'can_proceed': True,
            'fixed_count': 0,
            'message': ''
        }
        
        try:
            # First, find the FID field index
            fid_field_idx = -1
            for idx, field in enumerate(layer.fields()):
                if field.name().lower() == 'fid':
                    fid_field_idx = idx
                    break
            
            if fid_field_idx < 0:
                # Try using the first primary key field
                fid_field_name = layer.dataProvider().primaryKeyAttributes()
                if fid_field_name and len(fid_field_name) > 0:
                    fid_field_idx = fid_field_name[0]
            
            if fid_field_idx < 0:
                result['can_proceed'] = False
                result['message'] = "Could not identify FID field in layer"
                return result
            
            # Get all features and their FID attribute values
            fid_map = {}  # Map FID attribute value to list of (feature, feature_index) tuples
            
            for idx, feature in enumerate(layer.getFeatures()):
                # Get the FID from the attribute field, NOT from feature.id()
                fid_value = feature.attribute(fid_field_idx)
                
                if fid_value not in fid_map:
                    fid_map[fid_value] = []
                fid_map[fid_value].append((feature, idx))
            
            # Find duplicate FID values
            duplicates = {fid: feat_list for fid, feat_list in fid_map.items() if len(feat_list) > 1}
            
            if not duplicates:
                result['message'] = 'No duplicate FIDs found'
                return result
            
            total_duplicates = sum(len(feat_list) - 1 for feat_list in duplicates.values())
            
            if not fix_fids:
                # Don't fix - warn and prevent export
                result['can_proceed'] = False
                result['message'] = (
                    f"Layer has {total_duplicates} duplicate FID(s). "
                    f"Enable 'Fix Duplicate FIDs' option to automatically fix, "
                    f"or manually fix the FIDs in your source data. "
                    f"Geopackages require unique FIDs."
                )
                if results:
                    results['warnings'].append(
                        f"⚠ Found {len(duplicates)} duplicate FID value(s) in '{layer.name()}' "
                        f"(total {total_duplicates} duplicate rows)"
                    )
                return result
            
            # Fix the duplicates by renumbering later rows
            if results:
                results['warnings'].append(
                    f"Fixing {total_duplicates} duplicate FID(s) in '{layer.name()}'..."
                )
            
            # Find the maximum FID value to start new numbering from
            max_fid = max(fid_map.keys())
            next_available_fid = max_fid + 1
            
            # Check if layer supports editing
            if not layer.dataProvider().capabilities() & layer.dataProvider().ChangeAttributeValues:
                result['can_proceed'] = False
                result['message'] = f"Layer provider does not support changing attribute values"
                return result
            
            # Start editing
            if not layer.startEditing():
                result['can_proceed'] = False
                result['message'] = "Could not start editing session on layer"
                return result
            
            fixed_count = 0
            
            # For each FID value with duplicates, renumber all but the first occurrence
            for fid_value, feat_list in duplicates.items():
                # Keep the first occurrence, renumber the rest
                for feature, feature_idx in feat_list[1:]:
                    # Change the FID attribute value using QGIS feature ID
                    if layer.changeAttributeValue(feature.id(), fid_field_idx, next_available_fid):
                        fixed_count += 1
                        next_available_fid += 1
            
            # Commit changes
            if layer.commitChanges():
                result['fixed_count'] = fixed_count
                result['message'] = f'Fixed {fixed_count} duplicate FID(s)'
                
                if results:
                    results['warnings'].append(
                        f"✓ Successfully fixed {fixed_count} duplicate FID(s) in '{layer.name()}'"
                    )
            else:
                # Get commit errors
                commit_errors = layer.commitErrors()
                
                # Rollback on failure
                layer.rollBack()
                result['can_proceed'] = False
                result['message'] = f'Failed to commit FID fixes: {", ".join(commit_errors)}'
                
                if results:
                    results['warnings'].append(
                        f"✗ Failed to commit FID fixes for '{layer.name()}': {', '.join(commit_errors)}"
                    )
            
            return result
        
        except Exception as e:
            # Ensure we rollback on exception
            try:
                if layer.isEditable():
                    layer.rollBack()
            except Exception:
                pass
            
            result['can_proceed'] = False
            result['message'] = f'Exception checking/fixing FIDs: {str(e)}'
            
            if results:
                results['warnings'].append(
                    f"✗ Error checking/fixing FIDs for '{layer.name()}': {str(e)}"
                )
            
            print(f"Error checking/fixing FIDs: {e}")
            import traceback
            traceback.print_exc()
            
            return result
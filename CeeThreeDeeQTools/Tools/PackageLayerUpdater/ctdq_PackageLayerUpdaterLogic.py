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
            target_geopackages: List of geopackage file paths to update (absolute paths)
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
            'layers_not_found': 0,
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
        
        total_steps = len(target_geopackages)
        current_step = 0
        
        # Track which layers were never found in any geopackage
        layers_found_tracker = {layer.name(): False for layer in layers_to_export}
        
        # Helper to get display-friendly path (relative if possible)
        def get_display_path(abs_path):
            try:
                project_path = project.fileName()
                if project_path:
                    project_dir = os.path.dirname(project_path)
                    rel_path = os.path.relpath(abs_path, project_dir)
                    if not rel_path.startswith('..'):
                        return rel_path
                return os.path.basename(abs_path)  # Fallback to basename
            except Exception:
                return os.path.basename(abs_path)
        
        # Process each geopackage
        for gpkg_idx, gpkg_path in enumerate(target_geopackages):
            try:
                current_step = gpkg_idx
                
                # Get display-friendly path for progress messages
                display_path = get_display_path(gpkg_path)
                
                if progress_callback:
                    progress_callback(
                        f"Processing geopackage {gpkg_idx + 1}/{len(target_geopackages)}: {display_path}", 
                        int((current_step / total_steps) * 100)
                    )
                
                if not os.path.exists(gpkg_path):
                    results['errors'].append(f"Geopackage not found: {display_path}")
                    continue
                
                gpkg_modified = False
                
                # Get list of layers in the geopackage
                gpkg_layers = PackageLayerUpdaterLogic._get_geopackage_layers(gpkg_path)
                
                if not gpkg_layers:
                    results['warnings'].append(f"No layers found in geopackage: {display_path}")
                    continue
                
                # Update each matching layer
                for layer in layers_to_export:
                    try:
                        # Check if layer name exists in geopackage
                        if layer.name() in gpkg_layers:
                            # Mark this layer as found
                            layers_found_tracker[layer.name()] = True
                            
                            # Check if we should skip this layer based on modification date
                            if update_new_only:
                                should_update = PackageLayerUpdaterLogic._should_update_layer(
                                    layer, gpkg_path, results
                                )
                                if not should_update:
                                    results['layers_skipped'] += 1
                                    results['warnings'].append(
                                        f"⊘ Skipped '{layer.name()}' in {display_path} (not modified since last update)"
                                    )
                                    continue
                        
                            # ALWAYS check for FID problems before updating (only for vector layers)
                            from qgis.core import QgsMapLayer
                            if layer.type() == QgsMapLayer.VectorLayer:
                                fid_check = PackageLayerUpdaterLogic._check_and_fix_duplicate_fids(
                                    layer, fix_fids, results
                                )
                                
                                # If FID check fails, ALWAYS skip the layer
                                if not fid_check['can_proceed']:
                                    results['layers_skipped'] += 1
                                    results['warnings'].append(
                                        f"⊘ Skipped '{layer.name()}' in {display_path}: {fid_check['message']}"

                                    )
                                    continue
                                
                                # If FIDs were fixed, report it
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
                                    f"✓ Updated '{layer.name()}' in {display_path}"
                                )
                            else:
                                results['warnings'].append(
                                    f"✗ Failed to update '{layer.name()}' in {display_path}"
                                )
                    
                    except Exception as layer_error:
                        results['errors'].append(
                            f"Error updating layer '{layer.name()}' in {display_path}: {str(layer_error)}"
                        )
                
                if gpkg_modified:
                    results['geopackages_updated'] += 1
            
            except Exception as gpkg_error:
                results['errors'].append(f"Error processing geopackage {get_display_path(gpkg_path)}: {str(gpkg_error)}")
        
        # Final progress update
        if progress_callback:
            progress_callback(
                f"Completed processing {len(target_geopackages)} geopackage(s)", 
                100
            )
        
        # After all geopackages, check which layers were never found
        layers_not_found = [name for name, found in layers_found_tracker.items() if not found]
        if layers_not_found:
            results['layers_not_found'] = len(layers_not_found)
            results['warnings'].append(
                f"⚠ {len(layers_not_found)} layer(s) not found in any geopackage: {', '.join(layers_not_found)}"
            )
        
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
        Uses overwrite mode with retry logic to prevent data loss.
        
        Args:
            source_layer: The vector layer from the active project
            gpkg_path: Path to the geopackage
            results: Optional results dict for messages
        
        Returns:
            bool: True if successful
        """
        import time
        
        try:
            # Check if geopackage file is writable
            if not os.access(gpkg_path, os.W_OK):
                if results:
                    results['errors'].append(
                        f"Geopackage is read-only or locked: {os.path.basename(gpkg_path)}\n"
                        f"  Check if it's open in another application or if file permissions are read-only."
                    )
                return False
            
            # First, preserve the existing layer's metadata history from the geopackage
            existing_history = PackageLayerUpdaterLogic._get_layer_history(gpkg_path, source_layer.name())
            
            # Create new history entry
            new_history_entry = PackageLayerUpdaterLogic._create_history_entry(source_layer)
            
            # Combine existing history with new entry
            updated_history = existing_history + [new_history_entry] if existing_history else [new_history_entry]
            
            # Create metadata object with the updated history
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
            layer_metadata.setHistory(updated_history)
            
            # Prepare write options - use OVERWRITE mode (doesn't delete first!)
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = source_layer.name()
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer  # Overwrites without deleting
            options.layerMetadata = layer_metadata
            options.saveMetadata = True
            
            # Retry logic: attempt write up to 3 times with delays
            max_attempts = 3
            attempt = 0
            last_error = None
            
            while attempt < max_attempts:
                attempt += 1
                
                try:
                    # Small delay before each attempt (except first)
                    if attempt > 1:
                        time.sleep(0.5 * attempt)  # 0.5s, 1.0s, 1.5s
                        if results:
                            results['warnings'].append(
                                f"  Retry attempt {attempt}/{max_attempts} for '{source_layer.name()}'..."
                            )
                    
                    # Try to write
                    error = QgsVectorFileWriter.writeAsVectorFormatV3(
                        source_layer,
                        gpkg_path,
                        QgsCoordinateTransformContext(),
                        options
                    )
                    
                    if error[0] == QgsVectorFileWriter.NoError:
                        # Success! Verify the result
                        time.sleep(0.15)  # Brief delay for filesystem
                        
                        # Verify feature count
                        uri = f"{gpkg_path}|layername={source_layer.name()}"
                        check_layer = QgsVectorLayer(uri, "check", "ogr")
                        
                        if check_layer.isValid():
                            source_count = source_layer.featureCount()
                            gpkg_count = check_layer.featureCount()
                            
                            if source_count != gpkg_count:
                                if results:
                                    results['warnings'].append(
                                        f"⚠ Feature count mismatch for '{source_layer.name()}': "
                                        f"source has {source_count}, geopackage has {gpkg_count}"
                                    )
                        
                        return True  # Success!
                    
                    else:
                        last_error = error[1]
                        # Check if it's a lock/readonly error that might resolve with retry
                        if "readonly" in last_error.lower() or "locked" in last_error.lower():
                            if attempt < max_attempts:
                                continue  # Retry
                        else:
                            # Other error - don't retry
                            break
                
                except Exception as e:
                    last_error = str(e)
                    if attempt < max_attempts:
                        continue  # Retry
                    else:
                        break
            
            # All attempts failed
            if results:
                error_msg = last_error or "Unknown error"
                if "readonly" in error_msg.lower() or "locked" in error_msg.lower():
                    results['errors'].append(
                        f"Cannot write to geopackage (locked or read-only after {max_attempts} attempts): {os.path.basename(gpkg_path)}\n"
                        f"  Layer: '{source_layer.name()}'\n"
                        f"  Close the geopackage in other applications or check file permissions.\n"
                        f"  Error: {error_msg}"
                    )
                else:
                    results['errors'].append(
                        f"Error writing vector layer '{source_layer.name()}' to geopackage (after {max_attempts} attempts): {error_msg}"
                    )
            
            return False
        
        except sqlite3.OperationalError as e:
            if results:
                results['errors'].append(
                    f"SQLite error for '{source_layer.name()}': {str(e)}\n"
                    f"  Geopackage: {os.path.basename(gpkg_path)}\n"
                    f"  The file may be locked or corrupted."
                )
            print(f"SQLite error updating vector layer: {e}")
            return False
        
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
        """
        try:
            conn = sqlite3.connect(gpkg_path)
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT table_name FROM gpkg_contents WHERE table_name = ?",
                (layer_name,)
            )
            existing_row = cursor.fetchone()
            
            if not existing_row:
                cursor.execute(
                    "SELECT table_name FROM gpkg_contents WHERE table_name LIKE ?",
                    (f"%{layer_name}%",)
                )
                like_matches = cursor.fetchall()
                
                if like_matches:
                    layer_name = like_matches[0][0]
                else:
                    conn.close()
                    return False
            
            history_text = "HISTORY:\n" + "\n".join(history_entries)
            
            cursor.execute(
                "UPDATE gpkg_contents SET description = ? WHERE table_name = ?",
                (history_text, layer_name)
            )
            
            rows_affected = cursor.rowcount
            conn.commit()
            conn.close()
            
            return rows_affected > 0
        
        except Exception as e:
            if results:
                results['errors'].append(f"Error writing raster history to geopackage: {str(e)}")
            print(f"Error writing raster history: {e}")
            return False

    @staticmethod
    def _get_layer_history(gpkg_path: str, layer_name: str) -> list:
        """Get the existing history from a layer's metadata in the geopackage."""
        try:
            uri = f"{gpkg_path}|layername={layer_name}"
            layer = QgsVectorLayer(uri, layer_name, "ogr")
            
            if layer.isValid():
                metadata = layer.metadata()
                history_list = metadata.history()
                if history_list:
                    return history_list
            
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
                    return history_list
            
            return []
        
        except Exception as e:
            print(f"Error reading layer history: {e}")
            return []

    @staticmethod
    def _create_history_entry(source_layer) -> str:
        """Create a history entry string for the layer update."""
        timestamp = datetime.now().strftime("%Y-%m-%d@%H-%M-%S")
        source_path = source_layer.source()
        user = os.getenv('USERNAME') or os.getenv('USER') or 'UnknownUser'
        
        file_modified_date = "Unknown"
        try:
            file_path = source_path.split('|')[0]
            if os.path.exists(file_path):
                mtime = os.path.getmtime(file_path)
                file_modified_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d@%H-%M-%S")
        except Exception:
            pass
        
        return f"Updated;{timestamp};User;{user};DateModified;{file_modified_date};Source;{source_path}"
    
    @staticmethod
    def _should_update_layer(
        source_layer,
        gpkg_path: str,
        results: dict = None
    ) -> bool:
        """Determine if a layer should be updated based on modification dates."""
        try:
            source_path = source_layer.source().split('|')[0]
            
            if not os.path.exists(source_path):
                return True
            
            source_mtime = os.path.getmtime(source_path)
            source_date = datetime.fromtimestamp(source_mtime)
            
            existing_history = PackageLayerUpdaterLogic._get_layer_history(gpkg_path, source_layer.name())
            
            if not existing_history:
                return True
            
            latest_entry = existing_history[-1]
            parsed = PackageLayerUpdaterLogic._parse_history_entry(latest_entry)
            
            if not parsed or 'date_modified' not in parsed or parsed['date_modified'] is None:
                return True
            
            history_date = parsed['date_modified']
            time_diff = (source_date - history_date).total_seconds()
            
            return time_diff > 2.0
        
        except Exception:
            return True

    @staticmethod
    def _parse_history_entry(history_entry: str) -> dict:
        """Parse a history entry string into a structured dictionary."""
        try:
            parts = history_entry.split(';')
            
            if len(parts) < 8:
                return {}
            
            parsed = {
                'action': parts[0].strip(),
                'timestamp': None,
                'user': None,
                'date_modified': None,
                'source': None
            }
            
            try:
                timestamp_str = parts[1].strip()
                parsed['timestamp'] = datetime.strptime(timestamp_str, "%Y-%m-%d@%H-%M-%S")
            except Exception:
                pass
            
            if len(parts) > 3:
                parsed['user'] = parts[3].strip()
            
            if len(parts) > 5:
                try:
                    date_modified_str = parts[5].strip()
                    if date_modified_str != "Unknown":
                        parsed['date_modified'] = datetime.strptime(date_modified_str, "%Y-%m-%d@%H-%M-%S")
                except Exception:
                    pass
            
            if len(parts) > 7:
                parsed['source'] = parts[7].strip()
            
            return parsed
        
        except Exception:
            return {}

    @staticmethod
    def _check_and_fix_duplicate_fids(
        layer: QgsVectorLayer,
        fix_fids: bool,
        results: dict = None
    ) -> dict:
        """
        Check for FID validity issues in a layer and optionally fix them.
        Always checks for problems. Only attempts fixes if fix_fids is True.
        
        Args:
            layer: The vector layer to check
            fix_fids: Whether to attempt to fix FID problems
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
            # ALWAYS try to find the FID field (case-insensitive check!)
            fid_field_idx = -1
            fid_field_name = None
            for idx, field in enumerate(layer.fields()):
                if field.name().upper() == 'FID':  # Changed to uppercase comparison
                    fid_field_idx = idx
                    fid_field_name = field.name()  # Store actual field name
                    break
            
            if fid_field_idx < 0:
                try:
                    if hasattr(layer.dataProvider(), 'primaryKeyAttributes'):
                        fid_field_attrs = layer.dataProvider().primaryKeyAttributes()
                        if fid_field_attrs and len(fid_field_attrs) > 0:
                            fid_field_idx = fid_field_attrs[0]
                            fid_field_name = layer.fields()[fid_field_idx].name()
                except Exception:
                    pass
            
            if fid_field_idx < 0:
                # No FID field - this is normal for shapefiles/CSVs without FID
                # Geopackage will create its own FID during import
                result['message'] = 'No FID field found (normal for shapefiles/CSVs)'
                return result
            
            # Found an FID field - log which one
            #if results:
            #    results['warnings'].append(
            #        f"Found FID field in '{layer.name()}': '{fid_field_name}' at index {fid_field_idx}"
            #    )
            
            # ALWAYS check for NULL values and duplicates
            fid_map = {}
            invalid_fid_features = []  # Track features with invalid FIDs (NULL, non-integer, etc.)
            
            for idx, feature in enumerate(layer.getFeatures()):
                fid_value = feature.attribute(fid_field_idx)
                
                # Check if FID is a valid integer
                # This catches: None, empty strings, non-numeric strings, floats, etc.
                is_valid_int = False
                try:
                    if fid_value is not None and fid_value != '':
                        # Try to convert to int and check it's equal (catches floats like 1.5)
                        int_value = int(fid_value)
                        # Also check that converting to int didn't change the value (e.g., 1.5 -> 1)
                        if isinstance(fid_value, int) or (isinstance(fid_value, (float, str)) and float(fid_value) == int_value):
                            is_valid_int = True
                            fid_value = int_value  # Normalize to integer
                except (ValueError, TypeError):
                    pass  # Invalid - will be caught below
                
                if not is_valid_int:
                    invalid_fid_features.append((feature, idx))
                    continue  # Skip adding invalid FIDs to fid_map
                
                if fid_value not in fid_map:
                    fid_map[fid_value] = []
                fid_map[fid_value].append((feature, idx))
            
            # Find duplicate FID values (excluding invalid FIDs)
            duplicates = {fid: feat_list for fid, feat_list in fid_map.items() if len(feat_list) > 1}
            
            invalid_count = len(invalid_fid_features)
            
            # If no problems, we're done
            if not duplicates and invalid_count == 0:
                result['message'] = 'No FID problems found'
                if results:
                    results['warnings'].append(f"✓ No FID problems in '{layer.name()}'")
                return result
            
            # Problems found - report them
            if invalid_count > 0 and results:
                results['warnings'].append(
                    f"⚠ Found {invalid_count} invalid FID value(s) in '{layer.name()}' (field: '{fid_field_name}')"
                )
            
            if duplicates and results:
                total_duplicates = sum(len(feat_list) - 1 for feat_list in duplicates.values())
                results['warnings'].append(
                    f"⚠ Found {len(duplicates)} duplicate FID value(s) in '{layer.name()}' "
                    f"(total {total_duplicates} duplicate rows, field: '{fid_field_name}')"
                )
            
            # If not fixing, BLOCK the export
            if not fix_fids:
                total_duplicates = sum(len(feat_list) - 1 for feat_list in duplicates.values()) if duplicates else 0
                problems = []
                if invalid_count > 0:
                    problems.append(f"{invalid_count} invalid FID(s)")
                if duplicates:
                    problems.append(f"{total_duplicates} duplicate FID(s)")
                
                result['can_proceed'] = False
                result['message'] = (
                    f"Layer has {' and '.join(problems)} in field '{fid_field_name}'. "
                    f"Enable 'Fix Invalid FIDs' option to automatically fix, "
                    f"or manually fix the FIDs in your source data. "
                    f"Geopackages require unique, positive integer FID values."
                )
                return result
            
            # Attempt to fix the problems by renumbering
            if results:
                problems = []
                if invalid_count > 0:
                    problems.append(f"{invalid_count} invalid")
                if duplicates:
                    total_duplicates = sum(len(feat_list) - 1 for feat_list in duplicates.values())
                    problems.append(f"{total_duplicates} duplicate")
                results['warnings'].append(
                    f"Attempting to fix {' and '.join(problems)} FID(s) in '{layer.name()}' (field: '{fid_field_name}')..."
                )
            
            # Find the maximum FID value to start new numbering from
            max_fid = max(fid_map.keys()) if fid_map else 0
            next_available_fid = max(max_fid + 1, 1)  # Ensure we start at least from 1
            
            # Check if layer supports editing
            provider_caps = layer.dataProvider().capabilities()
            if not (provider_caps & layer.dataProvider().ChangeAttributeValues):
                result['can_proceed'] = False
                result['message'] = (
                    f"Cannot fix FIDs: Layer provider '{layer.dataProvider().name()}' does not support editing. "
                    f"Manually fix FIDs in source data or use a different data source."
                )
                if results:
                    results['warnings'].append(
                        f"⚠ Cannot edit '{layer.name()}' to fix FIDs (provider: {layer.dataProvider().name()})"
                    )
                return result
            
            if not layer.startEditing():
                result['can_proceed'] = False
                result['message'] = "Could not start editing session to fix FIDs"
                return result
            
            fixed_count = 0
            
            # Fix invalid FIDs first
            for feature, feature_idx in invalid_fid_features:
                if layer.changeAttributeValue(feature.id(), fid_field_idx, next_available_fid):
                    fixed_count += 1
                    next_available_fid += 1
            
            # Fix duplicates (renumber all but the first occurrence)
            for fid_value, feat_list in duplicates.items():
                for feature, feature_idx in feat_list[1:]:
                    if layer.changeAttributeValue(feature.id(), fid_field_idx, next_available_fid):
                        fixed_count += 1
                        next_available_fid += 1
            
            # Commit the fixes
            if layer.commitChanges():
                result['fixed_count'] = fixed_count
                result['message'] = f'Fixed {fixed_count} FID problem(s) in field \'{fid_field_name}\''

                if results:
                    results['warnings'].append(
                        f"✓ Fixed {fixed_count} FID problem(s) in '{layer.name()}' (field: '{fid_field_name}')"
                    )
            else:
                commit_errors = layer.commitErrors()
                layer.rollBack()
                result['can_proceed'] = False
                result['message'] = (
                    f"Failed to save FID fixes: {', '.join(commit_errors)}. "
                    f"Manually fix FIDs in source data."
                )
                
                if results:
                    results['warnings'].append(
                        f"✗ Failed to commit FID fixes for '{layer.name()}': {', '.join(commit_errors)}"
                    )
            
            return result

        except Exception as e:
            try:
                if layer.isEditable():
                    layer.rollBack()
            except Exception:
                pass
            
            result['can_proceed'] = False
            result['message'] = f'Error checking FIDs: {str(e)}. Manually fix FIDs in source data.'
            
            if results:
                results['warnings'].append(
                    f"✗ Error checking/fixing FIDs for '{layer.name()}': {str(e)}"
                )
            
            print(f"Error checking/fixing FIDs: {e}")
            import traceback
            traceback.print_exc()
            
            return result

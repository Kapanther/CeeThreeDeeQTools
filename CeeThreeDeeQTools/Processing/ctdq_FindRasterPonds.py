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

from typing import Any, Optional

from qgis.core import (    
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFileDestination,
    QgsProject,
    QgsLayerTreeModel,
    QgsMapLayer,
    Qgis,
    QgsVectorLayerSimpleLabeling,
    QgsRuleBasedLabeling,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsFeature,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterVectorDestination,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterString,
    QgsVectorFileWriter
)
import xml.etree.ElementTree as ET
from xml.dom.minidom import parseString
from ..ctdq_support import ctdprocessing_info
import heapq
import numpy as np
import processing
import os

class FindRasterPonds(QgsProcessingAlgorithm):
    # class-level imports removed; use module-level imports

    class PriorityQueue:
        def __init__(self):
            self.elements = []

        def empty(self):
            return not self.elements

        def put(self, item, priority):
            heapq.heappush(self.elements, (priority, item))

        def get(self):
            return heapq.heappop(self.elements)[1]
    TOOL_NAME = "FindRasterPonds"
    """
    QGIS Processing Algorithm to detect ponds (sinks) in a raster and output a vector layer with polygons representing the ponds. 
    Also computes statistics regarding the ponds like maximum and minimum elevation (RLmax, RLmin), pond volume (PONDvolume), 
    and depth statistics (DEPTH_sum, DEPTH_mean, DEPTH_max).
    """

    MIN_DEPTH = "MIN_DEPTH"
    MIN_AREA = "MIN_AREA"
    INPUT_RASTER = "INPUT_RASTER"
    OUTPUT_VECTOR = "OUTPUT_VECTOR"
    OUTPUT_FILLED_RASTER = "OUTPUT_FILLED_RASTER"
    OUTPUT_POND_DEPTH_RASTER = "OUTPUT_POND_DEPTH_RASTER"
    OUTPUT_POND_DEPTH_RASTER_VALID = "OUTPUT_POND_DEPTH_RASTER_VALID"    

    def name(self):
        return self.TOOL_NAME

    def displayName(self):
        return ctdprocessing_info[self.TOOL_NAME]["disp"]

    def group(self):
        return ctdprocessing_info[self.TOOL_NAME]["group"]

    def groupId(self):
        return ctdprocessing_info[self.TOOL_NAME]["group_id"]

    def shortHelpString(self) -> str:
        return ctdprocessing_info[self.TOOL_NAME]["shortHelp"]

    def initAlgorithm(self, config: Optional[dict[str, Any]] = None):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """       
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                "GROUND_RASTER",
                "Ground Raster",
                optional=False
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                "MIN_DEPTH",
                "Minimum Pond Depth",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.5,
                optional=False
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                "MIN_AREA",
                "Minimum Pond Area (in square units of the CRS)",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=500.0,
                optional=False
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
                "OUTPUT_POND_OUTLINES",
                "Output Pond Outlines Vector",                
                optional=False,
                fileFilter="ESRI Shapefile (*.shp)",
                createByDefault=True                
            )
        )

        # Move OPEN_OUTLINES_AFTER_RUN to the end of the parameter list
        self.addParameter(
            QgsProcessingParameterBoolean(
                "OPEN_OUTLINES_AFTER_RUN",
                "Open output file after running algorithm",
                defaultValue=True,
                optional=True               
            )
        )

        # Option to generalize (smooth) pond outlines after detection
        self.addParameter(
            QgsProcessingParameterBoolean(
                "GENERALIZE_OUTLINES",
                "Generalize (smooth) pond outlines after detection",
                defaultValue=True,
                optional=True
            )
        )

        # Advanced panel for output rasters
        self.addParameter(QgsProcessingParameterRasterDestination(
            "OUTPUT_FILLED_RASTER",
            "Output Filled Raster",
            optional=True,
            createByDefault=False  # Do not add to viewer by default
        ))

        self.addParameter(QgsProcessingParameterRasterDestination(
            "OUTPUT_POND_DEPTH_RASTER",
            "Output Pond Depth Raster",
            optional=True,
            createByDefault=False  # Do not add to viewer by default
        ))

        self.addParameter(QgsProcessingParameterRasterDestination(
            "OUTPUT_POND_DEPTH_RASTER_VALID",
            "Output Pond Depth Raster (Valid)",
            optional=True,
            createByDefault=False  # Do not add to viewer by default
        ))

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:      

        # Get input raster and output path
        input_raster = self.parameterAsRasterLayer(parameters, "GROUND_RASTER", context)
        output_raster_path = self.parameterAsOutputLayer(parameters, "OUTPUT_FILLED_RASTER", context)
        output_pond_depth_raster_path = self.parameterAsOutputLayer(parameters, "OUTPUT_POND_DEPTH_RASTER", context)
        output_pond_depth_raster_valid_path = self.parameterAsOutputLayer(parameters, "OUTPUT_POND_DEPTH_RASTER_VALID", context)
        pond_outline_output_path = self.parameterAsOutputLayer(parameters, "OUTPUT_POND_OUTLINES", context)
        # If optional outputs weren't provided, write to temp files to avoid empty-path errors
        import tempfile, uuid
        if not output_raster_path:
            output_raster_path = os.path.join(tempfile.gettempdir(), f"OUTPUT_FILLED_RASTER_{uuid.uuid4().hex}.tif")
            feedback.pushInfo(f"No OUTPUT_FILLED_RASTER provided; using temporary path: {output_raster_path}")
        if not output_pond_depth_raster_path:
            output_pond_depth_raster_path = os.path.join(tempfile.gettempdir(), f"OUTPUT_POND_DEPTH_RASTER_{uuid.uuid4().hex}.tif")
            feedback.pushInfo(f"No OUTPUT_POND_DEPTH_RASTER provided; using temporary path: {output_pond_depth_raster_path}")
        if not output_pond_depth_raster_valid_path:
            output_pond_depth_raster_valid_path = os.path.join(tempfile.gettempdir(), f"OUTPUT_POND_DEPTH_RASTER_VALID_{uuid.uuid4().hex}.tif")
            feedback.pushInfo(f"No OUTPUT_POND_DEPTH_RASTER_VALID provided; using temporary path: {output_pond_depth_raster_valid_path}")
        # Ensure pond outlines vector output path ends with .shp
        if pond_outline_output_path.lower().endswith('.gpkg'):
            pond_outline_output_path = pond_outline_output_path[:-5] + '.shp'
        if not pond_outline_output_path.lower().endswith('.shp'):
            pond_outline_output_path += '.shp'
        # Log paths for debugging
        feedback.pushInfo(f"Input raster: {input_raster.name()}")
        feedback.pushInfo(f"Output raster path: {output_raster_path}")
        feedback.pushInfo(f"Output pond depth raster path: {output_pond_depth_raster_path}")
        feedback.pushInfo(f"Output valid pond depth raster path: {output_pond_depth_raster_valid_path}")
        feedback.pushInfo(f"Output pond outlines path: {pond_outline_output_path}")
        # initialize progress
        try:
            feedback.setProgress(0)
        except Exception:
            # some feedback implementations may not support setProgress
            pass

        # Get raster properties
        provider = input_raster.dataProvider()
        extent = input_raster.extent()
        width = input_raster.width()
        height = input_raster.height()
        no_data_value = provider.sourceNoDataValue(1)

        # Read raster into a numpy array with shape (height, width).
        # Prefer GDAL ReadAsArray (preserves row/col ordering); if that fails, fall back to provider.block.
        dem = np.zeros((height, width), dtype=np.float32)
        read_ok = False
        src_path = provider.dataSourceUri()
        try:
            from osgeo import gdal
            ds_in = gdal.Open(src_path)
            if ds_in is not None:
                band = ds_in.GetRasterBand(1)
                arr = band.ReadAsArray()
                if arr is not None:
                    feedback.pushInfo(f"GDAL ReadAsArray shape: {arr.shape}")
                    # Expect (rows, cols) == (height, width)
                    if arr.shape == (height, width):
                        dem = arr.astype(np.float32)
                        nd = band.GetNoDataValue()
                        if nd is not None:
                            dem[dem == nd] = no_data_value
                        read_ok = True
                    else:
                        feedback.pushInfo(f"GDAL array shape {arr.shape} does not match expected (height,width)=({height},{width}). Will fallback to provider.block().")
                ds_in = None
        except Exception as e:
            feedback.pushInfo(f"GDAL ReadAsArray failed: {e}; falling back to provider.block()")

        if not read_ok:
            feedback.pushInfo("Using provider.block fallback to build numpy DEM (slower)")
            block = provider.block(1, extent, width, height)
            # update progress every few rows to keep UI responsive
            row_update = max(1, height // 50)
            for y in range(height):
                if feedback.isCanceled():
                    feedback.pushInfo("Processing canceled during raster read.")
                    return {}
                for x in range(width):
                    try:
                        value = block.value(x, y)
                    except Exception:
                        # Defensive: if block.value misbehaves, set nodata
                        value = None
                    dem[y, x] = float(value) if value is not None else -9999
                if (y % row_update) == 0:
                    try:
                        pct = int(5 + (y / float(height)) * 10)
                        feedback.setProgress(pct)
                    except Exception:
                        pass
        feedback.pushInfo(f"dem array shape after read: {dem.shape}, dtype: {dem.dtype}")

        # Initialize priority queue and visited mask (row=y, col=x)
        pq = self.PriorityQueue()
        visited = np.zeros((height, width), dtype=bool)
        # add top and bottom rows
        for x in range(width):
            if dem[0, x] != no_data_value:
                pq.put((0, x), dem[0, x])
                visited[0, x] = True
            if dem[height - 1, x] != no_data_value:
                pq.put((height - 1, x), dem[height - 1, x])
                visited[height - 1, x] = True
        # add left and right columns
        for y in range(1, height - 1):
            if dem[y, 0] != no_data_value:
                pq.put((y, 0), dem[y, 0])
                visited[y, 0] = True
            if dem[y, width - 1] != no_data_value:
                pq.put((y, width - 1), dem[y, width - 1])
                visited[y, width - 1] = True

        # Main loop: process cells from the priority queue (row=y, col=x)
        filled_dem = dem.copy()
        directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]  # (dy, dx)
        # We'll track progress by processed nodes vs total cells as an estimate
        total_cells = float(max(1, height * width))
        processed = 0
        update_step = max(1, int(total_cells // 200))
        while not pq.empty():
            if feedback.isCanceled():
                feedback.pushInfo("Processing canceled during sink-fill step.")
                return {}
            y, x = pq.get()
            processed += 1
            for dy, dx in directions:
                ny, nx = y + dy, x + dx
                if 0 <= ny < height and 0 <= nx < width:
                    if not visited[ny, nx] and dem[ny, nx] != no_data_value:
                        if filled_dem[ny, nx] < filled_dem[y, x]:
                            filled_dem[ny, nx] = filled_dem[y, x]
                        pq.put((ny, nx), filled_dem[ny, nx])
                        visited[ny, nx] = True
            if (processed % update_step) == 0:
                try:
                    pct = int(15 + (processed / total_cells) * 35)
                    feedback.setProgress(min(90, pct))
                except Exception:
                    pass

        # Ensure output directory exists
        output_dir = os.path.dirname(output_raster_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        # Write filled raster to disk using GDAL
        from osgeo import gdal
        driver = gdal.GetDriverByName('GTiff')

        # Try to preserve the source raster's exact GDAL geotransform and projection
        geotransform = None
        proj_wkt = None
        try:
            src_path = input_raster.dataProvider().dataSourceUri()
            ds_in = gdal.Open(src_path)
            if ds_in is not None:
                gt = ds_in.GetGeoTransform()
                if gt is not None:
                    geotransform = gt
                pw = ds_in.GetProjection()
                if pw:
                    proj_wkt = pw
                ds_in = None
        except Exception as e:
            feedback.pushInfo(f"Could not open source with GDAL to read geotransform/projection: {e}")

        # Fallback: compute a standard north-up geotransform using extent and pixel sizes
        if geotransform is None:
            extent = input_raster.extent()
            geotransform = (
                extent.xMinimum(),
                input_raster.rasterUnitsPerPixelX(),
                0,
                extent.yMaximum(),
                0,
                -input_raster.rasterUnitsPerPixelY()
            )
            feedback.pushInfo("Using computed north-up geotransform (source geotransform not available).")
        else:
            feedback.pushInfo(f"Using source GDAL geotransform: {geotransform}")

        if not proj_wkt:
            proj_wkt = input_raster.crs().toWkt()

        out_raster = driver.Create(output_raster_path, width, height, 1, gdal.GDT_Float32)
        out_raster.SetGeoTransform(geotransform)
        out_raster.SetProjection(proj_wkt)
        out_band = out_raster.GetRasterBand(1)
        # Prepare filled_dem for writing and add diagnostics
        try:
            arr = np.ascontiguousarray(filled_dem.astype(np.float32))
        except Exception as e:
            feedback.reportError(f"Failed to prepare filled_dem array for writing: {e}")
            out_raster = None
            return {}
        feedback.pushInfo(f"filled_dem array shape: {arr.shape}, dtype: {arr.dtype}")
        try:
            xs = out_raster.RasterXSize
            ys = out_raster.RasterYSize
            feedback.pushInfo(f"GDAL out_raster size: xsize={xs}, ysize={ys}")
        except Exception:
            feedback.pushInfo("Could not read out_raster size for logging")
        # GDAL expects (rows, cols) == (height, width)
        if arr.shape != (height, width):
            feedback.reportError(f"filled_dem shape {arr.shape} does not match expected (height,width)=({height},{width}). Aborting write.")
            out_raster = None
            return {}
        try:
            out_band.WriteArray(arr)
        except Exception as e:
            feedback.reportError(f"Failed to WriteArray for filled raster: {e}; arr.shape={arr.shape}; expected (height,width)=({height},{width})")
            out_raster = None
            return {}
        out_band.SetNoDataValue(no_data_value)
        out_band.FlushCache()
        out_band.SetNoDataValue(no_data_value)
        out_band.FlushCache()
        # Readback verification: open written file and compare
        try:
            ds_check = gdal.Open(output_raster_path)
            if ds_check is not None:
                band_check = ds_check.GetRasterBand(1)
                arr_check = band_check.ReadAsArray()
                gt_check = ds_check.GetGeoTransform()
                feedback.pushInfo(f"Written raster readback shape: {arr_check.shape}, dtype: {arr_check.dtype}")
                feedback.pushInfo(f"Written raster geotransform: {gt_check}")
                # sample corners
                h_ck, w_ck = arr_check.shape
                sample_vals = {
                    'top_left': float(arr_check[0, 0]),
                    'top_right': float(arr_check[0, w_ck - 1]),
                    'bottom_left': float(arr_check[h_ck - 1, 0]),
                    'bottom_right': float(arr_check[h_ck - 1, w_ck - 1])
                }
                feedback.pushInfo(f"Written raster corner samples: {sample_vals}")
            else:
                feedback.pushInfo("Could not open written filled raster for readback verification")
        except Exception as e:
            feedback.pushInfo(f"Exception during filled raster readback verification: {e}")
        finally:
            out_raster = None
        feedback.pushInfo(f"Filled raster written to: {output_raster_path}")
        try:
            feedback.setProgress(70)
        except Exception:
            pass

        # Calculate pond depth raster (filled_dem - dem)
        pond_depth = filled_dem - dem       
        # Ensure output directory exists
        pond_depth_dir = os.path.dirname(output_pond_depth_raster_path)
        if pond_depth_dir and not os.path.exists(pond_depth_dir):
            os.makedirs(pond_depth_dir)
        # Write pond depth raster using GDAL
        pond_driver = gdal.GetDriverByName('GTiff')
        pond_raster = pond_driver.Create(output_pond_depth_raster_path, width, height, 1, gdal.GDT_Float32)
        pond_raster.SetGeoTransform(geotransform)
        pond_raster.SetProjection(input_raster.crs().toWkt())
        pond_band = pond_raster.GetRasterBand(1)
        try:
            pond_arr = np.ascontiguousarray(pond_depth.astype(np.float32))
        except Exception as e:
            feedback.reportError(f"Failed to prepare pond_depth array for writing: {e}")
            pond_raster = None
            return {}
        feedback.pushInfo(f"pond_depth array shape: {pond_arr.shape}, dtype: {pond_arr.dtype}")
        if pond_arr.shape != (height, width):
            feedback.reportError(f"pond_depth shape {pond_arr.shape} does not match expected (height,width)=({height},{width}). Aborting write.")
            pond_raster = None
            return {}
        try:
            pond_band.WriteArray(pond_arr)
        except Exception as e:
            feedback.reportError(f"Failed to WriteArray for pond depth raster: {e}; arr.shape={pond_arr.shape}; expected (height,width)=({height},{width})")
            pond_raster = None
            return {}
        pond_band.SetNoDataValue(no_data_value)
        pond_band.FlushCache()
        pond_band.SetNoDataValue(no_data_value)
        pond_band.FlushCache()
        # Readback verification for pond depth raster
        try:
            ds_pcheck = gdal.Open(output_pond_depth_raster_path)
            if ds_pcheck is not None:
                pb = ds_pcheck.GetRasterBand(1)
                parr_check = pb.ReadAsArray()
                gt_pcheck = ds_pcheck.GetGeoTransform()
                feedback.pushInfo(f"Pond raster readback shape: {parr_check.shape}, dtype: {parr_check.dtype}")
                feedback.pushInfo(f"Pond raster geotransform: {gt_pcheck}")
            else:
                feedback.pushInfo("Could not open written pond depth raster for readback verification")
        except Exception as e:
            feedback.pushInfo(f"Exception during pond depth raster readback verification: {e}")
        finally:
            pond_raster = None
        feedback.pushInfo(f"Pond depth raster written to: {output_pond_depth_raster_path}")
        try:
            feedback.setProgress(80)
        except Exception:
            pass

        # Calculate valid pond depth raster (where depth > min_depth)
        min_depth = self.parameterAsDouble(parameters, "MIN_DEPTH", context)
        pond_depth_valid = pond_depth > min_depth

        # Write valid pond depth raster (where depth > min_depth)
        pond_depth_valid_dir = os.path.dirname(output_pond_depth_raster_valid_path)
        if pond_depth_valid_dir and not os.path.exists(pond_depth_valid_dir):
            os.makedirs(pond_depth_valid_dir)
        
        # pond_depth_valid = np.where(pond_depth > min_depth, pond_depth, no_data_value).astype(np.float32)
        pond_raster_valid = pond_driver.Create(output_pond_depth_raster_valid_path, width, height, 1, gdal.GDT_Float32)
        pond_raster_valid.SetGeoTransform(geotransform)
        pond_raster_valid.SetProjection(input_raster.crs().toWkt())
        pond_band_valid = pond_raster_valid.GetRasterBand(1)
        # pond_depth_valid is boolean; write a float raster with nodata and a separate mask if needed
        try:
            pond_valid_float = np.where(pond_depth > min_depth, pond_depth_valid, no_data_value).astype(np.float32)
            pond_valid_arr = np.ascontiguousarray(pond_valid_float)
        except Exception as e:
            feedback.reportError(f"Failed to prepare valid pond depth array for writing: {e}")
            pond_raster_valid = None
            return {}
        feedback.pushInfo(f"pond_valid_arr shape: {pond_valid_arr.shape}, dtype: {pond_valid_arr.dtype}")
        if pond_valid_arr.shape != (height, width):
            feedback.reportError(f"pond_valid_arr shape {pond_valid_arr.shape} does not match expected (height,width)=({height},{width}). Aborting write.")
            pond_raster_valid = None
            return {}
        try:
            pond_band_valid.WriteArray(pond_valid_arr)
        except Exception as e:
            feedback.reportError(f"Failed to WriteArray for valid pond depth raster: {e}; arr.shape={pond_valid_arr.shape}; expected (height,width)=({height},{width})")
            pond_raster_valid = None
            return {}
        pond_band_valid.SetNoDataValue(no_data_value)
        pond_band_valid.FlushCache()
        pond_band_valid.SetNoDataValue(no_data_value)
        pond_band_valid.FlushCache()
        # Readback verification for valid pond raster
        try:
            ds_vcheck = gdal.Open(output_pond_depth_raster_valid_path)
            if ds_vcheck is not None:
                vb = ds_vcheck.GetRasterBand(1)
                varr_check = vb.ReadAsArray()
                gt_vcheck = ds_vcheck.GetGeoTransform()
                feedback.pushInfo(f"Valid pond raster readback shape: {varr_check.shape}, dtype: {varr_check.dtype}")
                feedback.pushInfo(f"Valid pond raster geotransform: {gt_vcheck}")
            else:
                feedback.pushInfo("Could not open written valid pond raster for readback verification")
        except Exception as e:
            feedback.pushInfo(f"Exception during valid pond raster readback verification: {e}")
        finally:
            pond_raster_valid = None
        feedback.pushInfo(f"Valid pond depth raster written to: {output_pond_depth_raster_valid_path}")
        try:
            feedback.setProgress(85)
        except Exception:
            pass

        outlines_dir = os.path.dirname(pond_outline_output_path)
        if outlines_dir and not os.path.exists(outlines_dir):
            os.makedirs(outlines_dir)
        # Polygonize the valid pond depth raster to vector shapes
        polygonize_params = {
            'INPUT': output_pond_depth_raster_valid_path,
            'BAND': 1,
            'FIELD': 'IsPond',
            'EIGHT_CONNECTEDNESS': False,
            'OUTPUT': pond_outline_output_path
        }
        
        processing.run('gdal:polygonize', polygonize_params, context=context, feedback=feedback)
        feedback.pushInfo(f"Pond outlines vector layer written to: {pond_outline_output_path}")
        try:
            feedback.setProgress(90)
        except Exception:
            pass

        # After polygonize, filter polygons to keep only those with IsPond == 1
        
        pond_layer = QgsVectorLayer(pond_outline_output_path, "PondOutlines", "ogr")
        if pond_layer.isValid():
            pond_layer.startEditing()
            ids_to_delete = [f.id() for f in pond_layer.getFeatures() if f["IsPond"] != 1]
            pond_layer.deleteFeatures(ids_to_delete)
            pond_layer.commitChanges()
            # Optionally, overwrite the file with the filtered layer
            QgsVectorFileWriter.writeAsVectorFormat(pond_layer, pond_outline_output_path, "utf-8", pond_layer.crs(), "ESRI Shapefile")
            feedback.pushInfo(f"Filtered pond outlines written to: {pond_outline_output_path}")
        else:
            feedback.reportError(f"Could not load pond outlines layer for filtering: {pond_outline_output_path}")

        # Further filter ponds by minimum area (in CRS units) so downstream stats skip tiny ponds
        try:
            min_area = float(self.parameterAsDouble(parameters, "MIN_AREA", context))
        except Exception:
            min_area = 500.0
        try:
            pond_layer_area = QgsVectorLayer(pond_outline_output_path, "PondOutlinesAreaFilter", "ogr")
            if pond_layer_area.isValid():
                pond_layer_area.startEditing()
                small_ids = []
                for feat in pond_layer_area.getFeatures():
                    try:
                        geom = feat.geometry()
                        if geom is None:
                            small_ids.append(feat.id())
                            continue
                        # geometry area is in layer CRS units
                        area = geom.area()
                        if area < min_area:
                            small_ids.append(feat.id())
                    except Exception as e:
                        feedback.pushInfo(f"Error evaluating area for feature {feat.id()}: {e}")
                if small_ids:
                    pond_layer_area.deleteFeatures(small_ids)
                    pond_layer_area.commitChanges()
                    # overwrite shapefile with area-filtered results
                    QgsVectorFileWriter.writeAsVectorFormat(pond_layer_area, pond_outline_output_path, "utf-8", pond_layer_area.crs(), "ESRI Shapefile")
                    feedback.pushInfo(f"Removed {len(small_ids)} pond features smaller than MIN_AREA={min_area} and updated shapefile.")
                else:
                    pond_layer_area.rollBack()
                    feedback.pushInfo(f"No pond features smaller than MIN_AREA={min_area} found.")

                # Add a new field "PONDid" to assign unique IDs to each pond
                pond_layer_area.startEditing()
                if "PONDid" not in [field.name() for field in pond_layer_area.fields()]:
                    pond_layer_area.dataProvider().addAttributes([QgsField("PONDid", QVariant.String)])
                    pond_layer_area.updateFields()

                # Assign unique IDs (P1, P2, P3, ...) to each pond
                for i, feature in enumerate(pond_layer_area.getFeatures(), start=1):
                    feature.setAttribute("PONDid", f"P{i}")
                    pond_layer_area.updateFeature(feature)

                pond_layer_area.commitChanges()
                feedback.pushInfo("Assigned unique IDs (PONDid) to each pond.")
            else:
                feedback.reportError(f"Could not load pond outlines layer for filtering: {pond_outline_output_path}")
        except Exception as e:
            feedback.pushInfo(f"Exception during MIN_AREA filtering: {e}")

        # Optionally smooth the pond outlines using QGIS generalize algorithm
        try:
            do_gen = self.parameterAsBoolean(parameters, "GENERALIZE_OUTLINES", context)
        except Exception:
            do_gen = True
        if do_gen:
            try:
                import tempfile
                gen_out = os.path.join(tempfile.gettempdir(), f"pond_outlines_gen_{uuid.uuid4().hex}.shp")
                gen_params = {
                    'INPUT': pond_outline_output_path,
                    'ITERATIONS': 1,
                    'MAX_ANGLE': 180,
                    'OFFSET': 0.5,
                    'OUTPUT': gen_out
                }
                processing.run('qgis:smoothgeometry', gen_params, context=context, feedback=feedback)
                # replace the outline path with the smoothed version for downstream steps
                if os.path.exists(gen_out):
                    pond_outline_output_path = gen_out
                    feedback.pushInfo(f"Smoothed pond outlines written to: {pond_outline_output_path}")
            except Exception as e:
                feedback.pushInfo(f"Smooth step failed or not available: {e}")

        # Use QGIS Processing algorithm for zonal statistics instead of QgsZonalStatistics
        zonal_params = {
            'INPUT_RASTER': output_raster_path,
            'RASTER_BAND': 1,
            'INPUT_VECTOR': pond_outline_output_path,
            'COLUMN_PREFIX': 'RL',
            'STATISTICS': [6]  # 6 = Maximum
        }
        
        processing.run('qgis:zonalstatistics', zonal_params, context=context, feedback=feedback)
        feedback.pushInfo("Added RLmax zonal statistics to pond outlines layer using qgis:zonalstatistics.")

        # Also compute zonal statistics for pond depth raster: sum, count, mean, min, max
        depth_zonal_params = {
            'INPUT_RASTER': output_pond_depth_raster_path,
            'RASTER_BAND': 1,
            'INPUT_VECTOR': pond_outline_output_path,
            'COLUMN_PREFIX': 'DEPTH',
            # qgis:zonalstatistics STATISTICS codes: 1=sum,2=mean,3=median,6=max
            'STATISTICS': [1, 2, 3, 6]
        }
        processing.run('qgis:zonalstatistics', depth_zonal_params, context=context, feedback=feedback)
        feedback.pushInfo("Added DEPTH zonal statistics (sum,count,mean,min,max) to pond outlines layer using qgis:zonalstatistics.")
        try:
            feedback.setProgress(95)
        except Exception:
            pass

        # Compute RLmin = RLmax - DEPTH_max and PONDvolume = DEPTH_sum * pixel_area
        try:
            from qgis.PyQt.QtCore import QVariant
            from qgis.core import QgsField

            pond_layer_upd = QgsVectorLayer(pond_outline_output_path, "PondOutlinesForStats", "ogr")
            if not pond_layer_upd.isValid():
                feedback.reportError(f"Could not open pond outlines layer for stat post-processing: {pond_outline_output_path}")
            else:
                # determine pixel area from geotransform
                try:
                    if geotransform is not None:
                        # area = |a*f - b*e| where gt = (c, a, b, f, e, d)?? standard gt = (xmin, px, rx, ymax, ry, py)
                        # More reliably: area = abs(gt[1]*gt[5] - gt[2]*gt[4])
                        pixel_area = abs(geotransform[1] * geotransform[5] - geotransform[2] * geotransform[4])
                    else:
                        # fallback to rasterUnitsPerPixelX/Y
                        pixel_area = abs(input_raster.rasterUnitsPerPixelX() * input_raster.rasterUnitsPerPixelY())
                except Exception:
                    pixel_area = abs(input_raster.rasterUnitsPerPixelX() * input_raster.rasterUnitsPerPixelY())

                # helper to find field names produced by zonalstatistics
                def find_field(layer, prefix, keywords):
                    names = [f.name() for f in layer.fields()]
                    low_names = [n.lower() for n in names]
                    for kw in keywords:
                        target = f"{prefix}_{kw}".lower()
                        if target in low_names:
                            return names[low_names.index(target)]
                    # try prefix+kw without underscore
                    for kw in keywords:
                        target = f"{prefix}{kw}".lower()
                        if target in low_names:
                            return names[i]
                    # fallback: find any field that starts with prefix and contains any keyword
                    for i, n in enumerate(low_names):
                        if n.startswith(prefix.lower()):
                            for kw in keywords:
                                if kw in n:
                                    return names[i]
                    return None

                rlmax_field = find_field(pond_layer_upd, 'RL', ['max', 'maximum'])
                depth_sum_field = find_field(pond_layer_upd, 'DEPTH', ['sum', 'total'])
                depth_max_field = find_field(pond_layer_upd, 'DEPTH', ['max', 'maximum'])

                # Add RLmin and PONDvolume fields if not present
                new_fields = []
                if 'RLmin' not in [f.name() for f in pond_layer_upd.fields()]:
                    new_fields.append(QgsField('RLmin', QVariant.Double))
                if 'PONDvolume' not in [f.name() for f in pond_layer_upd.fields()]:
                    new_fields.append(QgsField('PONDvolume', QVariant.Double))
                if new_fields:
                    dp = pond_layer_upd.dataProvider()
                    dp.addAttributes(new_fields)
                    pond_layer_upd.updateFields()
                
                # Add PONDarea field if not present
                if 'PONDarea' not in [f.name() for f in pond_layer_upd.fields()]:
                    pond_layer_upd.dataProvider().addAttributes([QgsField('PONDarea', QVariant.Double)])
                    pond_layer_upd.updateFields()
                    # Compute PONDarea for each feature
                    pond_layer_upd.startEditing()
                    for feat in pond_layer_upd.getFeatures():
                        try:
                            geom = feat.geometry()
                            if geom is not None:
                                area = geom.area()  # in layer CRS units
                                feat.setAttribute('PONDarea', area)
                                pond_layer_upd.updateFeature(feat)
                        except Exception as e:
                            feedback.pushInfo(f"Error computing PONDarea for feature {feat.id()}: {e}")
                    pond_layer_upd.commitChanges()

                # Now iterate features and compute values
                pond_layer_upd.startEditing()
                total_feats = max(1, pond_layer_upd.featureCount())
                for i, feat in enumerate(pond_layer_upd.getFeatures()):
                    if feedback.isCanceled():
                        feedback.pushInfo("Processing canceled during feature attribute computation.")
                        pond_layer_upd.rollBack()
                        return {}
                    attrs = {}
                    try:
                        rlmax = None
                        if rlmax_field:
                            rlmax = feat[rlmax_field]
                        depth_max = None
                        if depth_max_field:
                            depth_max = feat[depth_max_field]
                        depth_sum = None
                        if depth_sum_field:
                            depth_sum = feat[depth_sum_field]

                        rlmin_val = None
                        if rlmax is not None and depth_max is not None:
                            try:
                                rlmin_val = float(rlmax) - float(depth_max)
                            except Exception:
                                rlmin_val = None

                        pondvol_val = None
                        if depth_sum is not None:
                            try:
                                pondvol_val = float(depth_sum) * float(pixel_area)
                            except Exception:
                                pondvol_val = None

                        # set attributes
                        if rlmin_val is not None:
                            feat.setAttribute('RLmin', rlmin_val)
                        if pondvol_val is not None:
                            feat.setAttribute('PONDvolume', pondvol_val)
                        pond_layer_upd.updateFeature(feat)
                    except Exception as e:
                        feedback.pushInfo(f"Failed computing RLmin/PONDvolume for feature {feat.id()}: {e}")
                    # update progress in this loop
                    if (i % max(1, int(total_feats / 20))) == 0:
                        try:
                            pct = 95 + int((i / float(total_feats)) * 5)
                            feedback.setProgress(min(100, pct))
                        except Exception:
                            pass
                pond_layer_upd.commitChanges()
                try:
                    feedback.setProgress(100)
                except Exception:
                    pass
                # Remove the DEPTH_sum field (if present) to avoid confusing users
                try:
                    if depth_sum_field:
                        idx = pond_layer_upd.fields().indexFromName(depth_sum_field)
                        if idx != -1:
                            pond_layer_upd.startEditing()
                            pond_layer_upd.dataProvider().deleteAttributes([idx])
                            pond_layer_upd.updateFields()
                            pond_layer_upd.commitChanges()
                            feedback.pushInfo(f"Removed field '{depth_sum_field}' from pond outlines.")
                except Exception as e:
                    feedback.pushInfo(f"Could not remove DEPTH_sum field: {e}")

                # overwrite shapefile with updated attributes
                QgsVectorFileWriter.writeAsVectorFormat(pond_layer_upd, pond_outline_output_path, "utf-8", pond_layer_upd.crs(), "ESRI Shapefile")
                feedback.pushInfo("Computed RLmin and PONDvolume and wrote updated pond outlines shapefile.")
        except Exception as e:
            feedback.pushInfo(f"Exception during RLmin/PONDvolume computation: {e}")

        # Optionally add pond outlines to project
        add_outlines = self.parameterAsEnum(parameters, "ADD_OUTLINES_TO_PROJECT", context)
        if add_outlines == 1:  # "Yes"            
            layer = QgsVectorLayer(pond_outline_output_path, "Pond Outlines", "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                feedback.pushInfo("Pond outlines layer added to project.")
            else:
                feedback.reportError(f"Could not add pond outlines layer to project: {pond_outline_output_path}")

        # Optionally open pond outlines after running algorithm
        open_outlines = self.parameterAsBoolean(parameters, "OPEN_OUTLINES_AFTER_RUN", context)
        if open_outlines:            
            layer = QgsVectorLayer(pond_outline_output_path, "Pond Outlines", "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                feedback.pushInfo("Pond outlines layer added to project.")
            else:
                feedback.reportError(f"Could not add pond outlines layer to project: {pond_outline_output_path}")

        return {
            "OUTPUT_FILLED_RASTER": output_raster_path,
            "OUTPUT_POND_DEPTH_RASTER": output_pond_depth_raster_path,
            "OUTPUT_POND_DEPTH_RASTER_VALID": output_pond_depth_raster_valid_path,
            "OUTPUT_POND_OUTLINES": pond_outline_output_path
        }

    def createInstance(self):
        return FindRasterPonds()
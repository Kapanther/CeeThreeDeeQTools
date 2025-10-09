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

# region Imports
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
    QgsField,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterVectorDestination,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterString,
    QgsVectorFileWriter,
    QgsSimpleFillSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsExpression,
    QgsCallout  # <-- Added import for QgsTextCallout
)
import xml.etree.ElementTree as ET
from xml.dom.minidom import parseString
from ..ctdq_support import CTDQSupport, ctdprocessing_command_info
from .ctdq_AlgoRun import ctdqAlgoRun  # <-- Add this import to fix the missing base class
import heapq
import numpy as np
import processing
import os
from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtGui import QColor
# endregion

class FindRasterPonds(ctdqAlgoRun):
    # region Class: FindRasterPonds and helpers
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
    Also computes statistics regarding the ponds like maximum and minimum elevation (PONDRLmax, PONDRLmin), pond volume (PONDvolume), 
    and depth statistics (DEPTH_sum, DEPTH_mean, DEPTH_max).
    """

    MIN_DEPTH = "MIN_DEPTH"
    MIN_AREA = "MIN_AREA"
    INPUT_RASTER = "INPUT_RASTER"
    OUTPUT_POND_OUTLINES = "OUTPUT_POND_OUTLINES"
    OUTPUT_FILLED_RASTER = "OUTPUT_FILLED_RASTER"
    OUTPUT_POND_DEPTH_RASTER = "OUTPUT_POND_DEPTH_RASTER"
    OUTPUT_POND_DEPTH_RASTER_VALID = "OUTPUT_POND_DEPTH_RASTER_VALID"   
    FILL_SYMBOL = QgsFillSymbol.createSimple({
                    'color': '173,216,230,128',  # Light blue with 50% transparency (alpha=128)
                    'outline_color': '0,0,255,255',  # Blue outline
                    'outline_width': '0.5',
                    'outline_style': 'solid'
                }) 
    LABEL_EXPRESSION = '"PONDid" || \'\\n\' || \'(RL=\' || "PONDRLmax" || \')\' || \'\\n\' || \'Vol =\' || "PONDvolume" || \' m³\' || \'\\n\' || \'Area=\' || "PONDarea" || \' m²\''
    LABEL_TEXT_FORMAT = QgsTextFormat()                
    LABEL_TEXT_FORMAT.setSize(8)
    LABEL_TEXT_FORMAT.setColor(QColor(0, 0, 0))  # Black text
    LABEL_BUFFER_FORMAT = QgsTextBufferSettings()
    LABEL_BUFFER_FORMAT.setEnabled(True)
    LABEL_BUFFER_FORMAT.setSize(1.5)
    LABEL_BUFFER_FORMAT.setColor(QColor(255, 255, 255))  # White buffer

    def name(self):
        return self.TOOL_NAME

    def displayName(self):
        return ctdprocessing_command_info[self.TOOL_NAME]["disp"]

    def group(self):
        return ctdprocessing_command_info[self.TOOL_NAME]["group"]

    def groupId(self):
        return ctdprocessing_command_info[self.TOOL_NAME]["group_id"]

    def shortHelpString(self) -> str:
        return ctdprocessing_command_info[self.TOOL_NAME]["shortHelp"]

    # endregion

    # region Algorithm Initialization (initAlgorithm)
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
                defaultValue=0.2,
                optional=False
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                "MIN_AREA",
                "Minimum Pond Area (in square units of the CRS)",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=2000.0,
                optional=False
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorDestination(
                "OUTPUT_POND_OUTLINES",
                "Output Pond Outlines Vector",                
                optional=False,                
                defaultValue=None              
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
        # region Process: Setup / Parameters
        # Get input raster and output path
        input_raster = self.parameterAsRasterLayer(parameters, "GROUND_RASTER", context)
        output_raster_path = self.parameterAsOutputLayer(parameters, "OUTPUT_FILLED_RASTER", context)
        output_pond_depth_raster_path = self.parameterAsOutputLayer(parameters, "OUTPUT_POND_DEPTH_RASTER", context)
        output_pond_depth_raster_valid_path = self.parameterAsOutputLayer(parameters, "OUTPUT_POND_DEPTH_RASTER_VALID", context)
        pond_outline_output_path = self.parameterAsOutputLayer(parameters, "OUTPUT_POND_OUTLINES", context)
        
        # Get precision values from global settings with fallback to 3 decimal places
        precision_elevation = CTDQSupport.get_precision_setting_with_fallback("ctdq_precision_elevation", 3)
        precision_area = CTDQSupport.get_precision_setting_with_fallback("ctdq_precision_area", 3)
        precision_volume = CTDQSupport.get_precision_setting_with_fallback("ctdq_precision_volume", 3)
        
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
        if not pond_outline_output_path:
            pond_outline_output_path = os.path.join(tempfile.gettempdir(), f"OUTPUT_POND_OUTLINES_{uuid.uuid4().hex}.gpkg")
            feedback.pushInfo(f"No OUTPUT_POND_OUTLINES provided; using temporary path: {pond_outline_output_path}")

        # Determine final vs working pond outlines output
        # The Processing framework may return the literal string 'TEMPORARY_OUTPUT' when the
        # user selected a temporary output. Detect that and treat final_output_path as None.
        final_pond_outline_path = pond_outline_output_path
        if isinstance(final_pond_outline_path, str) and final_pond_outline_path.upper() == 'TEMPORARY_OUTPUT':
            final_pond_outline_path = None

        # Log paths for debugging
        feedback.pushInfo(f"Input raster: {input_raster.name()}")
        feedback.pushInfo(f"Output raster path: {output_raster_path}")
        feedback.pushInfo(f"Output pond depth raster path: {output_pond_depth_raster_path}")
        feedback.pushInfo(f"Output valid pond depth raster path: {output_pond_depth_raster_valid_path}")
        feedback.pushInfo(f"Output working pond outlines path: {pond_outline_output_path}")
        # initialize progress
        try:
            feedback.setProgress(0)
        except Exception:
            # some feedback implementations may not support setProgress
            pass

        # endregion

        # region Process: Read raster into numpy DEM
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

    # endregion

    # region Process: Sink-fill (priority queue propagation)
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

        # endregion

        # region Process: Compute and write pond depth rasters
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

        # endregion

        # region Process: Polygonize & Filter pond outlines
        temp_poly_output_path = os.path.join(tempfile.gettempdir(), f"pond_outlines_polygonize_{uuid.uuid4().hex}.gpkg")
        # Polygonize the valid pond depth raster to vector shapes
        polygonize_params = {
            'INPUT': output_pond_depth_raster_valid_path,
            'BAND': 1,
            'FIELD': 'IsPond',
            'EIGHT_CONNECTEDNESS': False,
            'OUTPUT': temp_poly_output_path
        }
        
        processing.run('gdal:polygonize', polygonize_params, context=context, feedback=feedback)
        feedback.pushInfo(f"Pond outlines vector layer written to: {temp_poly_output_path}")
        try:
            feedback.setProgress(90)
        except Exception:
            pass

        # After polygonize, filter polygons to keep only those with IsPond == 1 we can also filter by area here as well
        try:
            min_area = float(self.parameterAsDouble(parameters, "MIN_AREA", context))
        except Exception:
            min_area = 500.0
        
        pond_layer = QgsVectorLayer(temp_poly_output_path, "PondOutlines", "ogr")
        if pond_layer.isValid():
            pond_layer.startEditing()
            ids_to_delete = []
            for f in pond_layer.getFeatures():
                try:
                    is_pond = f["IsPond"]
                except Exception:
                    is_pond = None
                try:
                    geom = f.geometry()
                    area = geom.area() if geom is not None else 0
                except Exception:
                    area = 0
                if is_pond != 1 or area < min_area:
                    ids_to_delete.append(f.id())
            pond_layer.deleteFeatures(ids_to_delete)
            pond_layer.commitChanges()
        else:
            feedback.reportError(f"Could not load pond outlines layer for filtering: {temp_poly_output_path}")

        # Add Pond ID field
        
        try:
            pond_layer_area = QgsVectorLayer(temp_poly_output_path, "PondOutlinesAreaFilter", "ogr")

            # Add a new field "PONDid" to assign unique IDs to each pond
            pond_layer_area.startEditing()
            if "PONDid" not in [field.name() for field in pond_layer_area.fields()]:
                # Use modern QgsField constructor with proper parameter naming
                pondid_field = QgsField(name="PONDid", type=QMetaType.QString)
                pond_layer_area.dataProvider().addAttributes([pondid_field])
                pond_layer_area.updateFields()

            # Assign unique IDs (P1, P2, P3, ...) to each pond
            for i, feature in enumerate(pond_layer_area.getFeatures(), start=1):
                feature.setAttribute("PONDid", f"P{i}")
                pond_layer_area.updateFeature(feature)

            pond_layer_area.commitChanges()
            feedback.pushInfo("Assigned unique IDs (PONDid) to each pond.")
        except Exception as e:
            feedback.pushWarning(f"Exception during MIN_AREA filtering: {e}")

        # Optionally smooth the pond outlines using QGIS smoothgeometry algorithm
        temp_poly_output_path  # default to unsmoothed
        try:
            do_gen = self.parameterAsBoolean(parameters, "GENERALIZE_OUTLINES", context)
        except Exception:
            do_gen = True
        if do_gen:
            try:
                import tempfile
                gen_out = os.path.join(tempfile.gettempdir(), f"pond_outlines_gen_{uuid.uuid4().hex}.gpkg")
                gen_params = {
                    'INPUT': temp_poly_output_path,
                    'ITERATIONS': 1,
                    'MAX_ANGLE': 180,
                    'OFFSET': 0.5,
                    'OUTPUT': gen_out
                }
                processing.run('qgis:smoothgeometry', gen_params, context=context, feedback=feedback)
                # replace the outline path with the smoothed version for downstream steps
                if os.path.exists(gen_out):
                    feedback.pushInfo(f"Smoothed pond outlines written to: {gen_out}")
                    temp_poly_output_path = gen_out
            except Exception as e:
                feedback.pushInfo(f"Smooth step failed or not available: {e}")

    # endregion

    # region Process: Zonal statistics and field calculations
    # Use QGIS Processing algorithm for zonal statistics instead of QgsZonalStatistics
        zonal_params = {
            'INPUT_RASTER': output_raster_path,
            'RASTER_BAND': 1,
            'INPUT_VECTOR': temp_poly_output_path,
            'COLUMN_PREFIX': 'tP',
            'STATISTICS': [6]  # 6 = Maximum
        }
        
        processing.run('qgis:zonalstatistics', zonal_params, context=context, feedback=feedback)
        feedback.pushInfo("Added Pond zonal statistics to pond outlines layer using qgis:zonalstatistics.")

        # Also compute zonal statistics for pond depth raster: sum, count, mean, min, max
        depth_zonal_params = {
            'INPUT_RASTER': output_pond_depth_raster_path,
            'RASTER_BAND': 1,
            'INPUT_VECTOR': temp_poly_output_path,
            'COLUMN_PREFIX': 'tD',
            # qgis:zonalstatistics STATISTICS codes: 1=sum,2=mean,3=median,6=max
            'STATISTICS': [1, 2, 3, 6]
        }
        processing.run('qgis:zonalstatistics', depth_zonal_params, context=context, feedback=feedback)
        feedback.pushInfo("Added Pond Depth zonal statistics (sum,count,mean,min,max) to pond outlines layer using qgis:zonalstatistics.")
        try:
            feedback.setProgress(95)
        except Exception:
            pass

        # Compute PONDRLmin = PONDRLmax - DEPTH_max and PONDvolume = DEPTH_sum * pixel_area
        try:
            # Load the layer after zonal statistics have been added
            pond_layer_upd = QgsVectorLayer(temp_poly_output_path, "PondOutlinesForStats", "ogr")
            if not pond_layer_upd.isValid():
                feedback.reportError(f"Could not open pond outlines layer for stat post-processing: {temp_poly_output_path}")
            else:
                # Debug: List all fields to see what was actually created
                all_fields = [f.name() for f in pond_layer_upd.fields()]
                feedback.pushInfo(f"All fields in layer: {all_fields}")
                
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
                                return names[low_names.index(target)]
                    # fallback: find any field that starts with prefix and contains any keyword
                    for i, n in enumerate(low_names):
                        if n.startswith(prefix.lower()):
                            for kw in keywords:
                                if kw in n:
                                    return names[i]
                    return None

                # Find all temporary zonal statistics fields (with improved field detection)
                rlmax_field = find_field(pond_layer_upd, 'tP', ['max', 'maximum'])
                depth_sum_field = find_field(pond_layer_upd, 'tD', ['sum', 'total'])
                depth_max_field = find_field(pond_layer_upd, 'tD', ['max', 'maximum'])
                depth_mean_field = find_field(pond_layer_upd, 'tD', ['mean', 'average'])
                depth_median_field = find_field(pond_layer_upd, 'tD', ['median', 'med'])                

                feedback.pushInfo(f"Found temporary fields - tPmax: {rlmax_field}, tD fields: max={depth_max_field}, sum={depth_sum_field}, mean={depth_mean_field}, median={depth_median_field}")

                # Ensure required output fields exist (use provider.addAttributes)
                provider = pond_layer_upd.dataProvider()
                existing = [f.name() for f in pond_layer_upd.fields()]
                fields_to_add = []
                def add_if_missing(name, qtype, length=15, prec=0):
                    if name not in existing:
                        fields_to_add.append(QgsField(name, qtype, len=length, prec=prec))

                add_if_missing('PONDRLmax', QMetaType.Double, 30, precision_elevation)
                add_if_missing('PONDRLmin', QMetaType.Double, 30, precision_elevation)
                add_if_missing('PONDarea', QMetaType.Double, 30, precision_area)
                add_if_missing('PONDvolume', QMetaType.Double, 30, precision_volume)
                add_if_missing('DPTHmax', QMetaType.Double, 30, precision_elevation)
                add_if_missing('DPTHmean', QMetaType.Double, 30, precision_elevation)
                add_if_missing('DPTHmedian', QMetaType.Double, 30, precision_elevation)

                if fields_to_add:
                    provider.addAttributes(fields_to_add)
                    pond_layer_upd.updateFields()
                    feedback.pushInfo(f"Added new fields: {[f.name() for f in fields_to_add]}")

                # Build field index map
                fld_idx = {f.name(): i for i, f in enumerate(pond_layer_upd.fields())}

                # Start editing and set attributes per feature using changeAttributeValue
                pond_layer_upd.startEditing()
                per_feature_failures = []
                changes_map = {}  # fallback map of fid -> {idx: val}
                for feature in pond_layer_upd.getFeatures():
                    fid = feature.id()
                    try:
                        # helper to safely parse floats
                        def sf(v):
                            try:
                                return None if v is None else float(v)
                            except Exception:
                                return None

                        rlmax_val = sf(feature[rlmax_field]) if rlmax_field in feature.fields().names() else None
                        dsum_val = sf(feature[depth_sum_field]) if depth_sum_field in feature.fields().names() else None
                        dmax_val = sf(feature[depth_max_field]) if depth_max_field in feature.fields().names() else None
                        dmean_val = sf(feature[depth_mean_field]) if depth_mean_field in feature.fields().names() else None
                        dmed_val = sf(feature[depth_median_field]) if depth_median_field in feature.fields().names() else None

                        # prepare per-feature dict for fallback
                        attrs = {}

                        if 'PONDRLmax' in fld_idx:
                            val = round(rlmax_val, precision_elevation) if rlmax_val is not None else None
                            ok = pond_layer_upd.changeAttributeValue(fid, fld_idx['PONDRLmax'], val)
                            attrs[fld_idx['PONDRLmax']] = val
                            if not ok:
                                per_feature_failures.append((fid, 'PONDRLmax', val))

                        if 'DPTHmax' in fld_idx and dmax_val is not None:
                            val = round(dmax_val, precision_elevation)
                            ok = pond_layer_upd.changeAttributeValue(fid, fld_idx['DPTHmax'], val)
                            attrs[fld_idx['DPTHmax']] = val
                            if not ok:
                                per_feature_failures.append((fid, 'DPTHmax', val))

                        if 'DPTHmean' in fld_idx and dmean_val is not None:
                            val = round(dmean_val, precision_elevation)
                            ok = pond_layer_upd.changeAttributeValue(fid, fld_idx['DPTHmean'], val)
                            attrs[fld_idx['DPTHmean']] = val
                            if not ok:
                                per_feature_failures.append((fid, 'DPTHmean', val))

                        if 'DPTHmedian' in fld_idx and dmed_val is not None:
                            val = round(dmed_val, precision_elevation)
                            ok = pond_layer_upd.changeAttributeValue(fid, fld_idx['DPTHmedian'], val)
                            attrs[fld_idx['DPTHmedian']] = val
                            if not ok:
                                per_feature_failures.append((fid, 'DPTHmedian', val))

                        # PONDRLmin = PONDRLmax - DPTHmax
                        if 'PONDRLmin' in fld_idx:
                            if rlmax_val is not None and dmax_val is not None:
                                val = round(rlmax_val - dmax_val, precision_elevation)
                            else:
                                val = None
                            ok = pond_layer_upd.changeAttributeValue(fid, fld_idx['PONDRLmin'], val)
                            attrs[fld_idx['PONDRLmin']] = val
                            if not ok:
                                per_feature_failures.append((fid, 'PONDRLmin', val))

                        # PONDvolume = DEPTH_sum * pixel_area
                        if 'PONDvolume' in fld_idx:
                            if dsum_val is not None and pixel_area is not None:
                                val = round(dsum_val * pixel_area, precision_volume)
                            else:
                                val = None
                            ok = pond_layer_upd.changeAttributeValue(fid, fld_idx['PONDvolume'], val)
                            attrs[fld_idx['PONDvolume']] = val
                            if not ok:
                                per_feature_failures.append((fid, 'PONDvolume', val))

                        # PONDarea
                        if 'PONDarea' in fld_idx:
                            try:
                                geom = feature.geometry()
                                area_val = geom.area() if geom is not None else None
                                val = round(area_val, precision_area) if area_val is not None else None
                            except Exception:
                                val = None
                            ok = pond_layer_upd.changeAttributeValue(fid, fld_idx['PONDarea'], val)
                            attrs[fld_idx['PONDarea']] = val
                            if not ok:
                                per_feature_failures.append((fid, 'PONDarea', val))

                        # store for fallback
                        if attrs:
                            changes_map[fid] = attrs

                    except Exception as fe:
                        feedback.pushInfo(f"Feature {fid} processing error: {fe}")

                # Try to commit edits
                committed = False
                try:
                    committed = pond_layer_upd.commitChanges()
                except Exception as ce:
                    feedback.pushWarning(f"commitChanges() raised exception: {ce}")

                if not committed:
                    feedback.pushWarning(f"commitChanges failed; trying provider.changeAttributeValues() fallback. Per-feature failures: {len(per_feature_failures)}")
                    # Attempt fallback via dataProvider.changeAttributeValues
                    try:
                        prov = pond_layer_upd.dataProvider()
                        prov.changeAttributeValues(changes_map)
                        feedback.pushInfo("Fallback attribute update via provider.changeAttributeValues succeeded.")
                    except Exception as prov_e:
                        feedback.pushWarning(f"Fallback provider.changeAttributeValues failed: {prov_e}")
                else:
                    feedback.pushInfo("Computed PONDRLmin and PONDvolume fields (committed).")

                # now lets open the layer for eidting again and remove temporary fields
                field_to_delete = ['IsPond', rlmax_field, depth_sum_field, depth_max_field, depth_mean_field, depth_median_field]
                field_to_delete_index = [pond_layer_upd.fields().indexFromName(column) for column in field_to_delete if column in pond_layer_upd.fields().names()]
                if len(field_to_delete_index) > 0:
                    pond_layer_upd.startEditing()
                    pond_layer_upd.dataProvider().deleteAttributes(field_to_delete_index)
                    pond_layer_upd.commitChanges()
                    feedback.pushInfo(f"Deleted temporary fields: {field_to_delete}")

                # Update progress and clean up temporary fields
                try:
                    feedback.setProgress(95)
                except Exception:
                    pass       
                    
        except Exception as e:
            feedback.pushWarning(f"Exception during PONDRLmin/PONDvolume computation: {e}")

        # endregion
        
        # Finally, write the pond outlines to the correct output path
        # Use QgsVectorFileWriter to write working layer to final output
        try:
            if not pond_layer_upd.isValid():
                feedback.pushWarning(f"Working pond outlines layer invalid; cannot write final output: {pond_outline_output_path}")
            else:
                pond_outline_output_path = pond_layer_upd
        except Exception as e:
            feedback.pushWarning(f"Could not write final pond outlines: {e}")

        
        # Use inherited helper to register a LayerPostProcessor (handles styling/grouping)
        # enable loading outputs into the run group (postProcessAlgorithm of base class uses
        self.load_outputs = True
        display_name = "Pond Outlines"

        # lets apply styling using the LayerPostProcessor
        try:
            self.handle_post_processing(
                "OUTPUT_POND_OUTLINES",
                pond_outline_output_path,
                display_name,
                context,
                None,
                None,
                self.FILL_SYMBOL,
                self.LABEL_EXPRESSION,
                self.LABEL_TEXT_FORMAT,
                self.LABEL_BUFFER_FORMAT
                )
        except Exception as e:
            feedback.pushWarning(f"Could not apply styling/grouping to pond outlines layer: {e}")

        return {
            "OUTPUT_FILLED_RASTER": output_raster_path,
            "OUTPUT_POND_DEPTH_RASTER": output_pond_depth_raster_path,
            "OUTPUT_POND_DEPTH_RASTER_VALID": output_pond_depth_raster_valid_path,
            "OUTPUT_POND_OUTLINES": pond_outline_output_path
        }

    def createInstance(self):
        return FindRasterPonds()
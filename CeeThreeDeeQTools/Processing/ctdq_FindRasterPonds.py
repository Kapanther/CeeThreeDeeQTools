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
    QgsCallout,  # <-- Added import for QgsTextCallout
    QgsProcessing  # <-- Added import for QgsProcessing
)
import tempfile, uuid, os, processing
import xml.etree.ElementTree as ET
from xml.dom.minidom import parseString
from ..ctdq_support import CTDQSupport, ctdprocessing_command_info
from ..Functions import ctdq_raster_functions
from .ctdq_AlgoRun import ctdqAlgoRun  # <-- Add this import to fix the missing base class
from .ctdq_AlgoSymbology import PostVectorSymbology  # Import symbology class
from osgeo import gdal
import numpy as np
from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtGui import QColor
# endregion

class FindRasterPonds(ctdqAlgoRun):

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
        output_pond_depth_raster = self.parameterAsOutputLayer(parameters, "OUTPUT_POND_DEPTH_RASTER", context)
        output_pond_depth_raster_valid_path = self.parameterAsOutputLayer(parameters, "OUTPUT_POND_DEPTH_RASTER_VALID", context)
        pond_outline_output_path = self.parameterAsOutputLayer(parameters, "OUTPUT_POND_OUTLINES", context)
        
        # Get precision values from global settings with fallback to 3 decimal places
        precision_elevation = CTDQSupport.get_precision_setting_with_fallback("ctdq_precision_elevation", 3)
        precision_area = CTDQSupport.get_precision_setting_with_fallback("ctdq_precision_area", 3)
        precision_volume = CTDQSupport.get_precision_setting_with_fallback("ctdq_precision_volume", 3)
        
        # initialize progress
        try:
            feedback.setProgress(0)
        except Exception:
            # some feedback implementations may not support setProgress
            pass

        # get key raster stats and 
        provider = input_raster.dataProvider()
        extent = input_raster.extent()
        width = input_raster.width()
        height = input_raster.height()
        no_data_value = provider.sourceNoDataValue(1)
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



        filled_dem = ctdq_raster_functions.CtdqRasterFunctions.ctdq_raster_fillsinks(input_raster, feedback)
        dem = ctdq_raster_functions.CtdqRasterFunctions.ctdq_raster_asnumpy(input_raster, feedback)

               
        # Check if both arrays are valid before proceeding
        if filled_dem is None:
            feedback.reportError("Failed to generate filled DEM array.")
            return {}
        if dem is None:
            feedback.reportError("Failed to read input DEM array.")
            return {}
        
        # Write filled raster
        output_raster_path = ctdq_raster_functions.CtdqRasterFunctions.ctdq_raster_fromNumpy(filled_dem, width,height,extent,input_raster.crs(),feedback)
        feedback.pushInfo(f"Filled raster written to: {output_raster_path}")
            
        # region Process: Compute and write pond depth rasters
        # Calculate pond depth raster (filled_dem - dem)
        pond_depth = filled_dem - dem       

        output_pond_depth_raster_path = ctdq_raster_functions.CtdqRasterFunctions.ctdq_raster_fromNumpy(pond_depth, width,height,extent,input_raster.crs(),feedback)

        try:
            feedback.setProgress(80)
        except Exception:
            pass
        
        # Calculate valid pond depth raster (where depth > min_depth)
        min_depth = self.parameterAsDouble(parameters, "MIN_DEPTH", context)
        pond_depth_valid = np.where(pond_depth > min_depth, pond_depth > min_depth, no_data_value).astype(np.float32)
        output_pond_depth_raster_valid_path = ctdq_raster_functions.CtdqRasterFunctions.ctdq_raster_fromNumpy(pond_depth_valid, width,height,extent,input_raster.crs(),feedback)   
        
        try:
            feedback.setProgress(85)
        except Exception:
            pass

        # endregion
        
        # Polygonize the valid pond depth raster to vector shapes
        pond_result = processing.run('gdal:polygonize',{
            'INPUT': output_pond_depth_raster_valid_path,
            'BAND': 1,
            'FIELD': 'IsPond',
            'EIGHT_CONNECTEDNESS': False,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }, context=context, feedback=feedback)['OUTPUT']
        
        # Create a QgsVectorLayer from the output path
        pond_layer = QgsVectorLayer(pond_result, "PondOutlines", "ogr")
        try:
            feedback.setProgress(90)
        except Exception:
            pass

        # After polygonize, filter polygons to keep only those with IsPond == 1 we can also filter by area here as well
        try:
            min_area = float(self.parameterAsDouble(parameters, "MIN_AREA", context))
        except Exception:
            min_area = 500.0        
        
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
            feedback.reportError(f"Could not load pond outlines layer for filtering: {output_pond_depth_raster_valid_path}")

        # Add Pond ID field
        # Add PONDid field to the filtered pond layer
        try:
            pond_layer.startEditing()
            if "PONDid" not in [field.name() for field in pond_layer.fields()]:
                # Use modern QgsField constructor with proper parameter naming
                pondid_field = QgsField(name="PONDid", type=QMetaType.QString)
                pond_layer.dataProvider().addAttributes([pondid_field])
                pond_layer.updateFields()

            # Assign unique IDs (P1, P2, P3, ...) to each pond
            for i, feature in enumerate(pond_layer.getFeatures(), start=1):
                feature.setAttribute("PONDid", f"P{i}")
                pond_layer.updateFeature(feature)

            pond_layer.commitChanges()
            feedback.pushInfo("Assigned unique IDs (PONDid) to each pond.")
        except Exception as e:
            feedback.pushWarning(f"Exception during PONDid assignment: {e}")

        # Optionally smooth the pond outlines using QGIS smoothgeometry algorithm
        try:
            do_gen = self.parameterAsBoolean(parameters, "GENERALIZE_OUTLINES", context)
        except Exception:
            do_gen = True
        if do_gen:
            try:           
                gen_result_output_path = os.path.join(tempfile.gettempdir(), f"pond_smooth_{uuid.uuid4().hex}.gpkg")     
                gen_result = processing.run('qgis:smoothgeometry',{
                    'INPUT': pond_result,
                    'ITERATIONS': 1,
                    'MAX_ANGLE': 180,
                    'OFFSET': 0.5,
                    'OUTPUT': gen_result_output_path
                }, context=context, feedback=feedback)['OUTPUT']
                pond_result = gen_result_output_path
                feedback.pushInfo("Generalized (smoothed) pond outlines.")
            except Exception as e:
                feedback.pushInfo(f"Smooth step failed or not available: {e}")
            

    # endregion

    # region Process: Zonal statistics and field calculations
    # Use QGIS Processing algorithm for zonal statistics instead of QgsZonalStatistics
        zonal_stats = processing.run('qgis:zonalstatistics',{
            'INPUT_RASTER': output_raster_path,
            'RASTER_BAND': 1,
            'INPUT_VECTOR': pond_result,
            'COLUMN_PREFIX': 'tP',
            'STATISTICS': [6]  # 6 = Maximum            
        }, context=context, feedback=feedback)
        feedback.pushInfo("Added Pond zonal statistics to pond outlines layer using qgis:zonalstatistics.")

        # Also compute zonal statistics for pond depth raster: sum, count, mean, min, max
        depth_zonal_stats = processing.run('qgis:zonalstatistics',{
            'INPUT_RASTER': output_pond_depth_raster_path,
            'RASTER_BAND': 1,
            'INPUT_VECTOR': pond_result,
            'COLUMN_PREFIX': 'tD',
            # qgis:zonalstatistics STATISTICS codes: 1=sum,2=mean,3=median,6=max
            'STATISTICS': [1, 2, 3, 6]            
        }, context=context, feedback=feedback)
        feedback.pushInfo("Added Pond Depth zonal statistics (sum,count,mean,min,max) to pond outlines layer using qgis:zonalstatistics.")
        try:
            feedback.setProgress(95)
        except Exception:
            pass

        # Compute PONDRLmin = PONDRLmax - DEPTH_max and PONDvolume = DEPTH_sum * pixel_area
        try:
            # Load the layer after zonal statistics have been added
            pond_layer_upd = QgsVectorLayer(pond_result, "PondOutlinesForStats", "ogr")
            if not pond_layer_upd.isValid():
                feedback.reportError(f"Could not open pond outlines layer for stat post-processing: {gen_result}")
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
                        feedback.pushWarning(f"Exception updating attributes for feature ID {fid}: {fe}")
                        per_feature_failures.append((fid, 'exception', str(fe)))
                    

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
                #lets write the pond_Layer_upd to the pond_outline_output_path
                error = QgsVectorFileWriter.writeAsVectorFormatV3(
                    pond_layer_upd,
                    pond_outline_output_path,
                    pond_layer_upd.transformContext(),
                    QgsVectorFileWriter.SaveVectorOptions()
                )
        except Exception as e:
            feedback.pushWarning(f"Could not write final pond outlines: {e}")

        
        # Use inherited helper to register a LayerPostProcessor (handles styling/grouping)
        # enable loading outputs into the run group (postProcessAlgorithm of base class uses
        self.load_outputs = True
        display_name = "Pond Outlines"

        # Create symbology for pond outlines
        try:
            
            # Create symbology with single symbol renderer and labeling
            pond_symbology = (PostVectorSymbology()
                .set_single_symbol_renderer(self.FILL_SYMBOL)
                .set_labeling(
                    field_name=self.LABEL_EXPRESSION,
                    text_size=8,
                    text_color=QColor(0, 0, 0),
                    buffer_enabled=True,
                    buffer_size=1.5,
                    buffer_color=QColor(255, 255, 255),
                    is_expression=True  # Explicitly mark as expression
                ))
            
            self.handle_post_processing(
                "OUTPUT_POND_OUTLINES",
                pond_outline_output_path,
                display_name,
                context,
                pond_symbology
            )
            feedback.pushInfo("Registered pond outlines with symbology.")
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
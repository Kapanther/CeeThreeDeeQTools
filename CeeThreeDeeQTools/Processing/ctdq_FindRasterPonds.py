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
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterVectorDestination,
    QgsProcessingParameterBoolean
)
import xml.etree.ElementTree as ET
from xml.dom.minidom import parseString
from ..ctdq_support import ctdprocessing_info
import os
import heapq
import numpy as np

class FindRasterPonds(QgsProcessingAlgorithm):
    import heapq

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
    """

    MIN_DEPTH = "MIN_DEPTH"
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

        # Advanced panel for output rasters
        self.addParameter(
            QgsProcessingParameterRasterDestination(
            "OUTPUT_FILLED_RASTER",
            "Output Filled Raster",
            optional=True            
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
            "OUTPUT_POND_DEPTH_RASTER",
            "Output Pond Depth Raster",
            optional=True            
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
            "OUTPUT_POND_DEPTH_RASTER_VALID",
            "Output Pond Depth Raster (Valid)",
            optional=True            
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
                "OUTPUT_POND_OUTLINES",
                "Output Pond Outlines Vector",                
                optional=False,
                fileFilter="ESRI Shapefile (*.shp)"
            )
        )

        # Move OPEN_OUTLINES_AFTER_RUN to the end of the parameter list
        self.addParameter(
            QgsProcessingParameterBoolean(
                "OPEN_OUTLINES_AFTER_RUN",
                "Open output file after running algorithm",
                defaultValue=True                
            )
        )

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

        # Get raster properties
        provider = input_raster.dataProvider()
        extent = input_raster.extent()
        width = input_raster.width()
        height = input_raster.height()
        no_data_value = provider.sourceNoDataValue(1)

        # Read raster block
        block = provider.block(1, extent, width, height)
        dem = np.zeros((height, width), dtype=np.float32)
        for y in range(height):
            for x in range(width):
                value = block.value(x, y)
                dem[y, x] = value if value != no_data_value else -9999

        # Initialize priority queue and visited mask
        pq = self.PriorityQueue()
        visited = np.zeros((height, width), dtype=bool)
        for x in range(width):
            if dem[0, x] != -9999:
                pq.put((0, x), dem[0, x])
                visited[0, x] = True
            if dem[height-1, x] != -9999:
                pq.put((height-1, x), dem[height-1, x])
                visited[height-1, x] = True
        for y in range(1, height-1):
            if dem[y, 0] != -9999:
                pq.put((y, 0), dem[y, 0])
                visited[y, 0] = True
            if dem[y, width-1] != -9999:
                pq.put((y, width-1), dem[y, width-1])
                visited[y, width-1] = True

        # Main loop: process cells from the priority queue
        filled_dem = dem.copy()
        directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        while not pq.empty():
            y, x = pq.get()
            for dy, dx in directions:
                ny, nx = y + dy, x + dx
                if 0 <= ny < height and 0 <= nx < width:
                    if not visited[ny, nx] and dem[ny, nx] != -9999:
                        if filled_dem[ny, nx] < filled_dem[y, x]:
                            filled_dem[ny, nx] = filled_dem[y, x]
                        pq.put((ny, nx), filled_dem[ny, nx])
                        visited[ny, nx] = True

        # Ensure output directory exists
        import os
        output_dir = os.path.dirname(output_raster_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        # Write filled raster to disk using GDAL
        from osgeo import gdal
        driver = gdal.GetDriverByName('GTiff')
        out_raster = driver.Create(output_raster_path, width, height, 1, gdal.GDT_Float32)
        # Construct GDAL geotransform from QGIS raster
        extent = input_raster.extent()
        geotransform = (
            extent.xMinimum(),
            input_raster.rasterUnitsPerPixelX(),
            0,
            extent.yMaximum(),
            0,
            -input_raster.rasterUnitsPerPixelY()
        )
        out_raster.SetGeoTransform(geotransform)
        out_raster.SetProjection(input_raster.crs().toWkt())
        out_band = out_raster.GetRasterBand(1)
        # Write the array, flipping rows to match GDAL's expected orientation
        out_band.WriteArray(filled_dem.T)
        out_band.SetNoDataValue(no_data_value)
        out_band.FlushCache()
        out_raster = None
        feedback.pushInfo(f"Filled raster written to: {output_raster_path}")

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
        pond_band.WriteArray(pond_depth.T)
        pond_band.SetNoDataValue(no_data_value)
        pond_band.FlushCache()
        pond_raster = None
        feedback.pushInfo(f"Pond depth raster written to: {output_pond_depth_raster_path}")

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
        pond_band_valid.WriteArray(pond_depth_valid.T)
        pond_band_valid.SetNoDataValue(no_data_value)
        pond_band_valid.FlushCache()
        pond_raster_valid = None
        feedback.pushInfo(f"Valid pond depth raster written to: {output_pond_depth_raster_valid_path}")

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
        import processing
        processing.run('gdal:polygonize', polygonize_params, context=context, feedback=feedback)
        feedback.pushInfo(f"Pond outlines vector layer written to: {pond_outline_output_path}")

        # After polygonize, filter polygons to keep only those with IsPond == 1
        from qgis.core import QgsVectorLayer, QgsFeature, QgsVectorFileWriter
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

        # Use QGIS Processing algorithm for zonal statistics instead of QgsZonalStatistics
        zonal_params = {
            'INPUT_RASTER': output_raster_path,
            'RASTER_BAND': 1,
            'INPUT_VECTOR': pond_outline_output_path,
            'COLUMN_PREFIX': 'RL',
            'STATISTICS': [6]  # 6 = Maximum
        }
        import processing
        processing.run('qgis:zonalstatistics', zonal_params, context=context, feedback=feedback)
        feedback.pushInfo("Added RLmax zonal statistics to pond outlines layer using qgis:zonalstatistics.")

        # Optionally add pond outlines to project
        add_outlines = self.parameterAsEnum(parameters, "ADD_OUTLINES_TO_PROJECT", context)
        if add_outlines == 1:  # "Yes"
            from qgis.core import QgsVectorLayer
            layer = QgsVectorLayer(pond_outline_output_path, "Pond Outlines", "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                feedback.pushInfo("Pond outlines layer added to project.")
            else:
                feedback.reportError(f"Could not add pond outlines layer to project: {pond_outline_output_path}")

        # Optionally open pond outlines after running algorithm
        open_outlines = self.parameterAsBoolean(parameters, "OPEN_OUTLINES_AFTER_RUN", context)
        if open_outlines:
            from qgis.core import QgsVectorLayer
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

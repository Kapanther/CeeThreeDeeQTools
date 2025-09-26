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
import os  # Add this import for path validation
import tempfile
import uuid  # Import uuid for generating unique identifiers
from osgeo import gdal

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsVectorLayer,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsWkbTypes,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterVectorDestination,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterRasterLayer,
    QgsProcessingException,
    QgsVectorFileWriter,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingOutputLayerDefinition,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsProcessingUtils,
    QgsRasterLayer,  # Import QgsRasterLayer for raster support
    QgsProcessingParameterString,  # Import QgsProcessingParameterString for text input
    QgsProcessingFeatureSourceDefinition,  # Import QgsProcessingFeatureSourceDefinition for spatial join
)
from qgis.utils import iface  # Import iface to access the map canvas
from PyQt5.QtCore import QVariant, QCoreApplication
from ..ctdq_support import ctdprocessing_info
import processing  # Import processing for running algorithms


class CalculateStageStoragePond(QgsProcessingAlgorithm):
    TOOL_NAME = "CalculateStageStoragePond"
    """
    Calcualtes the volumes/area at an increment for each polygon that represents a pond. Creates a seperate overlapping polygon for each slice and adds
    the attributes for area and volume at that stage as well as the original pond vectors attributes.
    """
    INPUT_RASTER = "INPUT_RASTER"
    INPUT_PONDS_VECTOR = "INPUT_PONDS_VECTOR"    
    INPUT_PONDS_RL_FIELD = "INPUT_PONDS_RL_FIELD"
    STORAGE_INTERVAL = "STORAGE_INTERVAL"
    DEFAULT_STORAGE_INTERVAL = 1  # Interval for stage slices
    OUTPUT_STAGE_STORAGE = "OUTPUT_STAGE_STORAGE"

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
        Define the output parameter for the location of the final "Extents" layer.
        """
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_RASTER,
                "Input Ground Raster",
                optional=False      
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_PONDS_VECTOR,
                "Input Ponds Vector Layer",
                types=[QgsWkbTypes.PolygonGeometry],
                optional=False
            )
        )

        # Replace the field selection parameter with a text input box
        self.addParameter(
            QgsProcessingParameterString(
                self.INPUT_PONDS_RL_FIELD,
                "Input Ponds RL Field",
                defaultValue="RLmax"
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
            self.STORAGE_INTERVAL,
            "Storage Interval",
            type=QgsProcessingParameterNumber.Double,  # Ensure it supports decimals
            defaultValue=self.DEFAULT_STORAGE_INTERVAL,
            minValue=0.1  # Set the minimum value to 0.1
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT_STAGE_STORAGE,
                "Output Stage Storage Slices",                
                type=QgsProcessing.TypeVectorAnyGeometry, 
                createByDefault=True,
                defaultValue=None
            )
        )

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        """
        Clip the ground raster to the pond polygons, generate contour polygons, fix geometries, and perform a spatial join.
        """
        # Retrieve parameters
        ground_raster = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
        ponds_layer = self.parameterAsVectorLayer(parameters, self.INPUT_PONDS_VECTOR, context)
        rl_field = self.parameterAsString(parameters, self.INPUT_PONDS_RL_FIELD, context)
        storage_interval = self.parameterAsDouble(parameters, self.STORAGE_INTERVAL, context)
        output_layer = self.parameterAsOutputLayer(parameters, self.OUTPUT_STAGE_STORAGE, context)

        if not ground_raster or not ponds_layer:
            raise QgsProcessingException("Both ground raster and ponds vector layer must be provided.")

        # Generate a unique identifier for this run
        run_uuid = uuid.uuid4().hex

        # Temporary file paths with UUID appended
        temp_clipped_raster = os.path.join(tempfile.gettempdir(), f"clipped_raster_{run_uuid}.tif")
        temp_contour_polygons = os.path.join(tempfile.gettempdir(), f"contour_polygons_{run_uuid}.gpkg")
        temp_spatial_join = os.path.join(tempfile.gettempdir(), f"spatial_join_result_{run_uuid}.gpkg")

        # Clip the ground raster to the pond polygons
        feedback.pushInfo("Clipping ground raster to pond polygons...")
        clip_params = {
            'INPUT': ground_raster.dataProvider().dataSourceUri(),
            'MASK': ponds_layer,
            'NODATA': -32567,
            'KEEP_RESOLUTION': True,
            'OUTPUT': temp_clipped_raster
        }
        processing.run("gdal:cliprasterbymasklayer", clip_params, context=context, feedback=feedback)
        feedback.pushInfo(f"Clipped raster saved to: {temp_clipped_raster}")

        # Generate contour polygons from the clipped raster
        feedback.pushInfo("Generating contour polygons...")
        contour_params = {
            'INPUT': temp_clipped_raster,
            'BAND': 1,
            'INTERVAL': storage_interval,
            'FIELD_NAME_MIN': 'ELEV_MIN',  # Store minimum elevation
            'FIELD_NAME_MAX': 'ELEV_MAX',  # Store maximum elevation
            'CREATE_3D': True,  # Generate 3D polygons
            'IGNORE_NODATA': True,  # Ignore NoData values
            'OPTIONS': '-p',  # Enable polygonal contouring
            'OUTPUT': temp_contour_polygons
        }
        processing.run("gdal:contour", contour_params, context=context, feedback=feedback)
        feedback.pushInfo(f"Contour polygons saved to: {temp_contour_polygons}")

        # Validate contour polygons
        contour_layer = QgsVectorLayer(temp_contour_polygons, "Contour Polygons", "ogr")
        if not contour_layer.isValid() or contour_layer.featureCount() == 0:
            raise QgsProcessingException("Contour polygons layer is invalid or contains no features.")

        # Fix geometries in the contour polygons
        feedback.pushInfo("Fixing geometries in the contour polygons...")
        fixed_contour_polygons = os.path.join(tempfile.gettempdir(), f"fixed_contour_polygons_{run_uuid}.gpkg")
        fix_geometry_params = {
            'INPUT': contour_layer,
            'OUTPUT': fixed_contour_polygons
        }
        processing.run("native:fixgeometries", fix_geometry_params, context=context, feedback=feedback)
        feedback.pushInfo(f"Fixed contour polygons saved to: {fixed_contour_polygons}")

        # Perform a spatial join between the fixed contour polygons and the pond polygons
        feedback.pushInfo("Performing spatial join between contour polygons and pond polygons...")
        spatial_join_params = {
            'INPUT': QgsProcessingFeatureSourceDefinition(fixed_contour_polygons, False),
            'JOIN': QgsProcessingFeatureSourceDefinition(ponds_layer.source(), False),
            'PREDICATE': [0],  # Intersects
            'JOIN_FIELDS': [],  # Join all fields from the pond polygons
            'METHOD': 1,  # Take attributes of the first matching feature only
            'DISCARD_NONMATCHING': False,
            'OUTPUT': temp_spatial_join
        }
        processing.run("native:joinattributesbylocation", spatial_join_params, context=context, feedback=feedback)
        feedback.pushInfo(f"Spatial join result saved to: {temp_spatial_join}")

        # Validate spatial join result
        spatial_join_layer = QgsVectorLayer(temp_spatial_join, "Spatial Join Result", "ogr")
        if not spatial_join_layer.isValid() or spatial_join_layer.featureCount() == 0:
            raise QgsProcessingException("Spatial join result layer is invalid or contains no features.")

        # Copy the spatial join result to the output layer
        feedback.pushInfo("Copying spatial join result to the output layer...")
        QgsVectorFileWriter.writeAsVectorFormat(
            spatial_join_layer,
            output_layer,
            "utf-8",
            ponds_layer.crs(),
            "ESRI Shapefile"
        )
        feedback.pushInfo(f"Output stage storage layer saved to: {output_layer}")

        return {self.OUTPUT_STAGE_STORAGE: output_layer}

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return self.__class__()

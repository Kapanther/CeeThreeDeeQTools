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

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingMultiStepFeedback,
    QgsProject,
    QgsVectorLayer,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsWkbTypes,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterVectorDestination,
    QgsProcessingParameterRasterLayer,  # Import QgsProcessingParameterRasterLayer for raster input
    QgsProcessingException,
    QgsVectorFileWriter,
    QgsProcessingOutputLayerDefinition,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsProcessingUtils,
    QgsRasterLayer,  # Import QgsRasterLayer for raster support
)
from qgis.utils import iface  # Import iface to access the map canvas
from PyQt5.QtCore import QVariant, QCoreApplication
from ..ctdq_support import ctdprocessing_command_info
import processing  # Import processing for running algorithms


class CatchmentsAndStreams(QgsProcessingAlgorithm):
    TOOL_NAME = "CatchmentsAndStreams"
    """
    Generates both catchments and stream vectors from a DEM. Streams also contain stream order (both Strahler and Shreve) and catchments are linked to streams.
    """

    INPUT_DEM = "INPUT_DEM"
    OUTPUT_CATCHMENTS = "OUTPUT_CATCHMENTS"
    OUTPUT_STREAMS = "OUTPUT_STREAMS"

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

    def initAlgorithm(self, config: Optional[dict[str, Any]] = None):
        """
        Define the output parameter for the location of the final "Extents" layer.
        """
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                "INPUT_DEM",
                "Input DEM Raster",
                optional=False
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT_CATCHMENTS,
                "Output Catchments Layer",
                type=QgsProcessing.TypeVectorPolygon,
                createByDefault=True,
                defaultValue=None
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT_STREAMS,
                "Output Streams Layer",
                type=QgsProcessing.TypeVectorLine,
                createByDefault=True,
                defaultValue=None
            )
        )

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        model_feedback: QgsProcessingMultiStepFeedback,
    ) -> dict[str, Any]:
        """
        Main Processor function to generate catchments and streams from a DEM.
        """
        # Use a multi-step feedback, so that individual child algorithm progress reports are adjusted for the
        # overall progress through the model
        feedback = QgsProcessingMultiStepFeedback(6, model_feedback)
        results = {}
        outputs = {}

        # lets use R.watershed to generate the watersheds and stream rasters initially
        alg_params = {
            '-4': False,
            '-a': False,
            '-b': False,
            '-m': False,
            '-s': False,
            'GRASS_RASTER_FORMAT_META': None,
            'GRASS_RASTER_FORMAT_OPT': None,
            'GRASS_REGION_CELLSIZE_PARAMETER': 0,
            'GRASS_REGION_PARAMETER': None,
            'blocking': None,
            'convergence': 5,
            'depression': None,
            'disturbed_land': None,
            'elevation': parameters['eg'],
            'flow': None,
            'max_slope_length': None,
            'memory': 300,
            'threshold': parameters['mincatchsize'],
            'basin': QgsProcessing.TEMPORARY_OUTPUT,
            'stream': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['Rwatershed'] = processing.run('grass7:r.watershed', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        


        # Return the output path
        return {self.OUTPUT: output_layer}

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return self.__class__()

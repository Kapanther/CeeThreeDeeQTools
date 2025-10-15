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
    QgsProcessingParameterNumber,  # Import QgsProcessingParameterNumber for numeric input
    QgsProcessingException,
    QgsVectorFileWriter,
    QgsProcessingOutputLayerDefinition,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsProcessingUtils,
    QgsRasterLayer,  # Import QgsRasterLayer for raster support
    QgsFeatureSink,  # Import QgsFeatureSink for feature sink operations
)
from qgis.utils import iface  # Import iface to access the map canvas
from PyQt5.QtCore import QVariant, QCoreApplication
from ..ctdq_support import ctdprocessing_command_info
from ..Functions import ctdq_raster_functions
import processing  # Import processing for running algorithms


class CatchmentsAndStreams(QgsProcessingAlgorithm):
    TOOL_NAME = "CatchmentsAndStreams"
    """
    Generates both catchments and stream vectors from a DEM. Streams also contain stream order (both Strahler and Shreve) and catchments are linked to streams.
    """

    INPUT_DEM = "INPUT_DEM"
    INPUT_THRESHOLD = "INPUT_THRESHOLD"
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
            QgsProcessingParameterNumber(
                self.INPUT_THRESHOLD,
                "Flow Threshold",
                defaultValue=4000
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
        try:
            """
            Main Processor function to generate catchments and streams from a DEM.
            """
            #parameterrised inputs
            input_dem = self.parameterAsRasterLayer(parameters, "INPUT_DEM", context)
            input_threshold = self.parameterAsDouble(parameters, "INPUT_THRESHOLD", context)

            # Use a multi-step feedback, so that individual child algorithm progress reports are adjusted for the
            # overall progress through the model
            feedback = QgsProcessingMultiStepFeedback(6, model_feedback)

            # generate a fill direction raster using the DEM
            
            dem_filled = ctdq_raster_functions.CtdqRasterFunctions.ctdq_raster_fillsinks(input_dem, feedback)

            dem_flow_accumulation = processing.run("grass7:r.watershed", {
                'elevation': dem_filled,
                'accumulation': QgsProcessing.TEMPORARY_OUTPUT,
                'drainage': QgsProcessing.TEMPORARY_OUTPUT,
                'threshold': input_threshold,
                '-s': True,
                '-m': True
            }, context=context, feedback=feedback)['accumulation']

            streams = processing.run("grass7:r.stream.extract", {
                'elevation': dem_filled,
                'accumulation': dem_flow_accumulation,
                'threshold': input_threshold,
                'stream_vector': QgsProcessing.TEMPORARY_OUTPUT,
                'stream_raster': QgsProcessing.TEMPORARY_OUTPUT,
                'direction': QgsProcessing.TEMPORARY_OUTPUT,
                'GRASS_OUTPUT_TYPE_PARAMETER': 2
            }, context=context, feedback=feedback)['stream_vector']

            stream_sink,stream_dest_id = self.parameterAsSink(parameters,self.OUTPUT_STREAMS,context,
                                                              streams.fields(),QgsWkbTypes.LineString,input_dem.crs())
            if stream_sink is None:
                raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_STREAMS))
            
            feature_count = streams.featureCount()
            for current, f in enumerate(streams.getFeatures()):
                if feedback.isCanceled():
                    break
                stream_sink.addFeature(f, QgsFeatureSink.FastInsert)
                feedback.setProgress(int((current + 1) / feature_count * 100))

            # Return the output paths
            return {self.OUTPUT_STREAMS: stream_sink}
        except Exception as e:
            raise QgsProcessingException(f"Error in {self.TOOL_NAME}: {e}")

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return self.__class__()

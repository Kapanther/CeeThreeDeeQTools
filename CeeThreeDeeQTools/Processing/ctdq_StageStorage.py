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
)
from qgis.utils import iface  # Import iface to access the map canvas
from PyQt5.QtCore import QVariant, QCoreApplication
from ..ctdq_support import ctdprocessing_info


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
    DEFAULT_STORAGE_INTERVAL = 0.1  # Interval for stage slices
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
                defaultValue="PondRLmax"
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.STORAGE_INTERVAL,
                "Storage Interval",
                defaultValue=self.DEFAULT_STORAGE_INTERVAL
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
        Descripton of what the processAlgorithm does
        """

        # Create the output layer
        output_layer = self.parameterAsOutputLayer(parameters, self.OUTPUT_STAGE_STORAGE, context)

        # Validate selected ponds layer and RL field so the user gets immediate feedback
        ponds_layer = self.parameterAsVectorLayer(parameters, self.INPUT_PONDS_VECTOR, context)
        rl_field = self.parameterAsString(parameters, self.INPUT_PONDS_RL_FIELD, context)
        if ponds_layer is None or not ponds_layer.isValid():
            feedback.reportError("Input ponds vector layer is invalid or not provided.")
            return {}
        # Only check RL field if ponds_layer is valid and rl_field is not None
        if rl_field is not None:
            field_names = [f.name() for f in ponds_layer.fields()]
            if rl_field not in field_names:
                feedback.reportError(f"Selected RL field '{rl_field}' not found in layer fields: {field_names}")
                return {}
        feedback.pushInfo(f"Using RL field '{rl_field}' from layer '{ponds_layer.name()}'")

        # Return the output path
        return {self.OUTPUT_STAGE_STORAGE: output_layer}

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return self.__class__()

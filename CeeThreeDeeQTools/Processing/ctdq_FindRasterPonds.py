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
    QgsProcessingParameterFeatureSink,
    QgsProcessingOutputVectorLayer,
    QgsWkbTypes,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsProcessingParameterRasterDestination,
    QgsRasterLayer,
    QgsRasterPipe,
    QgsRasterFileWriter,
    QgsRasterBlock,
    QgsRasterDataProvider
)
from qgis.PyQt.QtCore import QVariant
import xml.etree.ElementTree as ET
from xml.dom.minidom import parseString
from ..ctdq_support import ctdprocessing_info
import os
import numpy as np

class FindRasterPonds(QgsProcessingAlgorithm):
    TOOL_NAME = "FindRasterPonds"
    """
    QGIS Processing Algorithm to detect ponds (sinks) in a raster and output a vector layer with polygons representing the ponds.
    """

    
    INPUT_RASTER = "INPUT_RASTER"
    OUTPUT_VECTOR = "OUTPUT_VECTOR"
    OUTPUT_FILLED_RASTER = "OUTPUT_FILLED_RASTER"

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
        Define the inputs and outputs of the algorithm.
        """
        # Input raster layer for ground surface
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_RASTER,
                "Ground Raster"
            )
        )

        # Output vector layer for ponds
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_VECTOR,
                "Ponds"
            )
        )

        # Output raster layer for the filled DEM
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT_FILLED_RASTER,
                "Filled Raster"
            )
        )

    def fill_sinks(self, input_raster_path, output_raster_path, feedback):
        """
        Implements the Wang and Liu method to fill sinks in a raster using QGIS native methods.
        :param input_raster_path: Path to the input raster file.
        :param output_raster_path: Path to the output filled raster file.
        :param feedback: QGIS feedback object for progress reporting.
        """
        try:
            # Load the input raster
            raster_layer = QgsRasterLayer(input_raster_path, "Input Raster")
            if not raster_layer.isValid():
                raise QgsProcessingException("Invalid input raster")

            provider = raster_layer.dataProvider()
            extent = raster_layer.extent()
            width = raster_layer.width()
            height = raster_layer.height()
            no_data_value = provider.sourceNoDataValue(1)

            # Read the raster data into a 2D array
            try:
                block = provider.block(1, extent, width, height)
                if block is None or not block.isValid():
                    raise QgsProcessingException("Failed to read a valid raster block")
            except Exception as e:
                raise QgsProcessingException(f"Error reading raster block: {e}")

            # Initialize the DEM array
            dem = np.zeros((height, width), dtype=np.float32)

            # Populate the DEM array with values from the raster block
            try:
                for y in range(height):
                    for x in range(width):
                        try:
                            value = block.value(x, y)
                            dem[y, x] = value if value != no_data_value else -9999  # Replace NoData values
                        except Exception as e:
                            feedback.pushInfo(f"Error accessing raster value at ({x}, {y}): {e}")
                            dem[y, x] = -9999  # Default to NoData value
            except Exception as e:
                raise QgsProcessingException(f"Error populating DEM array: {e}")

            # Wang and Liu sink-filling algorithm
            filled_dem = dem.copy()
            rows, cols = dem.shape
            change = True
            iteration = 0

            while change:
                change = False
                iteration += 1
                feedback.pushInfo(f"Starting iteration {iteration} of sink filling...")

                try:
                    for row in range(1, rows - 1):
                        if feedback.isCanceled():
                            raise QgsProcessingException("Processing canceled by user")

                        # Update progress based on the current row
                        progress = int((row / rows) * 100)
                        feedback.setProgress(progress)

                        for col in range(1, cols - 1):
                            # Get the 3x3 neighborhood
                            neighborhood = filled_dem[row - 1:row + 2, col - 1:col + 2]
                            center = neighborhood[1, 1]

                            # Skip nodata cells
                            if center == -9999:
                                continue

                            # Calculate the maximum elevation of the neighbors
                            max_neighbor = np.max(neighborhood)

                            # If the center is lower than the maximum neighbor, fill it
                            if center < max_neighbor:
                                filled_dem[row, col] = max_neighbor
                                change = True
                except Exception as e:
                    raise QgsProcessingException(f"Error during sink-filling iteration {iteration}: {e}")

                feedback.pushInfo(f"Iteration {iteration} completed. Progress: {progress}%")

            feedback.pushInfo("Sink filling completed. Writing the filled raster to the output file...")

            # Write the filled DEM to the output raster
            try:
                writer = QgsRasterFileWriter(output_raster_path)
                pipe = QgsRasterPipe()
                pipe.set(provider.clone())
                writer.writeRaster(pipe, width, height, extent, raster_layer.crs())
            except Exception as e:
                raise QgsProcessingException(f"Error writing filled raster to output file: {e}")

            feedback.pushInfo("Filled raster written successfully.")
        except QgsProcessingException as e:
            feedback.reportError(f"Processing error: {e}")
            raise
        except Exception as e:
            feedback.reportError(f"Unexpected error: {e}")
            raise QgsProcessingException(f"Unexpected error: {e}")

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        """
        Main processing logic for detecting ponds.
        """
        # Retrieve the input raster
        input_raster = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
        if input_raster is None:
            raise QgsProcessingException("Invalid input raster")

        # Get the output paths
        filled_raster_path = self.parameterAsOutputLayer(parameters, self.OUTPUT_FILLED_RASTER, context)

        # Fill sinks in the raster
        feedback.pushInfo("Filling sinks in the raster using the Wang and Liu method...")
        self.fill_sinks(input_raster.dataProvider().dataSourceUri(), filled_raster_path, feedback)
        feedback.pushInfo("Sink filling completed.")

        # Create an empty vector layer for the output
        fields = QgsFields()
        fields.append(QgsField("ID", QVariant.Int))
        fields.append(QgsField("Volume", QVariant.Double))  # Placeholder for pond volume

        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT_VECTOR,
            context,
            fields,
            QgsWkbTypes.Polygon,
            input_raster.crs()
        )

        if sink is None:
            raise QgsProcessingException("Unable to create output vector layer")

        # Placeholder logic for detecting ponds (to be implemented in the next steps)
        feedback.pushInfo("Pond detection logic will be implemented in the next steps.")

        # Return the outputs
        return {
            self.OUTPUT_VECTOR: dest_id,
            self.OUTPUT_FILLED_RASTER: filled_raster_path
        }

    def createInstance(self):
        return self.__class__()

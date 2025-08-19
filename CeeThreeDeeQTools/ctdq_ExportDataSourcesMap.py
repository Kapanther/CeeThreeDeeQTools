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
from .support import ctdtool_info


class ExportDataSourcesMap(QgsProcessingAlgorithm):
    TOOL_NAME = "ExportDataSourcesMap"
    """
    Exports a layer containing bounding boxes and metadata for all layers in the project.
    """

    EXTENTS_LAYER_NAME = "Extents"
    OUTPUT = "OUTPUT"

    def name(self):
        return self.TOOL_NAME

    def displayName(self):
        return ctdtool_info[self.TOOL_NAME]["disp"]

    def group(self):
        return ctdtool_info[self.TOOL_NAME]["group"]

    def groupId(self):
        return ctdtool_info[self.TOOL_NAME]["group_id"]

    def shortHelpString(self) -> str:
        """
        Returns a localised short helper string for the algorithm. This string
        should provide a basic description about what the algorithm does and the
        parameters and outputs associated with it.
        """
        return "Exports a layer containing bounding boxes and metadata for all layers in the project."

    def initAlgorithm(self, config: Optional[dict[str, Any]] = None):
        """
        Define the output parameter for the location of the final "Extents" layer.
        """
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT,
                "Output Extents Layer",                
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
        Create an "Extents" layer containing bounding boxes and metadata for all layers in the project.
        """

        # Retrieve the output file path
        output_layer = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        # Retrieve the project instance and all map layers
        project = QgsProject.instance()
        layers = project.mapLayers().values()

        # Get the project name and set the extents layer name
        project_name = project.baseName() or "project"
        extents_layer_name = f"{project_name}_datasources"

        # Create fields for the new "Extents" layer
        fields = QgsFields()
        fields.append(QgsField("layer_name", QVariant.String))
        fields.append(QgsField("crs", QVariant.String))
        fields.append(QgsField("source", QVariant.String))
        fields.append(QgsField("geom_type", QVariant.String))
        fields.append(QgsField("feature_count", QVariant.Int))

        # Retrieve the project CRS
        project_crs = project.crs()

        # Create a temporary in-memory layer for storing extents using the project's CRS
        extents_layer = QgsVectorLayer(
            f"Polygon?crs={project_crs.authid()}", extents_layer_name, "memory"
        )
        extents_layer.dataProvider().addAttributes(fields)
        extents_layer.updateFields()

        # Determine the current view extent
        if iface.mapCanvas():
            current_extent = iface.mapCanvas().extent()
            feedback.pushInfo(f"Using map canvas extent: {current_extent.toString()}")
        else:
            feedback.pushInfo("Map canvas not available. Using project's full extent as fallback.")
            current_extent = project.extent()

        # Iterate through all layers in the project
        for layer in layers:
            if isinstance(layer, QgsVectorLayer):
                # Process vector layers
                layer_name = layer.name()
                layer_crs = layer.crs() if layer.crs().isValid() else project_crs
                crs = layer_crs.authid()
                source = layer.source()
                geom_type = QgsWkbTypes.displayString(layer.wkbType())
                feature_count = layer.featureCount()

                # Check if the layer has geometry
                if not layer.isSpatial():
                    # Use the current view extent if the layer has no geometry
                    feedback.pushInfo(f"Layer '{layer_name}' is non-spatial. Using current view extent.")
                    bbox = QgsGeometry.fromRect(current_extent)
                else:
                    # Calculate the bounding box for layers with geometry
                    extent = layer.extent()
                    bbox = QgsGeometry.fromRect(extent)

            elif isinstance(layer, QgsRasterLayer):
                # Process raster layers
                layer_name = layer.name()
                layer_crs = layer.crs() if layer.crs().isValid() else project_crs
                crs = layer_crs.authid()
                source = layer.source()
                geom_type = "Raster"
                feature_count = 0  # Raster layers do not have features

                # Calculate the bounding box for the raster layer
                extent = layer.extent()
                bbox = QgsGeometry.fromRect(extent)

            else:
                # Skip unsupported layer types
                feedback.pushInfo(f"Skipping unsupported layer: {layer.name()}")
                continue

            # Create a new feature for the extents layer
            feature = QgsFeature()
            feature.setGeometry(bbox)
            feature.setAttributes([layer_name, crs, source, geom_type, feature_count])

            # Add the feature to the extents layer
            extents_layer.dataProvider().addFeature(feature)

            # Send feedback to the user
            feedback.pushInfo(f"Processed layer: {layer_name}")

            # Stop if the user cancels the operation
            if feedback.isCanceled():
                break

        # Export the extents layer to the output parameter
        options = QgsVectorFileWriter.SaveVectorOptions()
        error = QgsVectorFileWriter.writeAsVectorFormatV2(
            extents_layer,
            output_layer,  # Use the output layer path directly
            context.transformContext(),
            options,
        )

        if error[0] != QgsVectorFileWriter.NoError:
            raise QgsProcessingException(f"Failed to save the layer. Error code: {error[0]}")

        # Send feedback about the saved file
        feedback.pushInfo(f"Extents layer saved to: {output_layer}")

        # Return the output path
        return {self.OUTPUT: output_layer}

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return self.__class__()

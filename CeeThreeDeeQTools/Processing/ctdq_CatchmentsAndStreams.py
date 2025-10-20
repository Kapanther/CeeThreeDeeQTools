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
    QgsMessageLog,
    QgsCategorizedSymbolRenderer,
    QgsVectorFileWriter,
    QgsProcessingOutputLayerDefinition,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsProcessingUtils,
    QgsRasterLayer,  # Import QgsRasterLayer for raster support
    QgsFeatureSink,  # Import QgsFeatureSink for feature sink operations
    QgsSpatialIndex,  # Import QgsSpatialIndex for spatial indexing
    QgsFillSymbol,  # Import for creating fill symbols
    QgsGraduatedSymbolRenderer,  # Import for graduated symbol renderer
    QgsRendererCategory,  # Import for renderer categories
    QgsSymbol,  # Import for symbols
    QgsStyle,  # Import for color ramps
)
from qgis.utils import iface  # Import iface to access the map canvas
from PyQt5.QtCore import QVariant, QCoreApplication
from PyQt5.QtGui import QColor  # Import QColor for random colors
from .ctdq_AlgoRun import ctdqAlgoRun  # <-- Add this import to fix the missing base class
from ..ctdq_support import ctdprocessing_command_info
from ..Functions import ctdq_raster_functions
import processing  # Import processing for running algorithms


class CatchmentsAndStreams(ctdqAlgoRun):
    TOOL_NAME = "CatchmentsAndStreams"
    """
    Generates both catchments and stream vectors from a DEM. Streams also contain stream order (both Strahler and Shreve) and catchments are linked to streams.
    """

    INPUT_DEM = "INPUT_DEM"
    INPUT_THRESHOLD = "INPUT_THRESHOLD"
    INPUT_WATERSHED_THRESHOLD = "INPUT_WATERSHED_THRESHOLD"
    SMOOTH_ITERATIONS = "SMOOTH_ITERATIONS"
    SMOOTH_OFFSET = "SMOOTH_OFFSET"
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

    def initAlgorithm(self, config=None):
        """
        Define the output parameter for the location of the final "Extents" layer.
        """
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_DEM,
                "Input DEM Raster",
                optional=False
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.INPUT_THRESHOLD,
                "Flow Threshold",
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=4000
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.INPUT_WATERSHED_THRESHOLD,
                "Watershed Threshold",
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=10000
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.SMOOTH_ITERATIONS,
                "Smoothing Iterations",
                type=QgsProcessingParameterNumber.Integer,
                minValue=1, maxValue=10, defaultValue=3
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.SMOOTH_OFFSET,
                "Smoothing Offset",
                type=QgsProcessingParameterNumber.Double,
                minValue=0, maxValue=0.5, defaultValue=0.25
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
            input_dem = self.parameterAsRasterLayer(parameters, self.INPUT_DEM, context)
            input_threshold = self.parameterAsDouble(parameters, self.INPUT_THRESHOLD, context)
            input_watershed_threshold = self.parameterAsDouble(parameters, self.INPUT_WATERSHED_THRESHOLD, context)
            smooth_iterations = self.parameterAsInt(parameters, self.SMOOTH_ITERATIONS, context)
            smooth_offset = self.parameterAsDouble(parameters, self.SMOOTH_OFFSET, context)

            # Use a multi-step feedback, so that individual child algorithm progress reports are adjusted for the
            # overall progress through the model
            feedback = QgsProcessingMultiStepFeedback(6, model_feedback)

            # generate a fill direction raster using the DEM
            
            dem_filled = processing.run("grass7:r.fill.dir", {
                'input': input_dem,
                'output': QgsProcessing.TEMPORARY_OUTPUT,
                'direction': QgsProcessing.TEMPORARY_OUTPUT,
                'areas': QgsProcessing.TEMPORARY_OUTPUT,
                'format': 0
            }, context=context, feedback=feedback)['output']

            grass_watershed = processing.run("grass7:r.watershed", {
                'elevation': dem_filled,
                'accumulation': QgsProcessing.TEMPORARY_OUTPUT,
                'drainage': QgsProcessing.TEMPORARY_OUTPUT,
                'basin': QgsProcessing.TEMPORARY_OUTPUT,
                'threshold': input_watershed_threshold,
                '-s': True,
                '-m': True
            }, context=context, feedback=feedback)

            grass_flow_accumulation = grass_watershed['accumulation']            

            streams = processing.run("grass7:r.stream.extract", {
                'elevation': dem_filled,
                'accumulation': grass_flow_accumulation,
                'threshold': input_threshold,
                'stream_vector': QgsProcessing.TEMPORARY_OUTPUT,
                'stream_raster': QgsProcessing.TEMPORARY_OUTPUT,
                'direction': QgsProcessing.TEMPORARY_OUTPUT,
                'GRASS_OUTPUT_TYPE_PARAMETER': 2
            }, context=context, feedback=feedback)['stream_vector']

            grass_basins = grass_watershed['basin']

            basins = processing.run("grass7:r.to.vect", {
                'input': grass_basins,
                'type': 2, # area
                'output': QgsProcessing.TEMPORARY_OUTPUT
            }, context=context, feedback=feedback)['output']

            # Apply smoothing
            smoothed_streams = processing.run("native:smoothgeometry", {
                'INPUT': streams,
                'ITERATIONS': smooth_iterations,
                'OFFSET': smooth_offset,
                'MAX_ANGLE': 180,
                'OUTPUT': 'memory:'
            }, context=context, feedback=feedback)['OUTPUT']

            smoothed_basins = processing.run("native:smoothgeometry", {
                'INPUT': basins,
                'ITERATIONS': smooth_iterations,
                'OFFSET': smooth_offset,
                'MAX_ANGLE': 180,
                'OUTPUT': 'memory:'
            }, context=context, feedback=feedback)['OUTPUT']

            ordered_streams = self.calculate_stream_orders(smoothed_streams, context, feedback)
            
            # Join catchments with stream network attribute
            joined_catchments = processing.run("native:joinattributesbylocation", {
                'INPUT': smoothed_basins,
                'JOIN': ordered_streams,
                'PREDICATE': [0],  # intersects
                'JOIN_FIELDS': ['network'],  # only take the network field
                'METHOD': 2,  # take attributes of the largest overlapping feature
                'DISCARD_NONMATCHING': False,
                'PREFIX': '',
                'OUTPUT': 'memory:'
            }, context=context, feedback=feedback)['OUTPUT']
            
            stream_sink,stream_dest_id = self.parameterAsSink(parameters,self.OUTPUT_STREAMS,context,
                                                              ordered_streams.fields(),QgsWkbTypes.LineString,input_dem.crs())
            if stream_sink is None:
                raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_STREAMS))

            # Create catchments sink
            catchments_sink, catchments_dest_id = self.parameterAsSink(parameters, self.OUTPUT_CATCHMENTS, context,
                                                                      joined_catchments.fields(), QgsWkbTypes.Polygon, input_dem.crs())
            if catchments_sink is None:
                raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_CATCHMENTS))

            feature_count = ordered_streams.featureCount()
            for current, f in enumerate(ordered_streams.getFeatures()):
                if feedback.isCanceled():
                    break
                stream_sink.addFeature(f, QgsFeatureSink.FastInsert)
                feedback.setProgress(int((current + 1) / feature_count * 100))

            # Add catchments features to sink
            catchment_feature_count = joined_catchments.featureCount()
            for current, f in enumerate(joined_catchments.getFeatures()):
                if feedback.isCanceled():
                    break
                catchments_sink.addFeature(f, QgsFeatureSink.FastInsert)
                feedback.setProgress(int((current + 1) / catchment_feature_count * 100))

            # Use inherited helper to register LayerPostProcessor for styling
            self.load_outputs = True
            display_name = "Stream Network"
            
            try:
                # Create graduated symbol renderer for streams based on Shreve order
                streams_renderer = QgsGraduatedSymbolRenderer()
                streams_renderer.setClassAttribute("Shreve")
                
                # Try to set up the renderer with classes
                try:
                    streams_renderer.updateClasses(ordered_streams, QgsGraduatedSymbolRenderer.Quantile, 5)
                except Exception:
                    # Fallback if updateClasses fails
                    pass
                
                # Apply Viridis color ramp
                try:
                    viridis_ramp = QgsStyle().defaultStyle().colorRamp("Viridis")
                    if viridis_ramp and hasattr(streams_renderer, "updateColorRamp"):
                        streams_renderer.updateColorRamp(viridis_ramp)
                except Exception as e:
                    feedback.pushInfo(f"Could not apply Viridis color ramp: {e}")
                
                self.handle_post_processing(
                    "OUTPUT_STREAMS",
                    stream_dest_id,
                    display_name,
                    context,
                    streams_renderer,  # graduated renderer
                    None,  # no categorized renderer
                    "Shreve"  # color_ramp_field
                )
                feedback.pushInfo("Registered stream network with Shreve-based Viridis styling.")
            except Exception as e:
                feedback.pushWarning(f"Could not apply styling to stream network: {e}")

            # Style catchments with blue outline only
            catchments_display_name = "Catchments"
            try:
                # Create a transparent fill symbol with light grey outline
                catchments_symbol = QgsFillSymbol.createSimple({
                    'color': '128,128,128,128',  # 50% transparent grey fill
                    'outline_color': '200,200,200,255',  # Light grey outline
                    'outline_width': '0.05',
                    'outline_style': 'solid'
                })

                # Create categorized renderer for catchments based on network field
                categories = []
                unique_values = joined_catchments.uniqueValues(joined_catchments.fields().indexFromName("network"))
                
                for i, value in enumerate(unique_values):
                    if value is not None:
                        # Create a copy of the symbol with different color
                        category_symbol = catchments_symbol.clone()
                        # Generate a random-ish color based on the value hash
                        import random
                        random.seed(hash(str(value)))
                        color = QColor.fromHsv(random.randint(0, 359), 180, 200, 128)
                        category_symbol.setColor(color)
                        
                        category = QgsRendererCategory(value, category_symbol, str(value))
                        categories.append(category)
                
                catchments_renderer = QgsCategorizedSymbolRenderer("network", categories)

                self.handle_post_processing(
                    "OUTPUT_CATCHMENTS",
                    catchments_dest_id,
                    catchments_display_name,
                    context,
                    None,  # no graduated renderer
                    catchments_renderer,  # use random color ramp for categorized rendering
                    "network"  # categorize by network field
                )
                feedback.pushInfo("Registered catchments with network-based categorized styling.")
            except Exception as e:
                feedback.pushWarning(f"Could not apply styling to catchments: {e}")

            # Return the output paths
            return {
                self.OUTPUT_STREAMS: stream_dest_id,
                self.OUTPUT_CATCHMENTS: catchments_dest_id
            }
        except Exception as e:
            raise QgsProcessingException(f"Error in {self.TOOL_NAME}: {e}")
        
    def calculate_stream_orders(self, stream_layer, context, feedback):
        try:
            if isinstance(stream_layer, str):
                layer = QgsVectorLayer(stream_layer, "Streams", "ogr")
            elif isinstance(stream_layer, QgsVectorLayer):
                layer = stream_layer
            else:
                raise QgsProcessingException(self.tr('Invalid stream layer type'))
            
            if not layer.isValid():
                raise QgsProcessingException(self.tr('Invalid stream layer'))
            
            layer_provider = layer.dataProvider()
            
            # Add Strahler and Shreve order fields if they don't exist
            fields_to_add = []
            if layer.fields().indexFromName("Strahler") == -1:
                fields_to_add.append(QgsField("Strahler", QVariant.Int))
            if layer.fields().indexFromName("Shreve") == -1:
                fields_to_add.append(QgsField("Shreve", QVariant.Int))
            
            if fields_to_add:
                layer_provider.addAttributes(fields_to_add)
                layer.updateFields()
            
            index = QgsSpatialIndex(layer.getFeatures())
            outlets = [f for f in layer.getFeatures() if self.is_valid_feature(f) and not self.find_downstream_features(f, index, layer)]
            
            layer.startEditing()
            total_features = len(outlets)
            for current, outlet in enumerate(outlets):
                if feedback.isCanceled():
                    break
                self.get_stream_orders(outlet, layer, index)
                feedback.setProgress(int((current + 1) / total_features * 100))
            layer.commitChanges()
            return layer
        except Exception as e:
            QgsMessageLog.logMessage(f"Error in calculate_stream_orders: {str(e)}", level=Qgis.Critical)
            raise

    def get_stream_orders(self, feature, layer, index):
        try:
            upstream_features = self.find_upstream_features(feature, index, layer)
            if not upstream_features:
                feature['Strahler'] = 1
                feature['Shreve'] = 1
                layer.updateFeature(feature)
                return 1, 1
            else:
                upstream_orders = [self.get_stream_orders(f, layer, index) for f in upstream_features]
                max_strahler = max([order[0] for order in upstream_orders])
                strahler = max_strahler + 1 if [order[0] for order in upstream_orders].count(max_strahler) > 1 else max_strahler
                shreve = sum([order[1] for order in upstream_orders])
                feature['Strahler'] = strahler
                feature['Shreve'] = shreve
                layer.updateFeature(feature)
                return strahler, shreve
        except Exception as e:
            QgsMessageLog.logMessage(f"Error in get_stream_orders: {str(e)}", level=Qgis.Critical)
            raise

    def find_upstream_features(self, feature, index, layer):
        try:
            if not self.is_valid_feature(feature):
                return []
            start_point = self.get_start_point(feature.geometry())
            if start_point is None:
                return []
            return [f for f in self.get_nearby_features(start_point, index, layer)
                    if f.id() != feature.id() and self.get_end_point(f.geometry()) == start_point]
        except Exception as e:
            QgsMessageLog.logMessage(f"Error in find_upstream_features: {str(e)}", level=Qgis.Critical)
            return []

    def find_downstream_features(self, feature, index, layer):
        try:
            if not self.is_valid_feature(feature):
                return []
            end_point = self.get_end_point(feature.geometry())
            if end_point is None:
                return []
            return [f for f in self.get_nearby_features(end_point, index, layer)
                    if f.id() != feature.id() and self.get_start_point(f.geometry()) == end_point]
        except Exception as e:
            QgsMessageLog.logMessage(f"Error in find_downstream_features: {str(e)}", level=Qgis.Critical)
            return []

    def is_valid_feature(self, feature):
        return feature.geometry() is not None and not feature.geometry().isNull() and feature.geometry().isGeosValid()

    def get_start_point(self, geometry):
        if geometry.type() == QgsWkbTypes.LineGeometry:
            return geometry.asPolyline()[0] if geometry.asPolyline() else None
        elif geometry.type() == QgsWkbTypes.MultiLineGeometry:
            lines = geometry.asMultiPolyline()
            return lines[0][0] if lines else None
        return None

    def get_end_point(self, geometry):
        if geometry.type() == QgsWkbTypes.LineGeometry:
            return geometry.asPolyline()[-1] if geometry.asPolyline() else None
        elif geometry.type() == QgsWkbTypes.MultiLineGeometry:
            lines = geometry.asMultiPolyline()
            return lines[-1][-1] if lines else None
        return None

    def get_nearby_features(self, point, index, layer):
        return [layer.getFeature(fid) for fid in index.nearestNeighbor(point, 5)]
    
    def tr(self, string):

        return QCoreApplication.translate('Processing', string)
    def createInstance(self):
        return self.__class__()

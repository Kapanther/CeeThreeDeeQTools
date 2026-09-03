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
    QgsVectorLayer,
    QgsRasterLayer,
    QgsField,
    QgsWkbTypes,
    QgsProcessingParameterVectorDestination,
    QgsProcessingParameterRasterDestination,  # Import QgsProcessingParameterRasterDestination for raster output
    QgsProcessingParameterRasterLayer,  # Import QgsProcessingParameterRasterLayer for raster input
    QgsProcessingParameterNumber,  # Import QgsProcessingParameterNumber for numeric input
    QgsProcessingParameterBoolean,
    QgsProcessingException,
    QgsProcessingUtils,
    Qgis,
    QgsClassificationQuantile,
    QgsMessageLog,
    QgsCategorizedSymbolRenderer,
    QgsClassificationMethod,
    QgsFeatureSink,  # Import QgsFeatureSink for feature sink operations
    QgsSpatialIndex,  # Import QgsSpatialIndex for spatial indexing
    QgsFillSymbol,  # Import for creating fill symbols
    QgsGraduatedSymbolRenderer,  # Import for graduated symbol renderer
    QgsRendererCategory,  # Import for renderer categories
    QgsSymbol,  # Import for symbols
    QgsStyle,  # Import for color ramps
    QgsPalLayerSettings,  # Import for labeling
    QgsVectorLayerSimpleLabeling,  # Import for simple labeling
    QgsTextFormat,  # Import for text formatting
    QgsTextBufferSettings,  # Import for text buffer
)
from qgis.utils import iface  # Import iface to access the map canvas
from qgis.PyQt.QtCore import QMetaType, QCoreApplication
from qgis.PyQt.QtGui import QColor  # Import QColor for random colors
from .ctdq_AlgoRun import ctdqAlgoRun  # <-- Add this import to fix the missing base class
from .ctdq_AlgoSymbology import PostVectorSymbology  # Import the new symbology class
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
    IGNORE_DEPRESSIONS = "IGNORE_DEPRESSIONS"
    IGNORE_SMALL_DEPRESSIONS = "ignoreSmallDepressions"
    BREACH_MAX_LENGTH = "BREACH_MAX_LENGTH"
    DEPRESSION_MIN_DEPTH = "DEPRESSION_MIN_DEPTH"
    SMOOTH_ITERATIONS = "SMOOTH_ITERATIONS"
    SMOOTH_OFFSET = "SMOOTH_OFFSET"
    OUTPUT_CATCHMENTS = "OUTPUT_CATCHMENTS"
    OUTPUT_STREAMS = "OUTPUT_STREAMS"
    OUTPUT_NETWORKS = "OUTPUT_NETWORKS"
    OUTPUT_DEPRESSION_RASTER = "OUTPUT_DEPRESSION_RASTER"

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
                "Catchment Threshold",
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=10000
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.IGNORE_DEPRESSIONS,
                "Ignore Depressions",
                defaultValue=True
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.IGNORE_SMALL_DEPRESSIONS,
                "Ignore Small Depressions",
                defaultValue=True
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.BREACH_MAX_LENGTH,
                "Maximum Depression Breach Length (cells)",
                type=QgsProcessingParameterNumber.Integer,
                minValue=1,
                maxValue=500,
                defaultValue=50
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.DEPRESSION_MIN_DEPTH,
                "Minimum Depression Depth",
                type=QgsProcessingParameterNumber.Double,
                minValue=0.0,
                defaultValue=0.1
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

        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT_NETWORKS,
                "Output Networks Layer",
                type=QgsProcessing.TypeVectorPolygon,
                createByDefault=True,
                defaultValue=None
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT_DEPRESSION_RASTER,
                "Output Depression Raster (optional)",
                createByDefault=False,
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
            ignore_depressions = self.parameterAsBool(parameters, self.IGNORE_DEPRESSIONS, context)
            ignore_small_depressions = self.parameterAsBool(
                parameters, self.IGNORE_SMALL_DEPRESSIONS, context
            )
            breach_max_length = self.parameterAsInt(parameters, self.BREACH_MAX_LENGTH, context)
            depression_min_depth = self.parameterAsDouble(
                parameters, self.DEPRESSION_MIN_DEPTH, context
            )
            smooth_iterations = self.parameterAsInt(parameters, self.SMOOTH_ITERATIONS, context)
            smooth_offset = self.parameterAsDouble(parameters, self.SMOOTH_OFFSET, context)
            depression_output = self.parameterAsOutputLayer(
                parameters, self.OUTPUT_DEPRESSION_RASTER, context
            )
                
            # Use a multi-step feedback, so that individual child algorithm progress reports are adjusted for the
            # overall progress through the model
            feedback = QgsProcessingMultiStepFeedback(7, model_feedback)

            if ignore_depressions:
                dem_filled = input_dem
                depression_raster = None
                feedback.pushInfo(
                    "Ignoring depressions; using the input DEM unchanged and skipping "
                    "sink-map generation."
                )
            else:
                if ignore_small_depressions:
                    dem_filled = input_dem
                    depression_source = input_dem
                    feedback.pushInfo(
                        "Ignoring small depressions; generating the depression map "
                        "from the original DEM."
                    )
                else:
                    # Breach local pits while preserving broad closed basins.
                    feedback.pushInfo("Breaching small DEM depressions...")
                    dem_filled = ctdq_raster_functions.CtdqRasterFunctions.ctdq_raster_breach_depressions(
                        input_dem,
                        feedback,
                        max_length=breach_max_length,
                    )
                    if not dem_filled or not os.path.exists(dem_filled):
                        raise QgsProcessingException(
                            f"Depression-breached DEM was not created: {dem_filled}"
                        )
                    depression_source = QgsRasterLayer(
                        dem_filled, "Depression-breached DEM"
                    )
                    if not depression_source.isValid():
                        raise QgsProcessingException(
                            f"Depression-breached DEM cannot be opened: {dem_filled}"
                        )
                    feedback.pushInfo(
                        f"Validated depression-breached DEM: {depression_source.width()} x "
                        f"{depression_source.height()} cells"
                    )

                filled_dem = ctdq_raster_functions.CtdqRasterFunctions.ctdq_raster_fillsinks(
                    depression_source,
                    feedback,
                )
                if filled_dem is None:
                    raise QgsProcessingException("Could not create sink-filled DEM for depression mapping")
                depression_raster = ctdq_raster_functions.CtdqRasterFunctions.ctdq_raster_create_depression_mask(
                    depression_source,
                    filled_dem,
                    feedback,
                    depression_min_depth,
                )

                if not depression_raster or not os.path.exists(depression_raster):
                    raise QgsProcessingException(
                        f"Depression raster was not created: {depression_raster}"
                    )
                else:
                    feedback.pushInfo(
                        f"Created depression raster: {depression_raster}"
                    )
                
                depression_layer = QgsRasterLayer(depression_raster, "Depressions")
                if not depression_layer.isValid():
                    raise QgsProcessingException(
                        f"Depression raster cannot be opened: {depression_raster}"
                    )
                feedback.pushInfo(
                    f"Validated depression raster: {depression_layer.width()} x "
                    f"{depression_layer.height()} cells"
                )
                if depression_output:
                    depression_output = ctdq_raster_functions.CtdqRasterFunctions.ctdq_raster_copy(
                        depression_raster,
                        depression_output,
                        feedback,
                    )
                    if depression_output is None:
                        raise QgsProcessingException(
                            "Could not write the requested depression raster output"
                        )

            watershed_parameters = {
                'elevation': dem_filled,
                'accumulation': QgsProcessing.TEMPORARY_OUTPUT,
                'drainage': QgsProcessing.TEMPORARY_OUTPUT,
                'basin': QgsProcessing.TEMPORARY_OUTPUT,
                'threshold': input_watershed_threshold,
                '-s': True,
                '-m': True,
            }
            if depression_raster is not None:
                watershed_parameters['depression'] = depression_raster

            grass_watershed = self._run_child_algorithm(
                "grass7:r.watershed",
                watershed_parameters,
                context=context,
                feedback=feedback,
            )

            grass_flow_accumulation = grass_watershed['accumulation']            

            streams = self._run_child_algorithm("grass7:r.stream.extract", {
                'elevation': dem_filled,
                'accumulation': grass_flow_accumulation,
                'threshold': input_threshold,
                'stream_vector': QgsProcessing.TEMPORARY_OUTPUT,
                'stream_raster': QgsProcessing.TEMPORARY_OUTPUT,
                'direction': QgsProcessing.TEMPORARY_OUTPUT,
                'GRASS_OUTPUT_TYPE_PARAMETER': 2
            }, context=context, feedback=feedback)['stream_vector']

            grass_basins = grass_watershed['basin']

            basins = self._run_child_algorithm("grass7:r.to.vect", {
                'input': grass_basins,
                'type': 2, # area
                'output': QgsProcessing.TEMPORARY_OUTPUT
            }, context=context, feedback=feedback)['output']

            # Apply smoothing
            smoothed_streams = self._run_child_algorithm("native:smoothgeometry", {
                'INPUT': streams,
                'ITERATIONS': smooth_iterations,
                'OFFSET': smooth_offset,
                'MAX_ANGLE': 180,
                'OUTPUT': 'memory:'
            }, context=context, feedback=feedback)['OUTPUT']

            # Apply generalization to catchments using GRASS v.generalize with snakes method
            generalized_basins = self._run_child_algorithm("grass7:v.generalize", {
                'input': basins,
                'type': 2,  # areas only
                'method': 10,  # snakes method
                'threshold': 1,
                'look_ahead': 7,
                'reduction': 50,
                'slide': 0.5,
                'angle_thresh': 3,
                'degree_thresh': 0,
                'closeness_thresh': 0,
                'betweeness_thresh': 0,
                'alpha': 1,
                'beta': 1,
                'iterations': 1,
                'cats': '',
                'where': '',
                '-t': False,
                '-l': True,
                'output': QgsProcessing.TEMPORARY_OUTPUT,
                'error': QgsProcessing.TEMPORARY_OUTPUT
            }, context=context, feedback=feedback)['output']

            # Fix geometries after generalization to handle any invalid geometries
            feedback.pushInfo("Fixing geometries after generalization...")
            smoothed_basins = self._run_child_algorithm("native:fixgeometries", {
                'INPUT': generalized_basins,
                'OUTPUT': 'memory:'
            }, context=context, feedback=feedback)['OUTPUT']

            ordered_streams = self.calculate_stream_orders(smoothed_streams, context, feedback)
            
            # Join catchments with stream network attribute
            joined_catchments = self._run_child_algorithm("native:joinattributesbylocation", {
                'INPUT': smoothed_basins,
                'JOIN': ordered_streams,
                'PREDICATE': [0],  # intersects
                'JOIN_FIELDS': ['network'],  # only take the network field
                'METHOD': 2,  # take attributes of the largest overlapping feature
                'DISCARD_NONMATCHING': False,
                'PREFIX': '',
                'OUTPUT': 'memory:'
            }, context=context, feedback=feedback)['OUTPUT']
            joined_catchments = QgsProcessingUtils.mapLayerFromString(
                joined_catchments, context
            )
            
            # Dissolve catchments by network field to create networks
            networks = self._run_child_algorithm("native:dissolve", {
                'INPUT': joined_catchments,
                'FIELD': ['network'],
                'OUTPUT': 'memory:'
            }, context=context, feedback=feedback)['OUTPUT']
            networks = QgsProcessingUtils.mapLayerFromString(networks, context)

            if joined_catchments is None or not joined_catchments.isValid():
                raise QgsProcessingException("Joined catchments layer is invalid")
            if networks is None or not networks.isValid():
                raise QgsProcessingException("Networks layer is invalid")

            stream_sink,stream_dest_id = self.parameterAsSink(parameters,self.OUTPUT_STREAMS,context,
                                                              ordered_streams.fields(),QgsWkbTypes.LineString,input_dem.crs())
            if stream_sink is None:
                raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_STREAMS))

            # Create catchments sink
            catchments_sink, catchments_dest_id = self.parameterAsSink(parameters, self.OUTPUT_CATCHMENTS, context,
                                                                      joined_catchments.fields(), QgsWkbTypes.Polygon, input_dem.crs())
            if catchments_sink is None:
                raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_CATCHMENTS))

            # Create networks sink
            networks_sink, networks_dest_id = self.parameterAsSink(parameters, self.OUTPUT_NETWORKS, context,
                                                                  networks.fields(), QgsWkbTypes.Polygon, input_dem.crs())
            if networks_sink is None:
                raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_NETWORKS))

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

            # Add networks features to sink
            networks_feature_count = networks.featureCount()
            for current, f in enumerate(networks.getFeatures()):
                if feedback.isCanceled():
                    break
                networks_sink.addFeature(f, QgsFeatureSink.FastInsert)
                feedback.setProgress(int((current + 1) / networks_feature_count * 100))

            # Use inherited helper to register LayerPostProcessor for styling
            self.load_outputs = True
            display_name = "Stream Network"
            
            try:
                # Create symbology for streams
                stream_symbology = PostVectorSymbology().set_graduated_renderer("Shreve", "Viridis")
                
                self.handle_post_processing(
                    "OUTPUT_STREAMS",
                    stream_dest_id,
                    display_name,
                    context,
                    stream_symbology
                )
                feedback.pushInfo("Registered stream network with Shreve-based Viridis styling.")
            except Exception as e:
                feedback.pushWarning(f"Could not apply styling to stream network: {e}")

            # Style catchments with categorized renderer
            catchments_display_name = "Catchments"
            try:
                # Create symbology for catchments with random colors by network
                catchment_symbology = PostVectorSymbology().set_categorized_renderer("network", generate_random_colors=True)

                self.handle_post_processing(
                    "OUTPUT_CATCHMENTS",
                    catchments_dest_id,
                    catchments_display_name,
                    context,
                    catchment_symbology
                )
                feedback.pushInfo("Registered catchments with network-based categorized styling.")
            except Exception as e:
                feedback.pushWarning(f"Could not apply styling to catchments: {e}")

            # Style networks with blue outline and labels
            networks_display_name = "Networks"
            try:
                # Create symbology for networks
                network_symbology = (PostVectorSymbology()
                    .set_simple_outline(outline_color="0,0,255,255", outline_width="0.6")
                    .set_labeling("network", force_inside_polygon=True))

                self.handle_post_processing(
                    "OUTPUT_NETWORKS",
                    networks_dest_id,
                    networks_display_name,
                    context,
                    network_symbology
                )
                feedback.pushInfo("Registered networks with blue outline styling and labels.")
            except Exception as e:
                feedback.pushWarning(f"Could not apply styling to networks: {e}")

            # Return the output paths
            return {
                self.OUTPUT_STREAMS: stream_dest_id,
                self.OUTPUT_CATCHMENTS: catchments_dest_id,
                self.OUTPUT_NETWORKS: networks_dest_id,
                self.OUTPUT_DEPRESSION_RASTER: depression_output,
            }
        except Exception as e:
            raise QgsProcessingException(f"Error in {self.TOOL_NAME}: {e}")
        
    def _run_child_algorithm(self, algorithm_id, parameters, context, feedback):
        """Run a child algorithm and fail immediately when an output is missing."""
        feedback.pushInfo(f"Running {algorithm_id}...")
        QgsMessageLog.logMessage(
            f"CatchmentsAndStreams: starting {algorithm_id}",
            "CeeThreeDeeQTools",
            Qgis.Info,
        )

        try:
            result = processing.run(
                algorithm_id,
                parameters,
                context=context,
                feedback=feedback,
                is_child_algorithm=True,
            )
        except Exception as error:
            message = f"{algorithm_id} failed: {error}"
            feedback.reportError(message)
            QgsMessageLog.logMessage(message, "CeeThreeDeeQTools", Qgis.Critical)
            raise QgsProcessingException(message) from error

        for output_name, output_value in result.items():
            feedback.pushInfo(
                f"{algorithm_id} returned {output_name}: {output_value}"
            )
            QgsMessageLog.logMessage(
                f"CatchmentsAndStreams: {algorithm_id} returned "
                f"{output_name}={output_value}",
                "CeeThreeDeeQTools",
                Qgis.Info,
            )

            if output_name == "error" or output_value in (None, ""):
                continue
            if isinstance(output_value, str):
                if os.path.exists(output_value):
                    file_size = os.path.getsize(output_value)
                    if file_size == 0:
                        message = (
                            f"{algorithm_id} created an empty output for '{output_name}': "
                            f"{output_value}"
                        )
                        feedback.reportError(message)
                        QgsMessageLog.logMessage(
                            message, "CeeThreeDeeQTools", Qgis.Critical
                        )
                        raise QgsProcessingException(message)

                    if output_value.lower().endswith(('.tif', '.tiff')):
                        layer = QgsRasterLayer(output_value, output_name)
                        if not layer.isValid():
                            message = (
                                f"{algorithm_id} created a raster that QGIS cannot open "
                                f"for '{output_name}': {output_value}"
                            )
                            feedback.reportError(message)
                            QgsMessageLog.logMessage(
                                message, "CeeThreeDeeQTools", Qgis.Critical
                            )
                            raise QgsProcessingException(message)
                        feedback.pushInfo(
                            f"Validated raster {output_name}: {file_size} bytes, "
                            f"{layer.width()} x {layer.height()} cells"
                        )
                    elif output_value.lower().endswith(('.gpkg', '.shp')):
                        layer = QgsVectorLayer(output_value, output_name, "ogr")
                        if not layer.isValid():
                            message = (
                                f"{algorithm_id} created a vector layer that QGIS cannot "
                                f"open for '{output_name}': {output_value}"
                            )
                            feedback.reportError(message)
                            QgsMessageLog.logMessage(
                                message, "CeeThreeDeeQTools", Qgis.Critical
                            )
                            raise QgsProcessingException(message)
                        feedback.pushInfo(
                            f"Validated vector {output_name}: {file_size} bytes, "
                            f"{layer.featureCount()} features"
                        )
                else:
                    layer = QgsProcessingUtils.mapLayerFromString(output_value, context)
                    if layer is None or not layer.isValid():
                        message = (
                            f"{algorithm_id} returned '{output_name}' as neither an "
                            f"existing file nor a valid processing layer: {output_value}"
                        )
                        feedback.reportError(message)
                        QgsMessageLog.logMessage(
                            message, "CeeThreeDeeQTools", Qgis.Critical
                        )
                        raise QgsProcessingException(message)
                    feedback.pushInfo(
                        f"Validated in-memory layer {output_name}: "
                        f"{layer.name()} ({layer.featureCount()} features)"
                    )
            elif hasattr(output_value, "isValid") and not output_value.isValid():
                message = f"{algorithm_id} returned an invalid layer for '{output_name}'"
                feedback.reportError(message)
                QgsMessageLog.logMessage(
                    message, "CeeThreeDeeQTools", Qgis.Critical
                )
                raise QgsProcessingException(message)

        return result

    def calculate_stream_orders(self, stream_layer, context, feedback):
        try:
            if isinstance(stream_layer, str):
                layer = QgsProcessingUtils.mapLayerFromString(stream_layer, context)
                if layer is None:
                    layer = QgsVectorLayer(stream_layer, "Streams", "ogr")
            elif isinstance(stream_layer, QgsVectorLayer):
                layer = stream_layer
            else:
                raise QgsProcessingException(self.tr('Invalid stream layer type'))
            
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                raise QgsProcessingException(self.tr('Invalid stream layer'))
            
            layer_provider = layer.dataProvider()
            
            # Add Strahler and Shreve order fields if they don't exist
            fields_to_add = []
            if layer.fields().indexFromName("Strahler") == -1:
                fields_to_add.append(QgsField("Strahler", QMetaType.Type.Int))
            if layer.fields().indexFromName("Shreve") == -1:
                fields_to_add.append(QgsField("Shreve", QMetaType.Type.Int))
            
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

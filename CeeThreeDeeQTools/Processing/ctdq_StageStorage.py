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
    QgsProcessingFeatureSourceDefinition,
    QgsField,
    QgsFields,  # Import QgsFields to fix the error
    QgsFeature,
    QgsWkbTypes,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterVectorDestination,
    QgsProcessingParameterRasterLayer,
    QgsProcessingException,
    QgsVectorFileWriter,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFeatureSource,  # Import QgsProcessingParameterFeatureSource for vector layer input
    QgsGraduatedSymbolRenderer,  # Import QgsGraduatedSymbolRenderer for graduated styling
    QgsStyle,  # Import QgsStyle for color ramp
    QgsFeatureRequest,  # Import QgsFeatureRequest for materialize
)
from qgis.utils import iface  # Import iface to access the map canvas
from PyQt5.QtCore import QCoreApplication, QMetaType
from ..ctdq_support import ctdprocessing_command_info, ctdprocessing_settingsdefaults, CTDQSupport
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
    POND_ID_FIELD = "POND_ID_FIELD"
    OUTPUT_HTML_REPORT = "OUTPUT_HTML_REPORT"

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
                self.INPUT_RASTER,
                "Input Ground Raster",
                optional=False      
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_PONDS_VECTOR,
                self.tr("Input Ponds Vector Layer"),
                types=[QgsWkbTypes.PolygonGeometry],
                optional=False
            )
        )

        # Replace the field selection parameter with a text input box
        self.addParameter(
            QgsProcessingParameterField(
                self.INPUT_PONDS_RL_FIELD,
                self.tr("Input Ponds RL Field"),
                None,
                self.INPUT_PONDS_VECTOR,
                QgsProcessingParameterField.Numeric,
                allowMultiple=False,
                optional=False            
            )
        )

        # Add a parameter for the pond ID field name
        self.addParameter(
            QgsProcessingParameterField(
                self.POND_ID_FIELD,
                self.tr("Input Pond ID Field"),
                None,
                self.INPUT_PONDS_VECTOR,
                QgsProcessingParameterField.Any,
                allowMultiple=False,
                optional=False                
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

        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_HTML_REPORT,
                "Output HTML Report (Optional)",
                fileFilter="HTML files (*.html)",
                optional=True
            )
        )

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        """
        Process each pond polygon individually to calculate stage storage.
        """
        # Retrieve parameters
        ground_raster = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
        
        # Handle QgsProcessingFeatureSourceDefinition (may include selectedFeaturesOnly)
        raw_ponds_param = parameters.get(self.INPUT_PONDS_VECTOR)
        selected_only = False
        if isinstance(raw_ponds_param, QgsProcessingFeatureSourceDefinition):
            selected_only = bool(raw_ponds_param.selectedFeaturesOnly)
            feedback.pushInfo(f"Selected features only: {selected_only}")
        
        # Get the ponds source and layer
        ponds_source = self.parameterAsSource(parameters, self.INPUT_PONDS_VECTOR, context)
        ponds_layer = self.parameterAsVectorLayer(parameters, self.INPUT_PONDS_VECTOR, context)
        
        # If parameterAsVectorLayer returns None, try to get it from the source
        if ponds_layer is None and ponds_source is not None:
            # Create a memory layer from the source
            ponds_layer = ponds_source.materialize(QgsFeatureRequest())
        
        rl_field = self.parameterAsString(parameters, self.INPUT_PONDS_RL_FIELD, context)
        storage_interval = self.parameterAsDouble(parameters, self.STORAGE_INTERVAL, context)
        output_layer = self.parameterAsOutputLayer(parameters, self.OUTPUT_STAGE_STORAGE, context)
        pond_id_field = self.parameterAsString(parameters, self.POND_ID_FIELD, context)
        output_html_report = self.parameterAsFile(parameters, self.OUTPUT_HTML_REPORT, context)
        
        # Get precision values from global settings with fallback to 3 decimal places
        precision_elevation = CTDQSupport.get_precision_setting_with_fallback("ctdq_precision_elevation", 3)
        precision_area = CTDQSupport.get_precision_setting_with_fallback("ctdq_precision_area", 3)
        precision_vol = CTDQSupport.get_precision_setting_with_fallback("ctdq_precision_volume", 3)
            
        feedback.pushInfo(f"Using precision settings - Elevation: {precision_elevation}, Area: {precision_area}, Volume: {precision_vol}")
        feedback.pushInfo(f"Using Pond ID Field: {pond_id_field}")

        if not ground_raster or not ponds_layer:
            raise QgsProcessingException("Both ground raster and ponds vector layer must be provided.")

        # Generate a unique identifier for this run
        run_uuid = uuid.uuid4().hex

        # Prepare the output layer
        feedback.pushInfo("Preparing output layer...")
        # Copy source fields excluding any named 'fid' (GeoPackage PK) to prevent UNIQUE constraint failures
        src_fields = ponds_layer.fields()
        output_fields = QgsFields()
        src_field_names_lower = []
        for f in src_fields:
            if f.name().lower() == "fid":
                feedback.pushInfo("Skipping source field 'fid' to avoid GeoPackage PK conflict.")
                continue
            output_fields.append(f)
            src_field_names_lower.append(f.name().lower())
        # Create fields using QMetaType
        output_fields.append(QgsField("ssMIN", QMetaType.Double))
        output_fields.append(QgsField("ssMAX", QMetaType.Double))  # ssMAX will be overridden with RLmax
        output_fields.append(QgsField("ssAREA", QMetaType.Double))
        output_fields.append(QgsField("ssINCVOL", QMetaType.Double))
        output_fields.append(QgsField("ssCUMVOL", QMetaType.Double))
        output_fields.append(QgsField("ssMINDPTH", QMetaType.Double))  # New field for minimum depth
        output_fields.append(QgsField("ssMAXDPTH", QMetaType.Double))  # New field for maximum depth
        save_opts = QgsVectorFileWriter.SaveVectorOptions()
        save_opts.driverName = "GPKG"
        save_opts.fileEncoding = "utf-8"
        writer_created = QgsVectorFileWriter.create(
            output_layer,
            output_fields,
            QgsWkbTypes.Polygon,
            ponds_layer.crs(),
            context.transformContext(),
            save_opts
        )
        writer = writer_created[0] if isinstance(writer_created, tuple) else writer_created
        if writer is None:
            raise QgsProcessingException("Failed to create output writer (GeoPackage).")
        # Pre-build list of retained source field names (order matches output_fields head)
        retained_src_fields = [f.name() for f in src_fields if f.name().lower() != "fid"]

        # Prepare data for the HTML report
        pond_reports = []

        # Process each pond feature
        feedback.pushInfo("Processing each pond polygon...")
        
        # Get features based on selectedFeaturesOnly flag
        if selected_only and ponds_source is not None:
            pond_features_iter = ponds_source.getFeatures()
            feedback.pushInfo("Using selected features only from input ponds layer.")
        elif ponds_layer is not None:
            pond_features_iter = ponds_layer.getFeatures()
        else:
            raise QgsProcessingException("Could not access ponds layer features.")
        
        for pond_feature in pond_features_iter:
            pond_id = pond_feature[pond_id_field]
            rl_max = pond_feature[rl_field]  # Retrieve RLmax from the pond feature
            feedback.pushInfo(f"Processing Pond ID: {pond_id} with RLmax: {rl_max}")

            # Create a temporary layer for the current pond polygon
            temp_current_pond = os.path.join(tempfile.gettempdir(), f"current_pond_{pond_id}_{run_uuid}.gpkg")
            ponds_layer.selectByExpression(f'"{pond_id_field}" = \'{pond_id}\'', QgsVectorLayer.SetSelection)
            QgsVectorFileWriter.writeAsVectorFormat(
                ponds_layer,
                temp_current_pond,
                "utf-8",
                ponds_layer.crs(),
                "GPKG",
                onlySelected=True
            )
            ponds_layer.removeSelection()

            # Calculate buffer distance as 2x the cell size of the input raster
            pixel_size_x = ground_raster.rasterUnitsPerPixelX()
            pixel_size_y = ground_raster.rasterUnitsPerPixelY()
            # Use the maximum of the two pixel sizes for the buffer distance
            buffer_distance = 2 * max(abs(pixel_size_x), abs(pixel_size_y))
            feedback.pushInfo(f"Using buffer distance: {buffer_distance} (2x max cell size)")

            # Create a buffered version of the current pond polygon to avoid square edges in contour polygons
            temp_buffered_pond = os.path.join(tempfile.gettempdir(), f"buffered_pond_{pond_id}_{run_uuid}.gpkg")
            feedback.pushInfo(f"Buffering pond polygon by {buffer_distance} units...")
            buffer_params = {
                'INPUT': temp_current_pond,
                'DISTANCE': buffer_distance,
                'SEGMENTS': 8,  # Number of segments for rounded corners
                'END_CAP_STYLE': 0,  # Round
                'JOIN_STYLE': 0,  # Round
                'MITER_LIMIT': 2,
                'DISSOLVE': False,
                'OUTPUT': temp_buffered_pond
            }
            processing.run("native:buffer", buffer_params, context=context, feedback=feedback)

            # Create a temporary file for the clipped raster
            temp_clipped_raster = os.path.join(tempfile.gettempdir(), f"clipped_raster_{pond_id}_{run_uuid}.tif")

            # Clip the ground raster to the buffered pond polygon (not the original)
            feedback.pushInfo(f"Clipping ground raster for Pond ID: {pond_id} using buffered polygon...")
            clip_params = {
                'INPUT': ground_raster.dataProvider().dataSourceUri(),
                'MASK': temp_buffered_pond,  # Use buffered pond instead of original
                'NODATA': -32567,
                'KEEP_RESOLUTION': True,
                'OUTPUT': temp_clipped_raster
            }
            processing.run("gdal:cliprasterbymasklayer", clip_params, context=context, feedback=feedback)

            # Generate contour polygons from the clipped raster
            temp_contour_polygons = os.path.join(tempfile.gettempdir(), f"contour_polygons_{pond_id}_{run_uuid}.gpkg")
            feedback.pushInfo(f"Generating contour polygons for Pond ID: {pond_id}...")
            contour_params = {
                'INPUT': temp_clipped_raster,
                'BAND': 1,
                'INTERVAL': storage_interval,
                'FIELD_NAME_MIN': 'ssMIN',
                'FIELD_NAME_MAX': 'ssMAX',
                'OFFSET': 0,
                # Use 2D to avoid geometry type mismatch with Polygon writer
                'CREATE_3D': False,
                'IGNORE_NODATA': False,
                'OUTPUT': temp_contour_polygons
            }
            processing.run("gdal:contour_polygon", contour_params, context=context, feedback=feedback)

            # Validate contour polygons
            contour_layer = QgsVectorLayer(temp_contour_polygons, f"Contour Polygons {pond_id}", "ogr")
            if not contour_layer.isValid() or contour_layer.featureCount() == 0:
                feedback.pushInfo(f"No valid contour polygons for Pond ID: {pond_id}. Skipping...")
                continue

            # Fix geometries in the contour polygons
            temp_fixed_contours = os.path.join(tempfile.gettempdir(), f"fixed_contours_{pond_id}_{run_uuid}.gpkg")
            feedback.pushInfo(f"Fixing geometries for Pond ID: {pond_id}...")
            fix_geometry_params = {
                'INPUT': contour_layer,
                'OUTPUT': temp_fixed_contours
            }
            processing.run("native:fixgeometries", fix_geometry_params, context=context, feedback=feedback)

            # Clip the fixed contour polygons back to the original pond boundary (not buffered)
            # This ensures we only calculate volumes within the actual pond area
            temp_clipped_contours = os.path.join(tempfile.gettempdir(), f"clipped_contours_{pond_id}_{run_uuid}.gpkg")
            feedback.pushInfo(f"Clipping contour polygons to original pond boundary for Pond ID: {pond_id}...")
            clip_contour_params = {
                'INPUT': temp_fixed_contours,
                'OVERLAY': temp_current_pond,  # Use original pond boundary, not buffered
                'OUTPUT': temp_clipped_contours
            }
            processing.run("native:clip", clip_contour_params, context=context, feedback=feedback)

            # Process clipped contour polygons to calculate ssAREA, ssINCVOL, and ssCUMVOL
            fixed_layer = QgsVectorLayer(temp_clipped_contours, f"Clipped Contours {pond_id}", "ogr")
            if not fixed_layer.isValid():
                feedback.pushInfo(f"Fixed contour layer is invalid for Pond ID: {pond_id}. Skipping...")
                continue
            
            #lets loop through the features and delete any that have a ssMIN that is greater than the pond RLmax
            features_to_delete = [f.id() for f in fixed_layer.getFeatures() if f["ssMIN"] > rl_max]
            if features_to_delete:
                fixed_layer.dataProvider().deleteFeatures(features_to_delete)
                feedback.pushInfo(f"Deleted {len(features_to_delete)} contour features with ssMIN greater than RLmax for Pond ID: {pond_id}.")

            # begin stage storage calculation
            feedback.pushInfo(f"Calculating stage storage for Pond ID: {pond_id}...")
            cumulative_area = 0.0
            cumulative_volume = 0.0
            previous_area = 0.0

            # Sort features by ssMIN in ascending order to ensure summation starts from the lowest level
            sorted_features = sorted(fixed_layer.getFeatures(), key=lambda f: f["ssMIN"])

            pond_data = []
            for i, contour_feature in enumerate(sorted_features):
                ss_min = contour_feature["ssMIN"]
                ss_max = contour_feature["ssMAX"]
                 
                 # Override ssMAX with RLmax only for the last range
                if i == len(sorted_features) - 1:
                    ss_max = rl_max

                area = contour_feature.geometry().area()

                # Calculate relative depths
                ss_min_depth = rl_max - ss_min  # Depth from RLmax to ssMIN
                ss_max_depth = rl_max - ss_max  # Depth from RLmax to ssMAX

                # Update cumulative area
                cumulative_area += area

                # Calculate incremental volume using the corrected formula
                height = ss_max - ss_min
                incremental_volume = ((previous_area + cumulative_area) / 2.0) * height

                # Update cumulative volume
                cumulative_volume += incremental_volume

                # Round results to specified precision
                ss_min = round(ss_min, precision_elevation)
                ss_max = round(ss_max, precision_elevation)
                ss_min_depth = round(ss_min_depth, precision_elevation)
                ss_max_depth = round(ss_max_depth, precision_elevation)
                area = round(area, precision_area)
                cumulative_area = round(cumulative_area, precision_area)
                incremental_volume = round(incremental_volume, precision_vol)
                cumulative_volume = round(cumulative_volume, precision_vol)

                # Create a new feature for the output layer
                new_feature = QgsFeature(output_fields)
                geom = contour_feature.geometry()
                if QgsWkbTypes.hasZ(geom.wkbType()):
                    geom = geom.make2D()
                new_feature.setGeometry(geom)
                # Build base attributes excluding any 'fid'
                base_attrs = [pond_feature[field_name] for field_name in retained_src_fields]
                new_feature.setAttributes(
                    base_attrs + [ss_min, ss_max, cumulative_area, incremental_volume, cumulative_volume, ss_min_depth, ss_max_depth]
                )
                new_feature.setId(-1)  # ensure provider assigns a fresh PK
                if not writer.addFeature(new_feature):
                    feedback.reportError(f"Failed to add feature (Pond {pond_id} ssMIN={ss_min} ssMAX={ss_max})")

                # Add data for the HTML report
                pond_data.append({
                    "Depth": ss_max_depth,
                    "RL": ss_max,
                    "Area": cumulative_area,
                    "IncVol": incremental_volume,
                    "CumVol": cumulative_volume
                })

                # Update previous area for the next iteration
                previous_area = cumulative_area

            # Sort pond data by highest elevation first
            pond_data = sorted(pond_data, key=lambda x: x["RL"], reverse=True)
            pond_reports.append({"PondID": pond_id, "Data": pond_data})

        # Generate the HTML report if requested
        if output_html_report:
            feedback.pushInfo(f"Generating HTML report at: {output_html_report}")
            with open(output_html_report, "w", encoding="utf-8") as html_file:
                html_file.write("<html><head><title>Stage Storage Report</title>")
                html_file.write("<style>")
                html_file.write("table { border-collapse: collapse; width: 100%; }")
                html_file.write("th, td { border: 1px solid black; padding: 8px; text-align: left; }")
                html_file.write("th { background-color: #f2f2f2; }")
                html_file.write("</style>")
                html_file.write("</head><body>")
                html_file.write("<h1>Stage Storage Report</h1>")

                for report in pond_reports:
                    html_file.write(f"<h2>Pond ID: {report['PondID']}</h2>")
                    html_file.write("<table>")
                    html_file.write("<thead><tr>")
                    html_file.write("<th>Depth</th><th>RL</th><th>Area</th><th>Inc. Vol</th><th>Cum. Vol</th>")
                    html_file.write("</tr></thead><tbody>")
                    for row in report["Data"]:
                        html_file.write(
                            f"<tr><td>{row['Depth']}</td><td>{row['RL']}</td><td>{row['Area']}</td>"
                            f"<td>{row['IncVol']}</td><td>{row['CumVol']}</td></tr>"
                        )
                    html_file.write("</tbody></table>")

                html_file.write("</body></html>")
            feedback.pushInfo("HTML report generated successfully.")

        # Finalize the output layer
        del writer
        feedback.pushInfo(f"Output stage storage layer saved to: {output_layer}")

        # Load the output layer path into a QgsVectorLayer for CRS/styling/add-to-project
        output_layer_obj = QgsVectorLayer(output_layer, "Output Stage Storage Slices", "ogr")
        if output_layer_obj.isValid():
            if output_layer_obj.crs() != ponds_layer.crs():
                feedback.pushInfo("Setting CRS of the output layer to match the ponds layer...")
                output_layer_obj.setCrs(ponds_layer.crs())

            # Apply graduated styling to the output layer (use non-deprecated factory)
            feedback.pushInfo("Applying graduated styling to the output layer...")
            renderer = QgsGraduatedSymbolRenderer.createRenderer(
                output_layer_obj,
                "ssMAXDPTH",
                QgsGraduatedSymbolRenderer.Quantile,
                5
            )
            color_ramp = QgsStyle().defaultStyle().colorRamp("Spectral")
            if color_ramp and renderer:
                renderer.updateColorRamp(color_ramp)
            if renderer:
                output_layer_obj.setRenderer(renderer)

            # Add the styled layer to the project
            QgsProject.instance().addMapLayer(output_layer_obj)
            feedback.pushInfo("Graduated styling applied using the 'ssMAXDPTH' field with the Spectral color scheme.")
        else:
            feedback.reportError("Output layer is invalid. CRS assignment and styling skipped.")

        # Deselect all features in the ponds layer
        ponds_layer.removeSelection()
        feedback.pushInfo("Deselected all features in the ponds layer.")

        return {
            self.OUTPUT_STAGE_STORAGE: output_layer,
            self.OUTPUT_HTML_REPORT: output_html_report
        }

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return self.__class__()
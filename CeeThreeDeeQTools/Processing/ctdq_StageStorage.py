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
    QgsFeatureRequest,  # Import QgsFeatureRequest for feature filtering
    QgsProcessingParameterDefinition,  # Import QgsProcessingParameterDefinition for advanced parameter flags
    QgsProcessingParameterFeatureSource,  # Import QgsProcessingParameterFeatureSource for vector layer input
    QgsGraduatedSymbolRenderer,  # Import QgsGraduatedSymbolRenderer for graduated styling
    QgsStyle,  # Import QgsStyle for color ramp
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
    POND_ID_FIELD = "POND_ID_FIELD"
    PRECISION_ELEVATION = "PRECISION_ELEVATION"
    PRECISION_AREA = "PRECISION_AREA"
    PRECISION_VOL = "PRECISION_VOL"
    OUTPUT_HTML_REPORT = "OUTPUT_HTML_REPORT"

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
                self.tr("Pond ID Field"),
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

        # Add advanced parameters for precision
        precision_elevation_param = QgsProcessingParameterNumber(
            self.PRECISION_ELEVATION,
            "Precision for Elevation",
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=2,
            optional=True
        )
        precision_elevation_param.setFlags(precision_elevation_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(precision_elevation_param)

        precision_area_param = QgsProcessingParameterNumber(
            self.PRECISION_AREA,
            "Precision for Area",
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=0,
            optional=True
        )
        precision_area_param.setFlags(precision_area_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(precision_area_param)

        precision_vol_param = QgsProcessingParameterNumber(
            self.PRECISION_VOL,
            "Precision for Volume",
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=0,
            optional=True
        )
        precision_vol_param.setFlags(precision_vol_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(precision_vol_param)

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
        ponds_layer = self.parameterAsVectorLayer(parameters, self.INPUT_PONDS_VECTOR, context)
        rl_field = self.parameterAsString(parameters, self.INPUT_PONDS_RL_FIELD, context)
        storage_interval = self.parameterAsDouble(parameters, self.STORAGE_INTERVAL, context)
        output_layer = self.parameterAsOutputLayer(parameters, self.OUTPUT_STAGE_STORAGE, context)
        pond_id_field = self.parameterAsString(parameters, self.POND_ID_FIELD, context)
        precision_elevation = self.parameterAsInt(parameters, self.PRECISION_ELEVATION, context)
        precision_area = self.parameterAsInt(parameters, self.PRECISION_AREA, context)
        precision_vol = self.parameterAsInt(parameters, self.PRECISION_VOL, context)
        output_html_report = self.parameterAsFile(parameters, self.OUTPUT_HTML_REPORT, context)
        feedback.pushInfo(f"Using Pond ID Field: {pond_id_field}")

        if not ground_raster or not ponds_layer:
            raise QgsProcessingException("Both ground raster and ponds vector layer must be provided.")

        # Generate a unique identifier for this run
        run_uuid = uuid.uuid4().hex

        # Prepare the output layer
        feedback.pushInfo("Preparing output layer...")
        output_fields = ponds_layer.fields()
        output_fields.append(QgsField("ssMIN", QVariant.Double))
        output_fields.append(QgsField("ssMAX", QVariant.Double))  # ssMAX will be overridden with RLmax
        output_fields.append(QgsField("ssAREA", QVariant.Double))
        output_fields.append(QgsField("ssINCVOL", QVariant.Double))
        output_fields.append(QgsField("ssCUMVOL", QVariant.Double))
        output_fields.append(QgsField("ssMINDPTH", QVariant.Double))  # New field for minimum depth
        output_fields.append(QgsField("ssMAXDPTH", QVariant.Double))  # New field for maximum depth
        writer = QgsVectorFileWriter(
            output_layer,
            "utf-8",
            output_fields,
            QgsWkbTypes.Polygon,
            ponds_layer.crs(),
            "GPKG"            
        )

        # Prepare data for the HTML report
        pond_reports = []

        # Process each pond feature
        feedback.pushInfo("Processing each pond polygon...")
        for pond_feature in ponds_layer.getFeatures():
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

            # Create a temporary file for the clipped raster
            temp_clipped_raster = os.path.join(tempfile.gettempdir(), f"clipped_raster_{pond_id}_{run_uuid}.tif")

            # Clip the ground raster to the current pond polygon
            feedback.pushInfo(f"Clipping ground raster for Pond ID: {pond_id}...")
            clip_params = {
                'INPUT': ground_raster.dataProvider().dataSourceUri(),
                'MASK': temp_current_pond,
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
                'CREATE_3D': True,
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

            # Process fixed contour polygons to calculate ssAREA, ssINCVOL, and ssCUMVOL
            fixed_layer = QgsVectorLayer(temp_fixed_contours, f"Fixed Contours {pond_id}", "ogr")
            if not fixed_layer.isValid():
                feedback.pushInfo(f"Fixed contour layer is invalid for Pond ID: {pond_id}. Skipping...")
                continue

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
                new_feature.setGeometry(contour_feature.geometry())
                new_feature.setAttributes(
                    pond_feature.attributes() +
                    [ss_min, ss_max, cumulative_area, incremental_volume, cumulative_volume, ss_min_depth, ss_max_depth]
                )
                writer.addFeature(new_feature)

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

        # Ensure the CRS of the output layer matches the ponds layer
        output_layer_obj = QgsVectorLayer(output_layer, "Output Stage Storage", "ogr")
        if (output_layer_obj.isValid()):
            if output_layer_obj.crs() != ponds_layer.crs():
                feedback.pushInfo("Setting CRS of the output layer to match the ponds layer...")
                output_layer_obj.setCrs(ponds_layer.crs())

            # Apply graduated styling to the output layer
            feedback.pushInfo("Applying graduated styling to the output layer...")
            renderer = QgsGraduatedSymbolRenderer()
            renderer.setClassAttribute("ssMAXDPTH")
            renderer.setMode(QgsGraduatedSymbolRenderer.Quantile)

            # Use the Spectral color ramp
            color_ramp = QgsStyle().defaultStyle().colorRamp("Spectral")
            if color_ramp:
                renderer.updateColorRamp(color_ramp)

            # Classify the layer into 5 classes
            renderer.updateClasses(output_layer_obj, QgsGraduatedSymbolRenderer.Quantile, 5)
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

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
    QgsProcessing,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingException,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterVectorDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterField,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsWkbTypes,
    QgsGeometry,
    QgsPointXY,
)
from PyQt5.QtCore import QVariant
from ..ctdq_support import ctdprocessing_command_info
from .ctdq_AlgoRun import ctdqAlgoRun


class PointsAlongPaths(ctdqAlgoRun):
    """
    Converts line features to point features along the line with customizable options.
    Maintains existing attributes from the line layer and adds a distance attribute.
    """
    TOOL_NAME = "PointsAlongPaths"
    
    # Parameter names
    INPUT_LINES = "INPUT_LINES"
    KEEP_EXISTING_VERTICES = "KEEP_EXISTING_VERTICES"
    INTERVAL_DISTANCE = "INTERVAL_DISTANCE"
    OFFSET_DISTANCE = "OFFSET_DISTANCE"
    START_DISTANCE_MODIFIER = "START_DISTANCE_MODIFIER"
    OUTPUT_POINTS = "OUTPUT_POINTS"

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

    def __init__(self):
        super().__init__()

    def initAlgorithm(self, configuration: Optional[dict[str, Any]] = None):
        """
        Define input and output parameters for the algorithm.
        """
        # Input line layer
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_LINES,
                self.tr("Input Line Layer"),
                types=[QgsWkbTypes.LineGeometry],
                optional=False
            )
        )

        # Keep existing vertices option
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.KEEP_EXISTING_VERTICES,
                self.tr("Keep Existing Vertices"),
                defaultValue=True,
                optional=False
            )
        )

        # Interval distance for creating points
        self.addParameter(
            QgsProcessingParameterNumber(
                self.INTERVAL_DISTANCE,
                self.tr("Interval Distance"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=10.0,
                minValue=0.0,
                optional=True
            )
        )

        # Interval distance field (optional - overrides constant if specified)
        self.addParameter(
            QgsProcessingParameterField(
                'INTERVAL_DISTANCE_FIELD',
                self.tr('Interval Distance Field (optional)'),
                None,
                self.INPUT_LINES,
                QgsProcessingParameterField.Numeric,
                optional=True
            )
        )

        # Offset distance (negative = left, positive = right)
        self.addParameter(
            QgsProcessingParameterNumber(
                self.OFFSET_DISTANCE,
                self.tr("Offset Distance (negative = left, positive = right)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                optional=True
            )
        )

        # Offset distance field (optional - overrides constant if specified)
        self.addParameter(
            QgsProcessingParameterField(
                'OFFSET_DISTANCE_FIELD',
                self.tr('Offset Distance Field (optional)'),
                None,
                self.INPUT_LINES,
                QgsProcessingParameterField.Numeric,
                optional=True
            )
        )

        # Start distance modifier
        self.addParameter(
            QgsProcessingParameterNumber(
                self.START_DISTANCE_MODIFIER,
                self.tr("Start Distance Modifier"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                optional=True
            )
        )

        # Start distance modifier field (optional - overrides constant if specified)
        self.addParameter(
            QgsProcessingParameterField(
                'START_DISTANCE_MODIFIER_FIELD',
                self.tr('Start Distance Modifier Field (optional)'),
                None,
                self.INPUT_LINES,
                QgsProcessingParameterField.Numeric,
                optional=True
            )
        )

        # Output point layer
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT_POINTS,
                self.tr("Output Points"),
                optional=False
            )
        )

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        """
        Process the line layer and create points along the paths.
        """
        # Retrieve parameters
        source = self.parameterAsSource(parameters, self.INPUT_LINES, context)
        keep_vertices = self.parameterAsBoolean(parameters, self.KEEP_EXISTING_VERTICES, context)
        
        # Get field names if specified, otherwise use constant values
        interval_field = self.parameterAsString(parameters, 'INTERVAL_DISTANCE_FIELD', context)
        offset_field = self.parameterAsString(parameters, 'OFFSET_DISTANCE_FIELD', context)
        start_modifier_field = self.parameterAsString(parameters, 'START_DISTANCE_MODIFIER_FIELD', context)
        
        # Default constant values (used when field not specified)
        default_interval = self.parameterAsDouble(parameters, self.INTERVAL_DISTANCE, context) if not interval_field else 10.0
        default_offset = self.parameterAsDouble(parameters, self.OFFSET_DISTANCE, context) if not offset_field else 0.0
        default_start_modifier = self.parameterAsDouble(parameters, self.START_DISTANCE_MODIFIER, context) if not start_modifier_field else 0.0

        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT_LINES))

        # Create output fields (copy from source + add distance field)
        fields = QgsFields(source.fields())
        fields.append(QgsField("distance", QVariant.Double))

        # Create the output layer writer
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT_POINTS,
            context,
            fields,
            QgsWkbTypes.Point,
            source.sourceCrs()
        )

        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_POINTS))

        # Process features
        total = 100.0 / source.featureCount() if source.featureCount() else 0
        features = source.getFeatures()

        for current, feature in enumerate(features):
            if feedback.isCanceled():
                break

            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                feedback.pushWarning(f"Feature {feature.id()} has no geometry, skipping")
                continue

            # Get per-feature parameter values from fields if specified
            interval = float(feature.attribute(interval_field)) if interval_field and feature.attribute(interval_field) is not None else default_interval
            offset = float(feature.attribute(offset_field)) if offset_field and feature.attribute(offset_field) is not None else default_offset
            start_modifier = float(feature.attribute(start_modifier_field)) if start_modifier_field and feature.attribute(start_modifier_field) is not None else default_start_modifier
            
            # Get the line geometry
            if geom.isMultipart():
                lines = geom.asMultiPolyline()
            else:
                lines = [geom.asPolyline()]

            # Process each line part
            for line in lines:
                if not line:
                    continue
                
                # Create a QgsLineString from the points
                line_geom = QgsGeometry.fromPolylineXY(line)
                
                # Generate points along the line
                points = self._generate_points_along_line(
                    line_geom,
                    keep_vertices,
                    interval,
                    offset,
                    start_modifier
                )

                # Create output features
                for point_data in points:
                    out_feature = QgsFeature(fields)
                    out_feature.setGeometry(QgsGeometry.fromPointXY(point_data['point']))
                    
                    # Copy attributes from source feature (skip fid to avoid duplicates)
                    for field in source.fields():
                        field_name = field.name()
                        if field_name.lower() != 'fid':
                            out_feature.setAttribute(field_name, feature.attribute(field_name))
                    
                    # Set distance attribute
                    out_feature.setAttribute("distance", point_data['distance'])
                    
                    sink.addFeature(out_feature)

            feedback.setProgress(int(current * total))

        feedback.pushInfo(f"Processing completed. {source.featureCount()} lines processed into points.")
        
        return {self.OUTPUT_POINTS: dest_id}

    def _generate_points_along_line(
        self,
        line_geom: QgsGeometry,
        keep_vertices: bool,
        interval: float,
        offset: float,
        start_modifier: float
    ) -> list:
        """
        Generate points along a line geometry.
        
        Args:
            line_geom: The line geometry
            keep_vertices: Whether to keep existing vertices
            interval: Distance interval for creating points
            offset: Offset distance from line (negative = left, positive = right)
            start_modifier: Value to add to distance attribute
            
        Returns:
            List of dicts with 'point' (QgsPointXY) and 'distance' (float)
        """
        points = []
        line_length = line_geom.length()
        
        # Collect distances where points should be created
        distances = []
        
        # Add existing vertices if requested
        if keep_vertices:
            vertices = line_geom.asPolyline()
            current_dist = 0.0
            for i in range(len(vertices)):
                if i == 0:
                    distances.append(0.0)
                else:
                    prev_pt = vertices[i - 1]
                    curr_pt = vertices[i]
                    segment_length = QgsGeometry.fromPointXY(prev_pt).distance(
                        QgsGeometry.fromPointXY(curr_pt)
                    )
                    current_dist += segment_length
                    if current_dist <= line_length:
                        distances.append(current_dist)
        
        # Add interval points
        if interval > 0:
            current_dist = 0.0
            while current_dist <= line_length:
                # Only add if not already in distances (to avoid duplicates with vertices)
                if not any(abs(d - current_dist) < 0.001 for d in distances):
                    distances.append(current_dist)
                current_dist += interval
        
        # Sort distances
        distances.sort()
        
        # Create points at each distance
        for dist in distances:
            if dist > line_length:
                continue
                
            # Get point at distance along line
            point_geom = line_geom.interpolate(dist)
            
            if point_geom.isEmpty():
                continue
            
            point = point_geom.asPoint()
            
            # Apply offset if needed
            if abs(offset) > 0.001:
                # Calculate offset point perpendicular to line
                point = self._offset_point(line_geom, dist, offset)
            
            # Add to results with modified distance
            points.append({
                'point': point,
                'distance': dist + start_modifier
            })
        
        return points

    def _offset_point(self, line_geom: QgsGeometry, distance: float, offset: float):
        """
        Calculate offset point perpendicular to line at given distance.
        
        Args:
            line_geom: The line geometry
            distance: Distance along line
            offset: Offset distance (negative = left, positive = right)
            
        Returns:
            QgsPointXY: The offset point
        """
        # Get point at distance
        point_geom = line_geom.interpolate(distance)
        if point_geom.isEmpty():
            return None
        
        point = point_geom.asPoint()
        
        # Get a small segment around this point to calculate perpendicular
        delta = 0.1  # Small distance for calculating direction
        
        # Get points before and after
        dist_before = max(0, distance - delta)
        dist_after = min(line_geom.length(), distance + delta)
        
        pt_before_geom = line_geom.interpolate(dist_before)
        pt_after_geom = line_geom.interpolate(dist_after)
        
        if pt_before_geom.isEmpty() or pt_after_geom.isEmpty():
            return point
        
        pt_before = pt_before_geom.asPoint()
        pt_after = pt_after_geom.asPoint()
        
        # Calculate direction vector
        dx = pt_after.x() - pt_before.x()
        dy = pt_after.y() - pt_before.y()
        
        # Normalize
        length = (dx * dx + dy * dy) ** 0.5
        if length < 0.0001:
            return point
        
        dx /= length
        dy /= length
        
        # Perpendicular vector (rotate 90 degrees)
        # Negative offset goes left, positive goes right
        perp_x = -dy * offset
        perp_y = dx * offset
        
        # Apply offset
        offset_point = QgsPointXY(point.x() + perp_x, point.y() + perp_y)
        
        return offset_point

    def createInstance(self):
        return PointsAlongPaths()
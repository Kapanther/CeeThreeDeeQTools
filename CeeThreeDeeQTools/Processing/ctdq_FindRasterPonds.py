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
    QgsProcessingParameterNumber
)
import xml.etree.ElementTree as ET
from xml.dom.minidom import parseString
from ..ctdq_support import ctdprocessing_info
import os
import heapq
import numpy as np

class FindRasterPonds(QgsProcessingAlgorithm):
    import heapq

    class PriorityQueue:
        def __init__(self):
            self.elements = []

        def empty(self):
            return not self.elements

        def put(self, item, priority):
            heapq.heappush(self.elements, (priority, item))

        def get(self):
            return heapq.heappop(self.elements)[1]
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
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """       
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                "GROUND_RASTER",
                "Ground Raster",
                optional=False
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                "MIN_DEPTH",
                "Minimum Pond Depth",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.5,
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
        Here is where the processing itself takes place.
        """        

        # Get input raster and output path
        input_raster = self.parameterAsRasterLayer(parameters, "GROUND_RASTER", context)
        output_raster_path = self.parameterAsString(parameters, self.OUTPUT, context)
        feedback.pushInfo(f"Input raster: {input_raster.name()}")
        feedback.pushInfo(f"Output raster path: {output_raster_path}")

        # Get raster properties
        provider = input_raster.dataProvider()
        extent = input_raster.extent()
        width = input_raster.width()
        height = input_raster.height()
        no_data_value = provider.sourceNoDataValue(1)

        # Read raster block
        block = provider.block(1, extent, width, height)
        dem = np.zeros((height, width), dtype=np.float32)
        for y in range(height):
            for x in range(width):
                value = block.value(x, y)
                dem[y, x] = value if value != no_data_value else -9999

        # Initialize priority queue and visited mask
        pq = self.PriorityQueue()
        visited = np.zeros((height, width), dtype=bool)
        for x in range(width):
            if dem[0, x] != -9999:
                pq.put((0, x), dem[0, x])
                visited[0, x] = True
            if dem[height-1, x] != -9999:
                pq.put((height-1, x), dem[height-1, x])
                visited[height-1, x] = True
        for y in range(1, height-1):
            if dem[y, 0] != -9999:
                pq.put((y, 0), dem[y, 0])
                visited[y, 0] = True
            if dem[y, width-1] != -9999:
                pq.put((y, width-1), dem[y, width-1])
                visited[y, width-1] = True

        # Main loop: process cells from the priority queue
        filled_dem = dem.copy()
        directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        while not pq.empty():
            y, x = pq.get()
            for dy, dx in directions:
                ny, nx = y + dy, x + dx
                if 0 <= ny < height and 0 <= nx < width:
                    if not visited[ny, nx] and dem[ny, nx] != -9999:
                        if filled_dem[ny, nx] < filled_dem[y, x]:
                            filled_dem[ny, nx] = filled_dem[y, x]
                        pq.put((ny, nx), filled_dem[ny, nx])
                        visited[ny, nx] = True

        # Write filled raster to disk
        from qgis.core import QgsRasterPipe, QgsRasterFileWriter
        pipe = QgsRasterPipe()
        pipe.set(provider.clone())
        writer = QgsRasterFileWriter(output_raster_path)
        writer.writeRaster(pipe, width, height, extent, input_raster.crs())
        feedback.pushInfo(f"Filled raster written to: {output_raster_path}")
        return {self.OUTPUT: output_raster_path}

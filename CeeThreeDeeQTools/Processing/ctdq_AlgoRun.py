# -*- coding: utf-8 -*-

"""
/***************************************************************************
CTDQ_ALOGbase
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

__author__ = "CeeThreeDeeQTools Development Team"
__date__ = "2025-10-09"
__copyright__ = "(C) 2025"

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = "$Format:%H$"

import os
from pathlib import Path
from json import load

from qgis.core import QgsVectorLayer, QgsProcessingException, QgsFillSymbol, QgsTextFormat, QgsTextBufferSettings,QgsGraduatedSymbolRenderer, QgsCategorizedSymbolRenderer

from .ctdq_AlgoBase import ctdqAlgoBase
from .ctdq_AlgoUtils import (
    LayerPostProcessor,
    select_group,
    create_group,
)


class ctdqAlgoRun(ctdqAlgoBase):
    """
    Base class for CTDQ Algorithms that run
    """    
    def __init__(self):
        super().__init__()
        # necessary to store LayerPostProcessor instances in class variable because of scoping issue
        self.styler_dict = {}
        self.load_outputs = False
        # default run name for grouping (ensure attribute exists for postProcessAlgorithm)
        try:
            self.run_name = self.name() if hasattr(self, "name") else self.__class__.__name__
        except Exception:
            self.run_name = self.__class__.__name__

    def group(self):
        return self.tr("Analysis")

    def groupId(self):
        return "analysis"

    def postProcessAlgorithm(self, context, feedback):
        if self.load_outputs:
            project = context.project()
            root = project.instance().layerTreeRoot()  # get base level node

            create_group(self.run_name, root)
            select_group(self.run_name)  # so that layers are spit out within group

        return {}

    def handle_post_processing(self,
                                entity: str,
                                layer_path: str, 
                                display_name: str,
                                context,
                                symbology=None
                                ) -> None:
        """
        Register a layer for post-processing with optional symbology.
        
        Args:
            entity: The parameter name (e.g., "OUTPUT_STREAMS")
            layer_path: The path to the layer
            display_name: The display name for the layer
            context: The processing context
            symbology: PostVectorSymbology or PostRasterSymbology object (optional)
        """
        layer_details = context.LayerDetails(
            display_name, context.project(), display_name
        )
        context.addLayerToLoadOnCompletion(
            layer_path,
            layer_details,
        )
        
        if context.willLoadLayerOnCompletion(layer_path):
            self.styler_dict[layer_path] = LayerPostProcessor(
                display_name, symbology
            )
            context.layerToLoadOnCompletionDetails(layer_path).setPostProcessor(
                self.styler_dict[layer_path]
            )
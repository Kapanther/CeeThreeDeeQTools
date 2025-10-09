# -*- coding: utf-8 -*-

"""
/***************************************************************************
 CTDQ_AlgoBase
Base class for all CTDQ algorithms
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
__date__ = "2025-10-08"
__copyright__ = "(C) 2025"

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = "$Format:%H$"

import os
import inspect

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsProcessingAlgorithm


class ctdqAlgoBase(QgsProcessingAlgorithm):
    """
    Base class for CTDQ Algorithms
    """

    _version = "0.3"

    def tr(self, string):
        return QCoreApplication.translate("Processing", string)
    
"""     def icon(self):

        #Returns the algorithm's icon.

        cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]
        icon = QIcon(
            os.path.join(os.path.dirname(cmd_folder), "resources/branding/icon.svg")
        )
        return icon 
"""


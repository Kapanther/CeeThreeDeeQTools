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
import os

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingParameterFile,
    QgsProcessingParameterEnum,
    QgsProcessingException,
)
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QFileDialog
from ..ctdq_support import ctdtool_info
import openpyxl


class ValidateProjectReport(QgsProcessingAlgorithm):
    TOOL_NAME = "ValidateProjectReport"

    EXTENTS_LAYER_NAME = "Validation Report"
    OUTPUT = "OUTPUT"
    EXCEL_FILE = "EXCEL_FILE"
    NAMED_RANGE = "NAMED_RANGE"
    LAYER_NAME_FIELD = "LAYER_NAME_FIELD"
    SOURCE_PATH_FIELD = "SOURCE_PATH_FIELD"

    def name(self):
        return self.TOOL_NAME

    def displayName(self):
        return ctdtool_info[self.TOOL_NAME]["disp"]

    def group(self):
        return ctdtool_info[self.TOOL_NAME]["group"]

    def groupId(self):
        return ctdtool_info[self.TOOL_NAME]["group_id"]

    def shortHelpString(self) -> str:
        return "Compares the layers in the current project to a table that contains a list of expected layers and data sources."

    def initAlgorithm(self, config: Optional[dict[str, Any]] = None):
        """
        Define the input parameters for the algorithm.
        """
        self.addParameter(
            QgsProcessingParameterFile(
                self.EXCEL_FILE,
                "Excel File",
                fileFilter="Excel files (*.xlsx *.xlsm)"
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.NAMED_RANGE,
                "Named Range",
                options=[],
                optional=True
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.LAYER_NAME_FIELD,
                "Layer Name Field",
                options=[],
                optional=True
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.SOURCE_PATH_FIELD,
                "Source Path Field",
                options=[],
                optional=True
            )
        )

    def prepareAlgorithm(self, parameters, context, feedback):
        """
        Prepare the algorithm by dynamically populating the named range options.
        """
        excel_file = self.parameterAsFile(parameters, self.EXCEL_FILE, context)
        if not excel_file:
            feedback.reportError("No Excel file specified.")
            return False

        try:
            workbook = openpyxl.load_workbook(excel_file, data_only=True)
            named_ranges = [name.name for name in workbook.defined_names.definedName]
            if not named_ranges:
                feedback.reportError("No named ranges found in the Excel file.")
                return False

            named_range_param = self.parameterDefinition(self.NAMED_RANGE)
            named_range_param.setOptions(named_ranges)
            feedback.pushInfo(f"Named ranges found: {named_ranges}")
        except Exception as e:
            feedback.reportError(f"Failed to read Excel file: {e}")
            return False

        return True

    def processAlgorithm(self, parameters, context: QgsProcessingContext, feedback: QgsProcessingFeedback):
        """
        Executes the algorithm to generate the validation report.
        """
        # Open the custom dialog
        dialog = ValidateProjectReportDialog()
        if dialog.exec_() == QDialog.Accepted:
            # Retrieve user inputs from the dialog
            excel_file = dialog.excel_file_edit.text()
            named_range = dialog.named_range_combo.currentText()
            layer_name_field = dialog.layer_name_combo.currentText()
            source_path_field = dialog.source_path_combo.currentText()

            feedback.pushInfo(f"Excel file: {excel_file}")
            feedback.pushInfo(f"Named range: {named_range}")
            feedback.pushInfo(f"Layer Name Field: {layer_name_field}")
            feedback.pushInfo(f"Source Path Field: {source_path_field}")

            # Placeholder implementation
            feedback.pushInfo("Processing algorithm started.")

            # Example: Return an empty dictionary as output
            return {self.OUTPUT: None}
        else:
            feedback.reportError("Operation canceled by the user.")
            return {self.OUTPUT: None}

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return self.__class__()

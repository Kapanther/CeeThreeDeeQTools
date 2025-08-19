"""
Generate catchments and streams with a minimum area using GRASS GIS tools.
This algorithm uses the r.watershed, r.to.vect, and v.generalize tools
to create catchment areas and stream lines based on a digital elevation model (DEM).
"""

from qgis.core import QgsProcessing
from qgis.core import QgsProcessingAlgorithm
from qgis.core import QgsProcessingMultiStepFeedback
from qgis.core import QgsProcessingParameterRasterLayer
from qgis.core import QgsProcessingParameterNumber
from qgis.core import QgsProcessingParameterVectorDestination
import processing
from PyQt5.QtCore import QCoreApplication
from .support import ctdtool_info


class GenerateCatchmentsMinArea(QgsProcessingAlgorithm):
    TOOL_NAME = "GenerateCatchmentsMinArea"

    def name(self):
        return self.TOOL_NAME

    def displayName(self):
        return ctdtool_info[self.TOOL_NAME]["disp"]

    def group(self):
        return ctdtool_info[self.TOOL_NAME]["group"]

    def groupId(self):
        return ctdtool_info[self.TOOL_NAME]["group_id"]
    
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer('eg', 'EG', defaultValue=None))
        self.addParameter(QgsProcessingParameterNumber('mincatchsize', 'Min Catch Size', type=QgsProcessingParameterNumber.Double, minValue=1000, maxValue=100000, defaultValue=20000))
        self.addParameter(QgsProcessingParameterVectorDestination('Streams', 'Streams', type=QgsProcessing.TypeVectorAnyGeometry, createByDefault=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterVectorDestination('Catchments', 'Catchments', type=QgsProcessing.TypeVectorAnyGeometry, createByDefault=True, defaultValue=None))

    def processAlgorithm(self, parameters, context, model_feedback):
        # Use a multi-step feedback, so that individual child algorithm progress reports are adjusted for the
        # overall progress through the model
        feedback = QgsProcessingMultiStepFeedback(6, model_feedback)
        results = {}
        outputs = {}

        # r.watershed
        alg_params = {
            '-4': False,
            '-a': False,
            '-b': False,
            '-m': False,
            '-s': False,
            'GRASS_RASTER_FORMAT_META': None,
            'GRASS_RASTER_FORMAT_OPT': None,
            'GRASS_REGION_CELLSIZE_PARAMETER': 0,
            'GRASS_REGION_PARAMETER': None,
            'blocking': None,
            'convergence': 5,
            'depression': None,
            'disturbed_land': None,
            'elevation': parameters['eg'],
            'flow': None,
            'max_slope_length': None,
            'memory': 300,
            'threshold': parameters['mincatchsize'],
            'basin': QgsProcessing.TEMPORARY_OUTPUT,
            'stream': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['Rwatershed'] = processing.run('grass7:r.watershed', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(1)
        if feedback.isCanceled():
            return {}

        # r.to.vect_catchments
        alg_params = {
            '-b': False,
            '-s': False,
            '-t': False,
            '-v': False,
            '-z': False,
            'GRASS_OUTPUT_TYPE_PARAMETER': 0,  # auto
            'GRASS_REGION_CELLSIZE_PARAMETER': 0,
            'GRASS_REGION_PARAMETER': None,
            'GRASS_VECTOR_DSCO': None,
            'GRASS_VECTOR_EXPORT_NOCAT': False,
            'GRASS_VECTOR_LCO': None,
            'column': 'value',
            'input': outputs['Rwatershed']['basin'],
            'type': 2,  # area
            'output': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['Rtovect_catchments'] = processing.run('grass7:r.to.vect', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(2)
        if feedback.isCanceled():
            return {}

        # r.thin
        alg_params = {
            'GRASS_RASTER_FORMAT_META': None,
            'GRASS_RASTER_FORMAT_OPT': None,
            'GRASS_REGION_CELLSIZE_PARAMETER': 0,
            'GRASS_REGION_PARAMETER': None,
            'input': outputs['Rwatershed']['stream'],
            'iterations': 200,
            'output': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['Rthin'] = processing.run('grass7:r.thin', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(3)
        if feedback.isCanceled():
            return {}

        # v.generalize_catchments
        alg_params = {
            '-l': True,
            '-t': False,
            'GRASS_MIN_AREA_PARAMETER': 0.0001,
            'GRASS_OUTPUT_TYPE_PARAMETER': 0,  # auto
            'GRASS_REGION_PARAMETER': None,
            'GRASS_SNAP_TOLERANCE_PARAMETER': -1,
            'GRASS_VECTOR_DSCO': None,
            'GRASS_VECTOR_EXPORT_NOCAT': False,
            'GRASS_VECTOR_LCO': None,
            'alpha': 1,
            'angle_thresh': 3,
            'beta': 1,
            'betweeness_thresh': 0,
            'cats': None,
            'closeness_thresh': 0,
            'degree_thresh': 0,
            'input': outputs['Rtovect_catchments']['output'],
            'iterations': 1,
            'look_ahead': 7,
            'method': 0,  # douglas
            'reduction': 50,
            'slide': 0.5,
            'threshold': 1,
            'type': 2,  # area
            'where': None,
            'error': QgsProcessing.TEMPORARY_OUTPUT,
            'output': parameters['Catchments']
        }
        outputs['Vgeneralize_catchments'] = processing.run('grass7:v.generalize', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        results['Catchments'] = outputs['Vgeneralize_catchments']['output']

        feedback.setCurrentStep(4)
        if feedback.isCanceled():
            return {}

        # r.to.vect_streams
        alg_params = {
            '-b': False,
            '-s': False,
            '-t': False,
            '-v': False,
            '-z': False,
            'GRASS_OUTPUT_TYPE_PARAMETER': 0,  # auto
            'GRASS_REGION_CELLSIZE_PARAMETER': 0,
            'GRASS_REGION_PARAMETER': None,
            'GRASS_VECTOR_DSCO': None,
            'GRASS_VECTOR_EXPORT_NOCAT': False,
            'GRASS_VECTOR_LCO': None,
            'column': 'value',
            'input': outputs['Rthin']['output'],
            'type': 0,  # line
            'output': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['Rtovect_streams'] = processing.run('grass7:r.to.vect', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(5)
        if feedback.isCanceled():
            return {}

        # v.generalize
        alg_params = {
            '-l': True,
            '-t': False,
            'GRASS_MIN_AREA_PARAMETER': 0.0001,
            'GRASS_OUTPUT_TYPE_PARAMETER': 0,  # auto
            'GRASS_REGION_PARAMETER': None,
            'GRASS_SNAP_TOLERANCE_PARAMETER': -1,
            'GRASS_VECTOR_DSCO': None,
            'GRASS_VECTOR_EXPORT_NOCAT': False,
            'GRASS_VECTOR_LCO': None,
            'alpha': 1,
            'angle_thresh': 3,
            'beta': 1,
            'betweeness_thresh': 0,
            'cats': None,
            'closeness_thresh': 0,
            'degree_thresh': 0,
            'input': outputs['Rtovect_streams']['output'],
            'iterations': 1,
            'look_ahead': 7,
            'method': 0,  # douglas
            'reduction': 50,
            'slide': 0.5,
            'threshold': 1,
            'type': [0],  # line
            'where': None,
            'error': QgsProcessing.TEMPORARY_OUTPUT,
            'output': parameters['Streams']
        }
        outputs['Vgeneralize'] = processing.run('grass7:v.generalize', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        results['Streams'] = outputs['Vgeneralize']['output']
        return results

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return GenerateCatchmentsMinArea()

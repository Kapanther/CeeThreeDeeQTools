import os
from pathlib import Path

# Import QGIS modules at the top level
try:
    from processing.core.ProcessingConfig import ProcessingConfig
    from qgis.core import QgsApplication
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False

ctdgroup_info = {
    1: {"group": "Projects", "group_id": "projects"},
    2: {"group": "Hydrology", "group_id": "hydrology"},
    3: {"group": "3D", "group_id": "3d"}
}

fop = '<font style="color:#CD5C5C;">' #font style for parameters (redish color)
foe = '<font style="color:#9400D3;">' #font style for emphasis (purple)
fcc = "</font>"                       #font style end

ctdprocessing_settingsdefaults = {
    "ctdq_precision_elevation": {
        "value": 2,
        "display_name": "Elevation Precision (decimal places)",
        "description": "Number of decimal places for elevation values"
    },
    "ctdq_precision_area": {
        "value": 0,
        "display_name": "Area Precision (decimal places)", 
        "description": "Number of decimal places for area values"
    },
    "ctdq_precision_volume": {
        "value": 0,
        "display_name": "Volume Precision (decimal places)",
        "description": "Number of decimal places for volume values"
    }
}

ctdprocessing_settingshelp_text = (
    "To change settings for precision of results go to the processing toolbox -> Settings(Cog Icon) -> Providers -> CeeThreeDeeQtools"
)

ctdprocessing_command_info = {    
    "ExportProjectLayerStyles": {
        "disp": "Export Project Layer Styles",
        "group": ctdgroup_info[1]["group"],
        "group_id": ctdgroup_info[1]["group_id"],
        "shortHelp": (
            "Exports the styles of all layers in the current QGIS project to a xml file and/or a directory of QML files that can be read in by other projects."
            "<h3>Parameters</h3>"
            "<ul>"
            f"<li>{fop}Output XML file:{fcc} Location to save XML file detailing styles details.</li>"
            f"<li>{fop}Output Directory for QMLS:{fcc} The directory where the layer QML files will be saved. If ByTheme is selected directories for each theme will be created in this location</li>"
            "</ul>"
            "<h3>Processing Settings</h3>"
            "<ul>"
            f"<li>{ctdprocessing_settingshelp_text}</li>"
        )
    },
    "ExportDataSourcesMap": {
        "disp": "Export Data Sources Map",
        "group": ctdgroup_info[1]["group"],
        "group_id": ctdgroup_info[1]["group_id"],
        "shortHelp": (
            "Generates a bounding box map of all layers used in the current QGIS project, each bounding box will contain details about the layer including path,CRS etc."
            "<h3>Parameters</h3>"
            "<ul>"
            f"<li>{fop}Output HTML file:{fcc} Location to save the HTML file which shows the Data Sources Map.</li>"
            f"<li>{fop}Output Table:{fcc} A table containing the details of each layer which can be exported into CAD programs as text.</li>"
            "</ul>"
            "<h3>Processing Settings</h3>"
            "<ul>"
            f"<li>{ctdprocessing_settingshelp_text}</li>"
        )
    },
    "GenerateCatchmentsMinArea": {
        "disp": "Generate Catchments - Min Area",
        "group": ctdgroup_info[2]["group"],
        "group_id": ctdgroup_info[2]["group_id"],
        "shortHelp": (
            "This tool generates catchments from a flow accumulation raster clipped to a boundary, it utilises GRASS commands to acheive the processing."
            "<h3>Parameters</h3>"
            "<ul>"
            f"<li>{fop}Input DEM:{fcc} A DEM to be processed.</li>"
            f"<li>{fop}Input Boundary Polygon:{fcc} A boundary to clip the DEM to before processing, leave blank to use the full extent.</li>"
            f"<li>{fop}Output Folder:{fcc} The output location for the individual raster and vector files created by the process.</li>"
            "</ul>"
            "<h3>Processing Settings</h3>"
            "<ul>"
            f"<li>{ctdprocessing_settingshelp_text}</li>"
        )
    },
    "FindRasterPonds": {
        "disp": "Find Raster Ponds",
        "group": ctdgroup_info[2]["group"],
        "group_id": ctdgroup_info[2]["group_id"],
        "shortHelp": (
            "Find potential ponds from a DEM by identifying depressions in a raster layer, will also compute volume/area and other key statistics for each pond."
            "<h3>Parameters</h3>"
            "<ul>"
            f"<li>{fop}Input DEM:{fcc} Digital Elevation Model to analyze for depressions(ponds) For larger jobs clip the raster to your area of interest first.</li>"
            f"<li>{fop}Output Ponds:{fcc} Output Vector layer containing potential pond locations, with pond volume/area and other statistics attached.</li>"            
            f"<li>{fop}Minimum Pond Area (m²):{fcc} Minimum area of ponds to detect, smaller ponds will be removed the result (default 2000m²).</li>"
            f"<li>{fop}Minimum Pond Depth (m):{fcc} Minimum depth of ponds to detect, shallower depressions will be ignored (default 0.1m). This is used to ignore small depressions that might have a large area</li>"
            "</ul>"
            "<h3>Optional Outputs (Off by default)</h3>"
            "<ul>"
            f"<li>{fop}Output Filled DEM:{fcc} Output Raster layer showing the DEM with depressions filled, possibly useful for other analyses.</li>"
            f"<li>{fop}Output Pond Depth Raster:{fcc} Output Raster layer showing the depth of each pond above the DEM surface.</li>"
            f"<li>{fop}Output Valid Pond Depth Raster:{fcc} Output Raster layer showing the depth of each pond above the DEM surface, with small/noisy depressions removed.</li>"
            "</ul>"
            "<h3>Processing Settings</h3>"
            "<ul>"
            f"<li>{ctdprocessing_settingshelp_text}</li>"
        )
    },
    "CalculateStageStoragePond": {
        "disp": "Calculate Stage Storage - Pond",
        "group": ctdgroup_info[2]["group"],
        "group_id": ctdgroup_info[2]["group_id"],
        "shortHelp": (
            "Calculate stage-storage curves for pond polygons."
            "<h3>Parameters</h3>"
            "<ul>"
            f"<li>{fop}Input Ground Raster:{fcc} DEM representing ground elevations.</li>"
            f"<li>{fop}Input Ponds Vector:{fcc} Polygon layer representing pond boundaries.</li>"
            f"<li>{fop}Storage Interval:{fcc} Elevation interval for volume calculations.</li>"
            "</ul>"
            "<h3>Processing Settings</h3>"
            "<ul>"
            f"<li>{ctdprocessing_settingshelp_text}</li>"
        )
    },
    "CatchmentsAndStreams": {
        "disp": "Generate Catchments and Streams",
        "group": ctdgroup_info[2]["group"],
        "group_id": ctdgroup_info[2]["group_id"],
        "shortHelp": (
            "Generates both catchments and stream vectors from a DEM. Streams also contain stream order (both Strahler and Shreve) and catchments are linked to streams."
            "<h3>Parameters</h3>"
            "<ul>"
            f"<li>{fop}Input DEM:{fcc} A DEM to be processed.</li>"
            f"<li>{fop}Output Catchments Layer:{fcc} The output polygon layer for the catchments.</li>"
            f"<li>{fop}Output Streams Layer:{fcc} The output line layer for the streams.</li>"
            "</ul>"
            "<h3>Processing Settings</h3>"
            "<ul>"
            f"<li>{ctdprocessing_settingshelp_text}</li>"
            "</ul>"
        )
    }

}


class CTDQSupport:
    """
    Support class for CeeThreeDee QTools with static utility methods.
    """
    
    @staticmethod
    def get_plugin_dir():
        """
        Returns the plugin directory.
        """
        return os.path.dirname(os.path.dirname(__file__))
    
    @staticmethod
    def get_global_precision_setting(setting_key, provider_name="CeeThreeDee Qtools"):
        """
        Get a global precision setting from QGIS Processing configuration.
        
        Args:
            setting_key: The key from ctdprocessing_settingsdefaults (e.g., 'precision_elevation')
            provider_name: The processing provider name
            
        Returns:
            The setting value, or the default value if not found
        """
        if not QGIS_AVAILABLE:
            return ctdprocessing_settingsdefaults.get(setting_key, {}).get("value", 3)
            
        try:
            setting_name = setting_key.upper()
            value = ProcessingConfig.getSetting(f"{provider_name}/{setting_name}")
            return value if value is not None else ctdprocessing_settingsdefaults[setting_key]["value"]
        except Exception:
            # Fallback to default if ProcessingConfig is not available
            return ctdprocessing_settingsdefaults.get(setting_key, {}).get("value", 3)
    
    @staticmethod
    def get_precision_setting_with_fallback(setting_key, fallback_value=3):
        """
        Get a global precision setting with a specific fallback value.
        
        Args:
            setting_key: The key from ctdprocessing_settingsdefaults (e.g., 'ctdq_precision_elevation')
            fallback_value: Value to use if setting cannot be retrieved (default: 3)
            
        Returns:
            The setting value, or the fallback_value if not found
        """
        if not QGIS_AVAILABLE:
            return ctdprocessing_settingsdefaults.get(setting_key, {}).get("value", fallback_value)
            
        try:
            # Use the setting key directly with CTDQ_ prefix (already uppercase)
            setting_name = setting_key.upper()
            value = ProcessingConfig.getSetting(setting_name)
            
            if value is not None and str(value).strip() != '':
                # Try to convert to int if it looks like a number
                try:
                    return int(value)
                except (ValueError, TypeError):
                    return value
            
            # Try the settings defaults
            if setting_key in ctdprocessing_settingsdefaults:
                return ctdprocessing_settingsdefaults[setting_key]["value"]
                
            return fallback_value
            
        except Exception:
            return fallback_value


# Backwards compatibility - create module-level functions that call the class methods
def get_plugin_dir():
    """Returns the plugin directory."""
    return CTDQSupport.get_plugin_dir()

def get_global_precision_setting(setting_key, provider_name="CeeThreeDee Qtools"):
    """Get a global precision setting from QGIS Processing configuration."""
    return CTDQSupport.get_global_precision_setting(setting_key, provider_name)

def get_precision_setting_with_fallback(setting_key, fallback_value=3):
    """Get a global precision setting with a specific fallback value."""
    return CTDQSupport.get_precision_setting_with_fallback(setting_key, fallback_value)


ctdpaths = {  
    "img": os.path.join(get_plugin_dir(), "assets", "img")
}
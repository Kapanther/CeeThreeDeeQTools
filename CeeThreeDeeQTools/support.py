import os
from pathlib import Path

ctdgroup_info = {
    1: {"group": "Projects", "group_id": "projects"},
    2: {"group": "Hydrology", "group_id": "hydrology"},
    3: {"group": "3D", "group_id": "3d"}
}
ctdtool_info = {    
    "ExportProjectStylesAsXML": {
        "disp": "Export Project Styles as XML",
        "group": ctdgroup_info[1]["group"],
        "group_id": ctdgroup_info[1]["group_id"]
    },
    "ExportDataSourcesMap": {
        "disp": "Export Data Sources Map",
        "group": ctdgroup_info[1]["group"],
        "group_id": ctdgroup_info[1]["group_id"]
    },
    "GenerateCatchmentsMinArea": {
        "disp": "Generate Catchments with Minimum Area",
        "group": ctdgroup_info[2]["group"],
        "group_id": ctdgroup_info[2]["group_id"]
    }
}

def get_plugin_dir():
    """
    Returns the plugin directory. This function should be called with
    self.plugin_dir from the provider or plugin class.
    """
    return os.path.dirname(os.path.dirname(__file__))

ctdpaths = {  
    "img": os.path.join(get_plugin_dir(), "assets", "img")
}
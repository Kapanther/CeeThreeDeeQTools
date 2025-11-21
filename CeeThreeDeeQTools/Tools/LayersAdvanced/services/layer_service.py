"""Service for layer operations and information retrieval."""

from qgis.core import (
    QgsProject, QgsMapLayer, QgsVectorLayer, QgsRasterLayer
)


class LayerService:
    """Handles layer information and operations."""
    
    @staticmethod
    def get_all_layers(project: QgsProject) -> list:
        """Get all layers from the project."""
        return list(project.mapLayers().values())
    
    @staticmethod
    def get_layer_type_string(layer: QgsMapLayer) -> str:
        """Get a human-readable string for the layer type."""
        if layer.type() == QgsMapLayer.VectorLayer:
            geom_type = layer.geometryType()
            geom_names = {
                0: "Point", 1: "Line", 2: "Polygon",
                3: "Unknown", 4: "Null"
            }
            return f"Vector ({geom_names.get(geom_type, 'Unknown')})"
        elif layer.type() == QgsMapLayer.RasterLayer:
            return "Raster"
        elif layer.type() == QgsMapLayer.PluginLayer:
            return "Plugin"
        elif layer.type() == QgsMapLayer.MeshLayer:
            return "Mesh"
        elif layer.type() == QgsMapLayer.VectorTileLayer:
            return "Vector Tile"
        else:
            return "Unknown"
    
    @staticmethod
    def get_layer_info(layer: QgsMapLayer) -> str:
        """Get basic information about a layer."""
        try:
            if isinstance(layer, QgsVectorLayer):
                count = layer.featureCount()
                return f"{count:,} features"
            elif isinstance(layer, QgsRasterLayer):
                width = layer.width()
                height = layer.height()
                return f"{width} x {height}"
        except Exception:
            pass
        return "-"
    
    @staticmethod
    def get_layer_info_dict(layer: QgsMapLayer) -> dict:
        """
        Get layer information as a dictionary.
        
        Returns:
            dict: Dictionary with 'type' and 'info' keys
        """
        return {
            'type': LayerService.get_layer_type_string(layer),
            'info': LayerService.get_layer_info(layer)
        }
    
    @staticmethod
    def get_detailed_layer_info(layer: QgsMapLayer) -> str:
        """Get detailed information about a layer for clipboard copy."""
        info_lines = []
        info_lines.append(f"Layer Name: {layer.name()}")
        info_lines.append(f"Layer Type: {LayerService.get_layer_type_string(layer)}")
        info_lines.append(f"Layer ID: {layer.id()}")
        
        try:
            info_lines.append(f"Source: {layer.source()}")
        except Exception:
            pass
        
        try:
            info_lines.append(f"Provider: {layer.providerType()}")
        except Exception:
            pass
        
        try:
            info_lines.append(f"CRS: {layer.crs().authid()}")
        except Exception:
            pass
        
        try:
            extent = layer.extent()
            info_lines.append(f"Extent: {extent.toString()}")
        except Exception:
            pass
        
        if isinstance(layer, QgsVectorLayer):
            try:
                info_lines.append(f"Feature Count: {layer.featureCount():,}")
            except Exception:
                pass
            
            try:
                fields = layer.fields()
                field_names = [f.name() for f in fields]
                info_lines.append(f"Fields: {', '.join(field_names)}")
            except Exception:
                pass
        
        elif isinstance(layer, QgsRasterLayer):
            try:
                info_lines.append(f"Dimensions: {layer.width()} x {layer.height()}")
            except Exception:
                pass
            
            try:
                info_lines.append(f"Band Count: {layer.bandCount()}")
            except Exception:
                pass
        
        return "\n".join(info_lines)

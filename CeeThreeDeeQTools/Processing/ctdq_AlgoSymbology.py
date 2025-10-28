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

from typing import Optional
from qgis.core import (
    QgsGraduatedSymbolRenderer,
    QgsCategorizedSymbolRenderer,
    QgsSingleSymbolRenderer,
    QgsVectorLayerSimpleLabeling,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsStyle,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsRendererCategory,
    Qgis,  # Import for label placement enums
)
from PyQt5.QtGui import QColor


class PostVectorSymbology:
    """
    Class to encapsulate vector layer symbology settings for post-processing.
    """
    
    def __init__(self):
        self.graduated_renderer: Optional[QgsGraduatedSymbolRenderer] = None
        self.categorized_renderer: Optional[QgsCategorizedSymbolRenderer] = None
        self.single_symbol_renderer: Optional[QgsSingleSymbolRenderer] = None
        self.labeling: Optional[QgsVectorLayerSimpleLabeling] = None
        self.color_ramp_field: Optional[str] = None
    
    def set_graduated_renderer(self, field_name: str, color_ramp_name: str = "Viridis"):
        """Create a graduated symbol renderer for the specified field."""
        self.graduated_renderer = QgsGraduatedSymbolRenderer()
        self.graduated_renderer.setClassAttribute(field_name)
        self.color_ramp_field = field_name
        
        try:
            color_ramp = QgsStyle().defaultStyle().colorRamp(color_ramp_name)
            if color_ramp and hasattr(self.graduated_renderer, "updateColorRamp"):
                self.graduated_renderer.updateColorRamp(color_ramp)
        except Exception:
            pass  # Fall back to default colors
        
        return self
    
    def set_categorized_renderer(self, field_name: str, categories: list = None, 
                                 generate_random_colors: bool = True):
        """Create a categorized symbol renderer for the specified field."""
        if categories:
            self.categorized_renderer = QgsCategorizedSymbolRenderer(field_name, categories)
        else:
            # Will be populated later with actual unique values
            self.categorized_renderer = QgsCategorizedSymbolRenderer(field_name, [])
        self.color_ramp_field = field_name
        return self
    
    def set_single_symbol_renderer(self, symbol: QgsFillSymbol or QgsLineSymbol or QgsMarkerSymbol):
        """Create a single symbol renderer with the specified symbol."""
        self.single_symbol_renderer = QgsSingleSymbolRenderer(symbol)
        return self
    
    def set_simple_outline(self, outline_color: str = "0,0,255,255", 
                          outline_width: str = "0.6",
                          fill_color: str = "255,255,255,0"):
        """Create a simple outline-only symbol."""
        symbol = QgsFillSymbol.createSimple({
            'color': fill_color,
            'outline_color': outline_color,
            'outline_width': outline_width,
            'outline_style': 'solid'
        })
        return self.set_single_symbol_renderer(symbol)
    
    def set_labeling(self, field_name: str, 
                    text_size: int = 10,
                    text_color: QColor = QColor(0, 0, 0),
                    buffer_enabled: bool = True,
                    buffer_size: float = 1.5,
                    buffer_color: QColor = QColor(255, 255, 255),
                    is_expression: bool = False,
                    force_inside_polygon: bool = False,
                    placement: str = "horizontal"):
        """Create labeling settings for the specified field or expression.
        
        Args:
            field_name: Field name or expression string
            text_size: Text size in points
            text_color: Color of the text
            buffer_enabled: Whether to enable text buffer
            buffer_size: Size of the text buffer
            buffer_color: Color of the text buffer
            is_expression: If True, treat field_name as an expression
            force_inside_polygon: If True, force labels to be placed inside polygon boundaries
            placement: Label placement mode ('horizontal', 'free', 'around_centroid', 'over_point')
        """
        label_settings = QgsPalLayerSettings()
        
        # Ensure field_name is a string
        if not isinstance(field_name, str):
            field_name = str(field_name)
        
        label_settings.fieldName = field_name
        # Auto-detect expressions or use explicit flag
        label_settings.isExpression = is_expression or ('||' in field_name or '+' in field_name or '"' in field_name)
        label_settings.enabled = True
        
        # Set placement mode based on geometry type
        placement_map = {
            'horizontal': QgsPalLayerSettings.Horizontal,
            'free': QgsPalLayerSettings.Free,
            'around_centroid': QgsPalLayerSettings.AroundPoint,
            'over_point': QgsPalLayerSettings.OverPoint,
            'ordered_positions_around_point': QgsPalLayerSettings.OrderedPositionsAroundPoint
        }
        
        if placement.lower() in placement_map:
            label_settings.placement = placement_map[placement.lower()]
        
        # Force labels inside polygon if requested
        if force_inside_polygon:
            # This setting ensures labels are kept within polygon boundaries
            label_settings.fitInPolygonOnly = True
        
        text_format = QgsTextFormat()
        text_format.setSize(text_size)
        text_format.setColor(text_color)
        
        if buffer_enabled:
            buffer_settings = QgsTextBufferSettings()
            buffer_settings.setEnabled(True)
            buffer_settings.setSize(buffer_size)
            buffer_settings.setColor(buffer_color)
            text_format.setBuffer(buffer_settings)
        
        label_settings.setFormat(text_format)
        self.labeling = QgsVectorLayerSimpleLabeling(label_settings)
        return self
    
    def get_renderer(self):
        """Get the appropriate renderer (prioritizes single > categorized > graduated)."""
        if self.single_symbol_renderer:
            return self.single_symbol_renderer
        elif self.categorized_renderer:
            return self.categorized_renderer
        elif self.graduated_renderer:
            return self.graduated_renderer
        return None


class PostRasterSymbology:
    """
    Class to encapsulate raster layer symbology settings for post-processing.
    """
    
    def __init__(self):
        # Placeholder for future raster symbology options
        self.color_ramp_name: Optional[str] = None
        self.min_value: Optional[float] = None
        self.max_value: Optional[float] = None
        self.classification_method: Optional[str] = None
    
    def set_color_ramp(self, color_ramp_name: str = "Viridis", 
                      min_value: float = None, 
                      max_value: float = None):
        """Set color ramp for raster styling."""
        self.color_ramp_name = color_ramp_name
        self.min_value = min_value
        self.max_value = max_value
        return self
    
    def set_classification(self, method: str = "quantile"):
        """Set classification method for raster styling."""
        self.classification_method = method
        return self

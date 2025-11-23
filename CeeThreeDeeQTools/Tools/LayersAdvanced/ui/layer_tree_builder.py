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

from qgis.PyQt.QtWidgets import QTreeWidgetItem, QWidget, QHBoxLayout, QLabel
from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QIcon, QPixmap, QPainter, QColor, QLinearGradient
from qgis.core import (
    QgsMapLayer,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsSymbol,
    QgsRendererCategory,
    QgsCategorizedSymbolRenderer,
    QgsSingleSymbolRenderer,
    QgsGraduatedSymbolRenderer,
    QgsRuleBasedRenderer,
    QgsPalettedRasterRenderer,
    QgsSingleBandPseudoColorRenderer,
    QgsSingleBandGrayRenderer,
    QgsMultiBandColorRenderer,
    QgsRasterContourRenderer
)
from ..services.layer_service import LayerService
from ..services.visibility_service import VisibilityService


class GradientWidget(QWidget):
    """Custom widget to display a color gradient with min/max labels."""
    
    def __init__(self, start_color, end_color, min_val, max_val, color_stops=None, parent=None):
        """
        Args:
            start_color: QColor for gradient start
            end_color: QColor for gradient end
            min_val: Minimum value to display
            max_val: Maximum value to display
            color_stops: Optional list of (position, QColor) tuples for multi-stop gradients (position 0.0-1.0)
            parent: Parent widget
        """
        super().__init__(parent)
        self.start_color = start_color
        self.end_color = end_color
        self.min_val = min_val
        self.max_val = max_val
        self.color_stops = color_stops  # List of (position, QColor) tuples
        self.setMinimumHeight(20)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Get widget dimensions
        width = self.width()
        height = self.height()
        
        # Set up font for measuring text
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        
        # Calculate text widths for positioning
        min_text = f"{self.min_val:.2f}"
        max_text = f"{self.max_val:.2f}"
        min_text_width = painter.fontMetrics().horizontalAdvance(min_text)
        max_text_width = painter.fontMetrics().horizontalAdvance(max_text)
        
        # Reserve space for text (5px padding on each side)
        text_padding = 5
        gradient_start_x = min_text_width + text_padding * 2
        gradient_end_x = width - max_text_width - text_padding * 2
        gradient_width = gradient_end_x - gradient_start_x
        
        if gradient_width > 0:
            # Draw gradient in the middle section
            gradient = QLinearGradient(gradient_start_x, 0, gradient_end_x, 0)
            
            if self.color_stops:
                # Multi-stop gradient
                for position, color in self.color_stops:
                    gradient.setColorAt(position, color)
            else:
                # Simple two-color gradient
                gradient.setColorAt(0, self.start_color)
                gradient.setColorAt(1, self.end_color)
            
            painter.fillRect(gradient_start_x, 2, gradient_width, height - 4, gradient)
        
        # Use palette text color (respects light/dark theme)
        painter.setPen(self.palette().color(self.palette().Text))
        
        # Draw min value on left
        painter.drawText(text_padding, height // 2 + 4, min_text)
        
        # Draw max value on right
        painter.drawText(width - max_text_width - text_padding, height // 2 + 4, max_text)
        
        painter.end()


class LayerTreeBuilder:
    """Builds and populates the layer tree widget with groups and layers."""
    
    @staticmethod
    def build_tree_from_node(node, parent_item, tree_widget, dialog=None):
        """
        Recursively build tree from layer tree node.
        
        Args:
            node: QgsLayerTreeNode to process
            parent_item: Parent QTreeWidgetItem (None for root)
            tree_widget: QTreeWidget instance
            dialog: LayersAdvancedDialog instance for logging (optional)
        """
        if dialog:
            dialog.log_debug(f"build_tree_from_node called, node has {len(node.children())} children")
        for child in node.children():
            if dialog:
                dialog.log_debug(f"Processing child: {type(child).__name__}")
            if isinstance(child, QgsLayerTreeGroup):
                # Create group item
                group_item = LayerTreeBuilder.add_group_item(child, parent_item, tree_widget)
                # Recursively add children
                LayerTreeBuilder.build_tree_from_node(child, group_item, tree_widget, dialog)
            elif isinstance(child, QgsLayerTreeLayer):
                # Add layer item
                layer = child.layer()
                if dialog:
                    dialog.log_debug(f"Found layer node, layer={layer.name() if layer else 'None'}, isValid={layer.isValid() if layer else 'N/A'}")
                if layer and layer.isValid():
                    LayerTreeBuilder.add_layer_item(layer, parent_item, tree_widget, child, dialog)
    
    @staticmethod
    def add_group_item(group_node, parent_item, tree_widget):
        """
        Add a group folder to the tree.
        
        Args:
            group_node: QgsLayerTreeGroup node
            parent_item: Parent QTreeWidgetItem (None for root)
            tree_widget: QTreeWidget instance
            
        Returns:
            QTreeWidgetItem: Created group item
        """
        if parent_item:
            item = QTreeWidgetItem(parent_item)
        else:
            item = QTreeWidgetItem(tree_widget)
        
        # Set group name
        group_name = group_node.name()
        item.setText(0, group_name)
        item.setData(0, Qt.UserRole, group_name)  # Store the group name to avoid dangling pointers
        item.setData(0, Qt.UserRole + 1, "group")  # Mark as group
        
        # Set checkbox for visibility
        item.setCheckState(0, Qt.Checked if group_node.isVisible() else Qt.Unchecked)
        
        # Set folder icon
        item.setIcon(0, QIcon(":/images/themes/default/mActionFolder.svg"))
        
        # Make text bold for groups
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        
        # Set other columns to empty
        for col in range(1, 7):
            item.setText(col, "")
        
        return item
    
    @staticmethod
    def add_layer_item(layer, parent_item, tree_widget, layer_node=None, dialog=None):
        """
        Add a layer to the tree widget.
        
        Args:
            layer: QgsMapLayer to add
            parent_item: Parent QTreeWidgetItem (None for root)
            tree_widget: QTreeWidget instance
            layer_node: QgsLayerTreeLayer node (optional)
            dialog: LayersAdvancedDialog instance for logging (optional)
            
        Returns:
            QTreeWidgetItem: Created layer item
        """
        if dialog:
            dialog.log_debug(f"add_layer_item called for '{layer.name()}', type={type(layer).__name__}, isRasterLayer={isinstance(layer, QgsRasterLayer)}")
        
        if parent_item:
            item = QTreeWidgetItem(parent_item)
        else:
            item = QTreeWidgetItem(tree_widget)
        
        # Set layer name
        item.setText(0, layer.name())
        item.setData(0, Qt.UserRole, layer.id())
        item.setData(0, Qt.UserRole + 1, "layer")  # Mark as layer
        
        # Set checkbox for visibility
        if layer_node:
            item.setCheckState(0, Qt.Checked if layer_node.isVisible() else Qt.Unchecked)
        else:
            item.setCheckState(0, Qt.Checked if VisibilityService.is_layer_visible(layer) else Qt.Unchecked)
        
        # Set layer type
        layer_type = LayerService.get_layer_type_string(layer)
        item.setText(1, layer_type)
        
        # Set feature count or size info
        info = LayerService.get_layer_info(layer)
        item.setText(2, info)
        
        # Set CRS
        try:
            crs = layer.crs().authid()
            item.setText(3, crs if crs else "-")
        except Exception:
            item.setText(3, "-")
        
        # Set file type
        try:
            source = layer.source()
            import os
            if os.path.exists(source):
                ext = os.path.splitext(source)[1].upper()
                item.setText(4, ext if ext else "-")
            else:
                # For non-file sources, try to get provider type
                try:
                    provider = layer.providerType()
                    item.setText(4, provider if provider else "-")
                except Exception:
                    item.setText(4, "-")
        except Exception:
            item.setText(4, "-")
        
        # Set file size
        try:
            source = layer.source()
            import os
            if os.path.exists(source):
                size_bytes = os.path.getsize(source)
                # Format size in human-readable format
                if size_bytes < 1024:
                    size_str = f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                elif size_bytes < 1024 * 1024 * 1024:
                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                else:
                    size_str = f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
                item.setText(5, size_str)
            else:
                item.setText(5, "-")
        except Exception:
            item.setText(5, "-")
        
        # Set source path (truncated, full path in tooltip)
        try:
            source = layer.source()
            # Extract filename or last part of path for display
            import os
            if os.path.exists(source):
                display_source = os.path.basename(source)
            else:
                # For non-file sources (e.g., URLs, database connections)
                display_source = source[:30] + "..." if len(source) > 30 else source
            
            item.setText(6, display_source)
            item.setToolTip(6, source)  # Full path on hover
        except Exception:
            item.setText(6, "-")
        
        # Set icon based on layer type
        icon = LayerTreeBuilder.get_layer_icon(layer)
        if icon:
            item.setIcon(0, icon)
        
        # Add symbology children for vector layers
        if isinstance(layer, QgsVectorLayer):
            LayerTreeBuilder.add_symbology_items(layer, item, layer_node)
        
        # Add symbology children for raster layers
        elif isinstance(layer, QgsRasterLayer):
            if dialog:
                dialog.log_debug(f"Calling add_raster_symbology_items for '{layer.name()}'")
            LayerTreeBuilder.add_raster_symbology_items(layer, item, layer_node, dialog)
        
        return item
    
    @staticmethod
    def add_symbology_items(vector_layer, parent_item, layer_node):
        """
        Add symbology items as children of a vector layer.
        
        Args:
            vector_layer: QgsVectorLayer
            parent_item: Parent QTreeWidgetItem
            layer_node: QgsLayerTreeLayer node (for checking visibility)
        """
        try:
            renderer = vector_layer.renderer()
            
            if isinstance(renderer, QgsCategorizedSymbolRenderer):
                # Categorized renderer - add each category as a child
                for i, category in enumerate(renderer.categories()):
                    LayerTreeBuilder.add_category_item(category, i, parent_item, vector_layer, layer_node)
            
            elif isinstance(renderer, QgsGraduatedSymbolRenderer):
                # Graduated renderer - add each range as a child
                for i, range_item in enumerate(renderer.ranges()):
                    LayerTreeBuilder.add_range_item(range_item, i, parent_item, vector_layer, layer_node)
            
            elif isinstance(renderer, QgsSingleSymbolRenderer):
                # Single symbol - show the symbol icon next to layer name (not as child)
                symbol = renderer.symbol()
                if symbol:
                    icon = LayerTreeBuilder.create_symbol_icon(symbol, vector_layer)
                    if icon:
                        parent_item.setIcon(0, icon)
            
            elif isinstance(renderer, QgsRuleBasedRenderer):
                # Rule-based renderer - add each rule as a child
                root_rule = renderer.rootRule()
                if root_rule:
                    for rule in root_rule.children():
                        LayerTreeBuilder.add_rule_item(rule, parent_item, vector_layer, layer_node)
        
        except Exception as e:
            # Silently fail if symbology can't be loaded
            pass
    
    @staticmethod
    def add_category_item(category, index, parent_item, vector_layer, layer_node):
        """Add a categorized symbol item as a child."""
        try:
            item = QTreeWidgetItem(parent_item)
            
            # Set category label
            label = category.label() if category.label() else str(category.value())
            item.setText(0, label)
            
            # Set symbol icon
            symbol = category.symbol()
            if symbol:
                icon = LayerTreeBuilder.create_symbol_icon(symbol, vector_layer)
                if icon:
                    item.setIcon(0, icon)
            
            # Make checkbox for category visibility
            item.setCheckState(0, Qt.Checked if category.renderState() else Qt.Unchecked)
            
            # Store category info
            item.setData(0, Qt.UserRole, vector_layer.id())
            item.setData(0, Qt.UserRole + 1, "category")
            item.setData(0, Qt.UserRole + 2, index)  # Store category index
            
            # Make text slightly smaller/lighter for categories
            font = item.font(0)
            font.setPointSize(font.pointSize() - 1)
            item.setFont(0, font)
            
        except Exception:
            pass
    
    @staticmethod
    def add_range_item(range_item, index, parent_item, vector_layer, layer_node):
        """Add a graduated symbol range item as a child."""
        try:
            item = QTreeWidgetItem(parent_item)
            
            # Set range label
            label = range_item.label() if range_item.label() else f"{range_item.lowerValue()} - {range_item.upperValue()}"
            item.setText(0, label)
            
            # Set symbol icon
            symbol = range_item.symbol()
            if symbol:
                icon = LayerTreeBuilder.create_symbol_icon(symbol, vector_layer)
                if icon:
                    item.setIcon(0, icon)
            
            # Make checkbox for range visibility
            item.setCheckState(0, Qt.Checked if range_item.renderState() else Qt.Unchecked)
            
            # Store range info
            item.setData(0, Qt.UserRole, vector_layer.id())
            item.setData(0, Qt.UserRole + 1, "range")
            item.setData(0, Qt.UserRole + 2, index)  # Store range index
            
            # Make text slightly smaller/lighter
            font = item.font(0)
            font.setPointSize(font.pointSize() - 1)
            item.setFont(0, font)
            
        except Exception:
            pass
    
    @staticmethod
    def add_rule_item(rule, parent_item, vector_layer, layer_node):
        """Add a rule-based renderer rule item as a child."""
        try:
            item = QTreeWidgetItem(parent_item)
            
            # Set rule label
            label = rule.label() if rule.label() else rule.filterExpression()
            item.setText(0, label if label else "Rule")
            
            # Set symbol icon
            symbol = rule.symbol()
            if symbol:
                icon = LayerTreeBuilder.create_symbol_icon(symbol, vector_layer)
                if icon:
                    item.setIcon(0, icon)
            
            # Make checkbox for rule visibility
            item.setCheckState(0, Qt.Checked if rule.active() else Qt.Unchecked)
            
            # Store rule info
            item.setData(0, Qt.UserRole, vector_layer.id())
            item.setData(0, Qt.UserRole + 1, "rule")
            item.setData(0, Qt.UserRole + 2, rule.ruleKey())
            
            # Make text slightly smaller/lighter
            font = item.font(0)
            font.setPointSize(font.pointSize() - 1)
            item.setFont(0, font)
            
            # Recursively add child rules
            if rule.children():
                for child_rule in rule.children():
                    LayerTreeBuilder.add_rule_item(child_rule, item, vector_layer, layer_node)
            
        except Exception:
            pass
    
    @staticmethod
    def create_symbol_icon(symbol, layer):
        """
        Create an icon from a QgsSymbol.
        
        Args:
            symbol: QgsSymbol
            layer: The vector layer (for context)
            
        Returns:
            QIcon or None
        """
        try:
            # Create a small pixmap for the symbol
            size = QSize(16, 16)
            pixmap = QPixmap(size)
            pixmap.fill(Qt.transparent)
            
            painter = QPainter(pixmap)
            symbol.drawPreviewIcon(painter, size)
            painter.end()
            
            return QIcon(pixmap)
        except Exception:
            return None
    
    @staticmethod
    def add_raster_symbology_items(raster_layer, parent_item, layer_node, dialog=None):
        """
        Add symbology items as children of a raster layer.
        
        Args:
            raster_layer: QgsRasterLayer
            parent_item: Parent QTreeWidgetItem
            layer_node: QgsLayerTreeLayer node
            dialog: LayersAdvancedDialog instance for logging (optional)
        """
        try:
            if dialog:
                dialog.log_debug(f"add_raster_symbology_items called for layer: {raster_layer.name()}")
            renderer = raster_layer.renderer()
            if dialog:
                dialog.log_debug(f"Renderer type: {type(renderer).__name__}")
            
            if isinstance(renderer, QgsPalettedRasterRenderer):
                if dialog:
                    dialog.log_debug("Detected QgsPalettedRasterRenderer")
                # Paletted/categorized raster - show each class
                classes = renderer.classes()
                for i, raster_class in enumerate(classes):
                    LayerTreeBuilder.add_raster_palette_item(raster_class, i, parent_item, raster_layer)
            
            elif isinstance(renderer, QgsSingleBandPseudoColorRenderer):
                if dialog:
                    dialog.log_debug("Detected QgsSingleBandPseudoColorRenderer")
                # Pseudocolor (gradient) - show color ramp bar
                LayerTreeBuilder.add_raster_gradient_item(renderer, parent_item, raster_layer, dialog)
            
            elif isinstance(renderer, QgsSingleBandGrayRenderer):
                if dialog:
                    dialog.log_debug("Detected QgsSingleBandGrayRenderer")
                # Grayscale - show gradient bar
                LayerTreeBuilder.add_raster_gray_gradient_item(renderer, parent_item, raster_layer, dialog)
            
            elif isinstance(renderer, QgsMultiBandColorRenderer):
                if dialog:
                    dialog.log_debug("Detected QgsMultiBandColorRenderer")
                # Multiband color (RGB) - show a simple indicator
                LayerTreeBuilder.add_raster_rgb_item(renderer, parent_item, raster_layer)
            
            elif isinstance(renderer, QgsRasterContourRenderer):
                if dialog:
                    dialog.log_debug("Detected QgsRasterContourRenderer")
                # Contour renderer - show contour levels
                LayerTreeBuilder.add_raster_contour_items(renderer, parent_item, raster_layer, dialog)
            
            else:
                if dialog:
                    dialog.log_debug(f"Unknown renderer type: {type(renderer).__name__}")
        
        except Exception as e:
            print(f"DEBUG ERROR in add_raster_symbology_items: {e}")
            import traceback
            traceback.print_exc()
    
    @staticmethod
    def add_raster_palette_item(raster_class, index, parent_item, raster_layer):
        """Add a paletted raster class item as a child."""
        try:
            item = QTreeWidgetItem(parent_item)
            
            # Set class label
            label = raster_class.label if raster_class.label else str(raster_class.value)
            item.setText(0, label)
            
            # Create color icon
            pixmap = QPixmap(16, 16)
            pixmap.fill(raster_class.color)
            item.setIcon(0, QIcon(pixmap))
            
            # Store class info
            item.setData(0, Qt.UserRole, raster_layer.id())
            item.setData(0, Qt.UserRole + 1, "raster_palette")
            item.setData(0, Qt.UserRole + 2, index)
            
            # Make text slightly smaller
            font = item.font(0)
            font.setPointSize(font.pointSize() - 1)
            item.setFont(0, font)
            
        except Exception:
            pass
    
    @staticmethod
    def add_raster_contour_items(renderer, parent_item, raster_layer, dialog=None):
        """Add contour levels as list items."""
        try:
            if dialog:
                dialog.log_debug(f"add_raster_contour_items called for {raster_layer.name()}")
            
            # Get contour interval and index interval
            contour_interval = renderer.contourInterval()
            index_interval = renderer.contourIndexInterval()
            
            if dialog:
                dialog.log_debug(f"  contour_interval = {contour_interval}")
                dialog.log_debug(f"  index_interval = {index_interval}")
            
            # Get contour symbol (line style)
            contour_symbol = renderer.contourSymbol()
            index_symbol = renderer.contourIndexSymbol()
            
            # Add contour interval item
            if contour_interval > 0:
                item = QTreeWidgetItem(parent_item)
                item.setText(0, f"Interval: {contour_interval}")
                
                # Get line color from symbol if available
                if contour_symbol:
                    color = contour_symbol.color()
                    pixmap = QPixmap(16, 16)
                    pixmap.fill(Qt.transparent)
                    painter = QPainter(pixmap)
                    painter.setPen(color)
                    painter.drawLine(0, 8, 16, 8)
                    painter.end()
                    item.setIcon(0, QIcon(pixmap))
                
                # Make text slightly smaller
                font = item.font(0)
                font.setPointSize(font.pointSize() - 1)
                item.setFont(0, font)
                
                item.setData(0, Qt.UserRole, raster_layer.id())
                item.setData(0, Qt.UserRole + 1, "raster_contour")
            
            # Add index contour item if different
            if index_interval > 0 and index_interval != contour_interval:
                item = QTreeWidgetItem(parent_item)
                item.setText(0, f"Index Interval: {index_interval}")
                
                # Get line color from index symbol if available
                if index_symbol:
                    color = index_symbol.color()
                    pixmap = QPixmap(16, 16)
                    pixmap.fill(Qt.transparent)
                    painter = QPainter(pixmap)
                    pen = painter.pen()
                    pen.setColor(color)
                    pen.setWidth(2)  # Thicker line for index contours
                    painter.setPen(pen)
                    painter.drawLine(0, 8, 16, 8)
                    painter.end()
                    item.setIcon(0, QIcon(pixmap))
                
                # Make text slightly smaller
                font = item.font(0)
                font.setPointSize(font.pointSize() - 1)
                item.setFont(0, font)
                
                item.setData(0, Qt.UserRole, raster_layer.id())
                item.setData(0, Qt.UserRole + 1, "raster_contour_index")
            
            if dialog:
                dialog.log_debug(f"  Added contour items")
        
        except Exception as e:
            if dialog:
                dialog.log_debug(f"Error in add_raster_contour_items: {e}")
            import traceback
            traceback.print_exc()
    
    @staticmethod
    def add_raster_discrete_items(raster_shader, parent_item, raster_layer, dialog=None):
        """Add discrete color ramp items as a list (similar to vector categories)."""
        try:
            if dialog:
                dialog.log_debug(f"add_raster_discrete_items called for {raster_layer.name()}")
            
            # Get the color ramp items
            if not hasattr(raster_shader, 'colorRampItemList'):
                if dialog:
                    dialog.log_debug("No colorRampItemList method available")
                return
            
            ramp_items = raster_shader.colorRampItemList()
            if dialog:
                dialog.log_debug(f"Found {len(ramp_items)} discrete color ramp items")
            
            # Add each item as a separate row
            for index, ramp_item in enumerate(ramp_items):
                item = QTreeWidgetItem(parent_item)
                
                # Format label based on whether it has a label or just value
                if ramp_item.label:
                    label = ramp_item.label
                else:
                    label = str(ramp_item.value)
                
                item.setText(0, label)
                
                # Create color icon (square swatch like vector categories)
                pixmap = QPixmap(16, 16)
                pixmap.fill(ramp_item.color)
                item.setIcon(0, QIcon(pixmap))
                
                # Store item info
                item.setData(0, Qt.UserRole, raster_layer.id())
                item.setData(0, Qt.UserRole + 1, "raster_discrete")
                item.setData(0, Qt.UserRole + 2, index)
                
                # Make text slightly smaller to match other symbology items
                font = item.font(0)
                font.setPointSize(font.pointSize() - 1)
                item.setFont(0, font)
                
                if dialog:
                    dialog.log_debug(f"  Added discrete item: {label} = {ramp_item.color.name()}")
        
        except Exception as e:
            if dialog:
                dialog.log_debug(f"Error in add_raster_discrete_items: {e}")
            import traceback
            traceback.print_exc()
    
    @staticmethod
    def add_raster_gradient_item(renderer, parent_item, raster_layer, dialog=None):
        """Add a gradient bar for pseudocolor raster (or discrete list for Discrete/Exact modes)."""
        try:
            if dialog:
                dialog.log_debug(f"add_raster_gradient_item called for {raster_layer.name()}")
            
            # Get shader and color ramp
            shader = renderer.shader()
            if dialog:
                dialog.log_debug(f"shader = {shader}")
            if not shader:
                if dialog:
                    dialog.log_debug("No shader found!")
                return
            
            raster_shader = shader.rasterShaderFunction()
            if dialog:
                dialog.log_debug(f"raster_shader = {raster_shader}")
            if not raster_shader:
                if dialog:
                    dialog.log_debug("No raster shader function!")
                return
            
            # Check interpolation type
            from qgis.core import QgsColorRampShader
            color_ramp_type = raster_shader.colorRampType()
            if dialog:
                dialog.log_debug(f"color_ramp_type = {color_ramp_type}")
            
            # If Discrete or Exact, show as list items instead of gradient
            if color_ramp_type in (QgsColorRampShader.Discrete, QgsColorRampShader.Exact):
                LayerTreeBuilder.add_raster_discrete_items(raster_shader, parent_item, raster_layer, dialog)
                return
            
            # Otherwise, show as gradient (Interpolated mode)
            item = QTreeWidgetItem(parent_item)
            
            # Get min/max values
            min_val = raster_shader.minimumValue()
            max_val = raster_shader.maximumValue()
            if dialog:
                dialog.log_debug(f"min_val = {min_val}, max_val = {max_val}")
            
            # Get color ramp items (the color stops)
            color_stops = []
            try:
                # Try to get the color ramp items which define the stops
                if hasattr(raster_shader, 'colorRampItemList'):
                    ramp_items = raster_shader.colorRampItemList()
                    if dialog:
                        dialog.log_debug(f"Found {len(ramp_items)} color ramp items")
                    
                    # Convert ramp items to normalized positions (0.0-1.0)
                    value_range = max_val - min_val
                    if value_range > 0:
                        for ramp_item in ramp_items:
                            value = ramp_item.value
                            color = ramp_item.color
                            position = (value - min_val) / value_range
                            # Clamp position to 0.0-1.0 range
                            position = max(0.0, min(1.0, position))
                            color_stops.append((position, color))
                            if dialog:
                                dialog.log_debug(f"  Stop at {position:.3f} ({value:.2f}): {color.name()}")
            except Exception as e:
                if dialog:
                    dialog.log_debug(f"Error getting color ramp items: {e}")
            
            # Fallback: get the source color ramp and sample it
            if not color_stops:
                color_ramp = raster_shader.sourceColorRamp()
                if dialog:
                    dialog.log_debug(f"color_ramp = {color_ramp}")
                
                if color_ramp:
                    # Sample the color ramp at regular intervals
                    start_color = color_ramp.color(0.0)
                    end_color = color_ramp.color(1.0)
                    
                    if dialog:
                        dialog.log_debug(f"Fallback: sampling ramp - start: {start_color.name()}, end: {end_color.name()}")
                else:
                    # No color information available
                    if dialog:
                        dialog.log_debug("No color ramp available")
                    item.setText(0, f"{min_val:.2f} - {max_val:.2f}")
                    return
            
            # Create gradient widget with color stops
            if color_stops:
                # Use the first and last colors for the simple gradient parameters
                start_color = color_stops[0][1]
                end_color = color_stops[-1][1]
                gradient_widget = GradientWidget(start_color, end_color, min_val, max_val, color_stops=color_stops)
                if dialog:
                    dialog.log_debug(f"Created GradientWidget with {len(color_stops)} color stops")
            else:
                # Fallback to simple two-color gradient
                gradient_widget = GradientWidget(start_color, end_color, min_val, max_val)
                if dialog:
                    dialog.log_debug("Created simple GradientWidget")
            
            # Set empty text for the item (widget will display everything)
            item.setText(0, "")
            
            # Get the tree widget from parent_item
            tree_widget = parent_item.treeWidget() if parent_item else None
            if tree_widget:
                tree_widget.setItemWidget(item, 0, gradient_widget)
                if dialog:
                    dialog.log_debug("Set item widget")
            
            # Store info
            item.setData(0, Qt.UserRole, raster_layer.id())
            item.setData(0, Qt.UserRole + 1, "raster_pseudocolor")
            
        except Exception as e:
            if dialog:
                dialog.log_debug(f"ERROR in add_raster_gradient_item: {e}")
            import traceback
            traceback.print_exc()
    
    @staticmethod
    def add_raster_gray_gradient_item(renderer, parent_item, raster_layer, dialog=None):
        """Add a grayscale gradient bar."""
        from qgis.core import QgsRasterShader, QgsColorRampShader
        
        try:
            if dialog:
                dialog.log_debug(f"add_raster_gray_gradient_item called for {raster_layer.name()}")
            item = QTreeWidgetItem(parent_item)
            
            # Get min/max values from the raster
            # Use inputBand() instead of deprecated grayBand()
            try:
                band = renderer.inputBand()
                if dialog:
                    dialog.log_debug(f"band = {band} (from inputBand)")
            except AttributeError:
                # Fallback for older QGIS versions
                band = renderer.grayBand()
                if dialog:
                    dialog.log_debug(f"band = {band} (from grayBand)")
            
            provider = raster_layer.dataProvider()
            
            # Try to get min/max from renderer's contrast enhancement
            min_val = None
            max_val = None
            
            try:
                contrast_enhancement = renderer.contrastEnhancement()
                if dialog:
                    dialog.log_debug(f"contrast_enhancement = {contrast_enhancement}")
                if contrast_enhancement:
                    min_val = contrast_enhancement.minimumValue()
                    max_val = contrast_enhancement.maximumValue()
                    if dialog:
                        dialog.log_debug(f"From contrast enhancement - min: {min_val}, max: {max_val}")
            except Exception as ce_ex:
                if dialog:
                    dialog.log_debug(f"Error getting contrast enhancement: {ce_ex}")
            
            # Fallback to band statistics if contrast enhancement doesn't have values
            if min_val is None or max_val is None:
                try:
                    stats = provider.bandStatistics(band)
                    min_val = stats.minimumValue
                    max_val = stats.maximumValue
                    if dialog:
                        dialog.log_debug(f"From band stats - min: {min_val}, max: {max_val}")
                except Exception as stats_ex:
                    if dialog:
                        dialog.log_debug(f"Error getting band stats: {stats_ex}")
                    # Last resort defaults
                    min_val = 0
                    max_val = 255
                    if dialog:
                        dialog.log_debug(f"Using defaults - min: {min_val}, max: {max_val}")
            
            # Determine gradient colors based on renderer settings
            start_color = QColor(0, 0, 0)  # Default black
            end_color = QColor(255, 255, 255)  # Default white
            
            # Try to get the actual gradient mode
            try:
                # Access the gradient property (BlackToWhite=0, WhiteToBlack=1)
                gradient_mode = renderer.gradient()
                if dialog:
                    dialog.log_debug(f"gradient_mode = {gradient_mode}")
                if gradient_mode == 1:  # WhiteToBlack
                    start_color = QColor(255, 255, 255)
                    end_color = QColor(0, 0, 0)
                    if dialog:
                        dialog.log_debug("Using WhiteToBlack gradient")
                else:
                    if dialog:
                        dialog.log_debug("Using BlackToWhite gradient")
            except Exception as grad_ex:
                if dialog:
                    dialog.log_debug(f"Error getting gradient mode: {grad_ex}")
            
            if dialog:
                dialog.log_debug(f"Final colors - start: {start_color.name()}, end: {end_color.name()}")
            
            # Create custom gradient widget
            gradient_widget = GradientWidget(start_color, end_color, min_val, max_val)
            if dialog:
                dialog.log_debug("Created GradientWidget")
            
            # Set empty text for the item (widget will display everything)
            item.setText(0, "")
            
            # Get the tree widget from parent_item
            tree_widget = parent_item.treeWidget() if parent_item else None
            if tree_widget:
                tree_widget.setItemWidget(item, 0, gradient_widget)
                if dialog:
                    dialog.log_debug("Set item widget")
            
            # Store info
            item.setData(0, Qt.UserRole, raster_layer.id())
            item.setData(0, Qt.UserRole + 1, "raster_gray")
            
        except Exception as e:
            print(f"DEBUG ERROR in add_raster_gray_gradient_item: {e}")
            import traceback
            traceback.print_exc()
            pass
    
    @staticmethod
    def add_raster_rgb_item(renderer, parent_item, raster_layer):
        """Add an RGB indicator for multiband color raster."""
        try:
            item = QTreeWidgetItem(parent_item)
            
            # Get band assignments
            red_band = renderer.redBand()
            green_band = renderer.greenBand()
            blue_band = renderer.blueBand()
            
            item.setText(0, f"RGB: {red_band}, {green_band}, {blue_band}")
            
            # Create simple RGB icon
            pixmap = QPixmap(48, 16)
            painter = QPainter(pixmap)
            painter.fillRect(0, 0, 16, 16, QColor(255, 0, 0))
            painter.fillRect(16, 0, 16, 16, QColor(0, 255, 0))
            painter.fillRect(32, 0, 16, 16, QColor(0, 0, 255))
            painter.end()
            
            item.setIcon(0, QIcon(pixmap))
            
            # Store info
            item.setData(0, Qt.UserRole, raster_layer.id())
            item.setData(0, Qt.UserRole + 1, "raster_rgb")
            
            # Make text slightly smaller
            font = item.font(0)
            font.setPointSize(font.pointSize() - 1)
            item.setFont(0, font)
            
        except Exception:
            pass
    
    @staticmethod
    def get_layer_icon(layer):
        """
        Get the appropriate icon for a layer type.
        
        Args:
            layer: QgsMapLayer
            
        Returns:
            QIcon or None
        """
        try:
            if layer.type() == QgsMapLayer.VectorLayer:
                return QIcon(":/images/themes/default/mIconVector.svg")
            elif layer.type() == QgsMapLayer.RasterLayer:
                return QIcon(":/images/themes/default/mIconRaster.svg")
        except Exception:
            pass
        return None

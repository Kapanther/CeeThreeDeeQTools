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

from qgis.PyQt.QtWidgets import QTreeWidgetItem
from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QIcon, QPixmap, QPainter
from qgis.core import (
    QgsMapLayer,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsVectorLayer,
    QgsSymbol,
    QgsRendererCategory,
    QgsCategorizedSymbolRenderer,
    QgsSingleSymbolRenderer,
    QgsGraduatedSymbolRenderer,
    QgsRuleBasedRenderer
)
from ..services.layer_service import LayerService
from ..services.visibility_service import VisibilityService


class LayerTreeBuilder:
    """Builds and populates the layer tree widget with groups and layers."""
    
    @staticmethod
    def build_tree_from_node(node, parent_item, tree_widget):
        """
        Recursively build tree from layer tree node.
        
        Args:
            node: QgsLayerTreeNode to process
            parent_item: Parent QTreeWidgetItem (None for root)
            tree_widget: QTreeWidget instance
        """
        for child in node.children():
            if isinstance(child, QgsLayerTreeGroup):
                # Create group item
                group_item = LayerTreeBuilder.add_group_item(child, parent_item, tree_widget)
                # Recursively add children
                LayerTreeBuilder.build_tree_from_node(child, group_item, tree_widget)
            elif isinstance(child, QgsLayerTreeLayer):
                # Add layer item
                layer = child.layer()
                if layer and layer.isValid():
                    LayerTreeBuilder.add_layer_item(layer, parent_item, tree_widget, child)
    
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
    def add_layer_item(layer, parent_item, tree_widget, layer_node=None):
        """
        Add a layer to the tree widget.
        
        Args:
            layer: QgsMapLayer to add
            parent_item: Parent QTreeWidgetItem (None for root)
            tree_widget: QTreeWidget instance
            layer_node: QgsLayerTreeLayer node (optional)
            
        Returns:
            QTreeWidgetItem: Created layer item
        """
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

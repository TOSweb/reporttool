from django import template
from decimal import Decimal
from django.utils.safestring import mark_safe
from datetime import datetime
from dateutil.parser import parse

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Template filter to get a value from a dictionary by key"""
    if dictionary is None:
        return None
    return dictionary.get(key)

@register.filter
def map_field_paths(columns):
    """Template filter to get a list of field paths from columns"""
    return [col.field_path for col in columns]

@register.filter
def split(value, delimiter=','):
    """Template filter to split a string by delimiter"""
    if value:
        return value.split(delimiter)
    return []

@register.filter
def format_number(value, aggregation_type=None):
    """Template filter to format numbers based on aggregation type"""
    if value is None:
        return ''
    
    try:
        if aggregation_type == 'COUNT':
            return str(int(value))
        elif isinstance(value, (int, float)):
            return '{:.2f}'.format(float(value))
        return value
    except (ValueError, TypeError):
        return value

@register.filter
def get_dict_value(dictionary, key):
    """
    Template filter to get a value from a dictionary using a key.
    Handles nested keys using dot notation.
    """
    if not dictionary or not key:
        return ''
    
    try:
        # Handle nested keys
        if '.' in key:
            parts = key.split('.')
            value = dictionary
            for part in parts:
                value = value.get(part, '')
            return value
        return dictionary.get(key, '')
    except (AttributeError, TypeError, KeyError):
        return ''

@register.filter
def add(value, arg):
    """
    Template filter to add numbers
    """
    try:
        return float(value) + float(arg)
    except (ValueError, TypeError):
        return value

@register.filter
def get_field(obj, field_path):
    """
    Get a field value from an object using dot notation.
    Handles both dictionary and object access.
    """
    if obj is None:
        return ''
        
    if isinstance(obj, dict):
        return obj.get(field_path, '')
        
    try:
        # Split the field path for nested access
        parts = field_path.split('__')
        value = obj
        
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part, '')
            else:
                value = getattr(value, part, '')
                
            if callable(value):
                value = value()
                
        # Format numeric values
        if isinstance(value, float):
            return '{:.2f}'.format(value)
        return value if value is not None else ''
    except (AttributeError, KeyError, ValueError, TypeError):
        return ''

@register.filter
def map_field_paths(queryset):
    """Convert a queryset of objects with field_path attribute to a list of field paths"""
    return [obj.field_path for obj in queryset]

@register.filter
def format_value(value, column):
    """Format a value based on column settings."""
    if value is None:
        return ''
        
    try:
        if column.formatting_type == 'number':
            if isinstance(value, (int, float)):
                return f"{float(value):,.{column.decimal_places}f}"
            return value
            
        elif column.formatting_type == 'currency':
            if isinstance(value, (int, float)):
                return f"{column.currency_symbol}{float(value):,.{column.decimal_places}f}"
            return value
            
        elif column.formatting_type == 'percentage':
            if isinstance(value, (int, float)):
                return f"{float(value) * 100:.{column.decimal_places}f}%"
            return value
            
        elif column.formatting_type == 'date':
            if isinstance(value, str):
                try:
                    value = parse(value)
                except:
                    return value
            if isinstance(value, datetime):
                return value.strftime(column.date_format)
            return value
            
        elif column.formatting_type == 'boolean':
            if isinstance(value, bool):
                return 'Yes' if value else 'No'
            return value
            
        # Apply conditional formatting if any
        if column.conditional_formatting:
            try:
                rules = column.conditional_formatting.get('rules', [])
                for rule in rules:
                    condition = rule['condition']
                    if column._evaluate_condition(condition, value, {}):
                        style = rule.get('style', {})
                        style_str = '; '.join([f"{k}: {v}" for k, v in style.items()])
                        return mark_safe(f'<span style="{style_str}">{value}</span>')
            except:
                pass
                
        return str(value)
        
    except Exception as e:
        print(f"Error formatting value: {str(e)}")
        return str(value)

@register.filter
def get_group_indicator(level):
    """Return the appropriate group level indicator."""
    indicators = ['└', '├', '─', '│']
    if level < len(indicators):
        return indicators[level]
    return indicators[-1]

@register.filter
def format_aggregation(aggregation):
    """Format aggregation name for display."""
    return aggregation.replace('_', ' ').title()

@register.simple_tag
def get_column_style(column, value, row_data=None):
    """Get the style for a column value based on conditional formatting."""
    if not column.conditional_formatting:
        return ''
        
    try:
        rules = column.conditional_formatting.get('rules', [])
        for rule in rules:
            if column._evaluate_condition(rule['condition'], value, row_data or {}):
                style = rule.get('style', {})
                return '; '.join([f"{k}: {v}" for k, v in style.items()])
    except Exception as e:
        print(f"Error applying conditional formatting: {str(e)}")
        
    return '' 
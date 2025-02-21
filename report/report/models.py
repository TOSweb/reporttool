from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
import json

class Report(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    root_model = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.name
        
    def get_optimized_queryset(self):
        """Get an optimized queryset with all necessary related fields."""
        print(f"DEBUG: Getting optimized queryset for report {self.id}")
        model_class = self.root_model.model_class()
        print(f"DEBUG: Root model is {model_class.__name__}")
        queryset = model_class.objects.all()
        
        # Collect all field paths
        field_paths = set()
        for column in self.columns.all():
            if '__' in column.field_path:
                field_paths.add(column.field_path.split('__')[0])
                print(f"DEBUG: Added field path from column: {column.field_path}")
        
        for filter_obj in self.filters.all():
            if '__' in filter_obj.field_path:
                field_paths.add(filter_obj.field_path.split('__')[0])
                print(f"DEBUG: Added field path from filter: {filter_obj.field_path}")
                
        for grouping in self.groupings.all():
            if '__' in grouping.field_path:
                field_paths.add(grouping.field_path.split('__')[0])
                print(f"DEBUG: Added field path from grouping: {grouping.field_path}")
        
        print(f"DEBUG: Collected field paths: {field_paths}")
        
        # Add select_related for ForeignKey fields
        select_related = []
        prefetch_related = []
        
        for path in field_paths:
            field = model_class._meta.get_field(path)
            if field.many_to_one or field.one_to_one:
                select_related.append(path)
                print(f"DEBUG: Added {path} to select_related")
            elif field.many_to_many or field.one_to_many:
                prefetch_related.append(path)
                print(f"DEBUG: Added {path} to prefetch_related")
        
        if select_related:
            print(f"DEBUG: Applying select_related: {select_related}")
            queryset = queryset.select_related(*select_related)
        if prefetch_related:
            print(f"DEBUG: Applying prefetch_related: {prefetch_related}")
            queryset = queryset.prefetch_related(*prefetch_related)
        
        print(f"DEBUG: Final queryset SQL: {queryset.query}")
        return queryset
        
    def needs_pandas_processing(self):
        """Check if the report needs Pandas processing."""
        return (
            self.calculated_fields.exists() or
            self.groupings.exists() or
            any(col.aggregation for col in self.columns.all()) or
            any(col.is_formula for col in self.columns.all())
        )
        
    def get_aggregation_dict(self):
        """Get a dictionary of aggregation functions for Pandas."""
        agg_dict = {}
        for column in self.columns.all():
            if column.aggregation:
                agg_dict[column.field_path] = column.get_pandas_aggregation()
        return agg_dict

class ReportColumn(models.Model):
    AGGREGATION_CHOICES = [
        ('', 'No Aggregation'),
        # Basic Aggregations
        ('COUNT', 'Count'),
        ('SUM', 'Sum'),
        ('AVG', 'Average'),
        ('MIN', 'Minimum'),
        ('MAX', 'Maximum'),
        # Conditional Aggregations
        ('COUNT_DISTINCT', 'Count Distinct'),
        ('COUNT_IF', 'Count If'),
        ('SUM_IF', 'Sum If'),
        # Statistical Aggregations
        ('STDDEV', 'Standard Deviation'),
        ('VARIANCE', 'Variance'),
        ('MEDIAN', 'Median'),
        # Time-Based Aggregations
        ('MONTH_SUM', 'Monthly Sum'),
        ('YEAR_SUM', 'Yearly Sum'),
        ('YOY_GROWTH', 'Year over Year Growth'),
        # Window Functions
        ('RUNNING_TOTAL', 'Running Total'),
        ('RANK', 'Rank'),
        ('MOVING_AVG', 'Moving Average'),
        # Percentile Functions
        ('PERCENTILE_25', '25th Percentile'),
        ('PERCENTILE_50', 'Median (50th Percentile)'),
        ('PERCENTILE_75', '75th Percentile'),
        ('PERCENTILE_90', '90th Percentile'),
    ]

    FORMATTING_TYPES = [
        ('number', 'Number'),
        ('currency', 'Currency'),
        ('percentage', 'Percentage'),
        ('date', 'Date'),
        ('datetime', 'DateTime'),
        ('boolean', 'Boolean'),
        ('text', 'Text')
    ]
    
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='columns')
    name = models.CharField(max_length=255)
    field_path = models.CharField(max_length=255, help_text="Dot notation path to the field")
    display_name = models.CharField(max_length=255)
    order = models.IntegerField(default=0)
    is_visible = models.BooleanField(default=True)
    aggregation = models.CharField(max_length=20, choices=AGGREGATION_CHOICES, blank=True)
    formula = models.TextField(null=True, blank=True, help_text="Python expression for field concatenation. Use field names in curly braces, e.g. {first_name} + ' ' + {last_name}")
    is_formula = models.BooleanField(default=False, help_text="Whether this column is a formula-based field")
    
    # New fields for formatting and display
    formatting_type = models.CharField(max_length=20, choices=FORMATTING_TYPES, default='text')
    decimal_places = models.IntegerField(default=2, help_text="Number of decimal places for numeric fields")
    currency_symbol = models.CharField(max_length=5, default='$', help_text="Currency symbol for currency fields")
    date_format = models.CharField(max_length=50, default='YYYY-MM-DD', help_text="Date format string")
    is_sortable = models.BooleanField(default=True, help_text="Whether this column can be sorted")
    
    # Conditional formatting
    conditional_formatting = models.JSONField(null=True, blank=True, help_text="""
    JSON configuration for conditional formatting, e.g.:
    {
        "rules": [
            {
                "condition": "value > 1000",
                "style": {"color": "red", "font-weight": "bold"}
            }
        ]
    }
    """)
    
    # New fields for advanced aggregations
    condition = models.TextField(null=True, blank=True, help_text="Condition for conditional aggregations (e.g., 'value > 100')")
    window_size = models.IntegerField(null=True, blank=True, help_text="Size of window for moving averages")
    time_unit = models.CharField(max_length=10, choices=[
        ('DAY', 'Daily'),
        ('WEEK', 'Weekly'),
        ('MONTH', 'Monthly'),
        ('QUARTER', 'Quarterly'),
        ('YEAR', 'Yearly')
    ], null=True, blank=True)
    weight_field = models.CharField(max_length=255, null=True, blank=True, help_text="Field to use for weighted calculations")
    
    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.report.name} - {self.display_name}"

    def apply_formula(self, row_data):
        """
        Applies the formula to a row of data.
        Formula should use field names in curly braces, e.g. {first_name} + ' ' + {last_name}
        """
        if not self.is_formula or not self.formula:
            return None
            
        try:
            # Replace field placeholders with actual values
            formula = self.formula
            for field_name in row_data.keys():
                placeholder = '{' + field_name + '}'
                if placeholder in formula:
                    value = row_data[field_name]
                    # Handle different data types
                    if isinstance(value, (int, float)):
                        formula = formula.replace(placeholder, str(value))
                    elif isinstance(value, bool):
                        formula = formula.replace(placeholder, str(value))
                    elif value is None:
                        formula = formula.replace(placeholder, 'None')
                    else:
                        # Escape string values
                        formula = formula.replace(placeholder, f"'{str(value)}'")
            
            # Evaluate the formula
            result = eval(formula, {"__builtins__": {}}, {})  # Restrict built-ins for security
            return result
        except Exception as e:
            print(f"Error applying formula {self.formula}: {str(e)}")
            return None

    def apply_aggregation(self, df, group_by=None):
        """
        Applies the selected aggregation to the data.
        Supports advanced aggregation types including conditional, statistical, and time-based.
        """
        if not self.aggregation:
            return df

        field = self.field_path
        
        try:
            if group_by:
                grouped = df.groupby(group_by)
            else:
                grouped = df

            # Basic Aggregations
            if self.aggregation == 'COUNT':
                return grouped[field].count()
            elif self.aggregation == 'SUM':
                return grouped[field].sum()
            elif self.aggregation == 'AVG':
                return grouped[field].mean()
            elif self.aggregation == 'MIN':
                return grouped[field].min()
            elif self.aggregation == 'MAX':
                return grouped[field].max()
            
            # Conditional Aggregations
            elif self.aggregation == 'COUNT_DISTINCT':
                return grouped[field].nunique()
            elif self.aggregation in ['COUNT_IF', 'SUM_IF'] and self.condition:
                mask = df.eval(self.condition)
                if self.aggregation == 'COUNT_IF':
                    return grouped[mask][field].count()
                else:
                    return grouped[mask][field].sum()
            
            # Statistical Aggregations
            elif self.aggregation == 'STDDEV':
                return grouped[field].std()
            elif self.aggregation == 'VARIANCE':
                return grouped[field].var()
            elif self.aggregation == 'MEDIAN':
                return grouped[field].median()
            
            # Time-Based Aggregations
            elif self.aggregation in ['MONTH_SUM', 'YEAR_SUM']:
                time_field = self.time_unit.lower() if self.time_unit else 'month'
                return grouped[field].resample(time_field).sum()
            elif self.aggregation == 'YOY_GROWTH':
                yearly = grouped[field].resample('Y').sum()
                return yearly.pct_change() * 100
            
            # Window Functions
            elif self.aggregation == 'RUNNING_TOTAL':
                return grouped[field].cumsum()
            elif self.aggregation == 'RANK':
                return grouped[field].rank(method='dense')
            elif self.aggregation == 'MOVING_AVG' and self.window_size:
                return grouped[field].rolling(window=self.window_size).mean()
            
            # Percentile Functions
            elif self.aggregation.startswith('PERCENTILE_'):
                percentile = float(self.aggregation.split('_')[1]) / 100
                return grouped[field].quantile(percentile)
            
            return df[field]
        except Exception as e:
            print(f"Error applying aggregation {self.aggregation}: {str(e)}")
            return df[field]

    def get_pandas_aggregation(self):
        """Convert Django aggregation to Pandas aggregation."""
        agg_map = {
            'COUNT': 'count',
            'SUM': 'sum',
            'AVG': 'mean',
            'MIN': 'min',
            'MAX': 'max',
            'COUNT_DISTINCT': 'nunique',
            'STDDEV': 'std',
            'VARIANCE': 'var',
            'MEDIAN': 'median',
            'PERCENTILE_25': lambda x: x.quantile(0.25),
            'PERCENTILE_50': lambda x: x.quantile(0.50),
            'PERCENTILE_75': lambda x: x.quantile(0.75),
            'PERCENTILE_90': lambda x: x.quantile(0.90),
        }
        return agg_map.get(self.aggregation, 'first')
    
    def format_value(self, value):
        """Format the value according to the column's formatting settings."""
        if value is None:
            return ''
            
        try:
            if self.formatting_type == 'number':
                return f"{float(value):,.{self.decimal_places}f}"
            elif self.formatting_type == 'currency':
                return f"{self.currency_symbol}{float(value):,.{self.decimal_places}f}"
            elif self.formatting_type == 'percentage':
                return f"{float(value) * 100:.{self.decimal_places}f}%"
            elif self.formatting_type == 'date':
                if isinstance(value, str):
                    value = parse(value)
                return value.strftime(self.date_format)
            elif self.formatting_type == 'boolean':
                return 'Yes' if value else 'No'
            else:
                return str(value)
        except (ValueError, TypeError):
            return str(value)
    
    def apply_conditional_formatting(self, value, row_data=None):
        """Apply conditional formatting rules to the value."""
        if not self.conditional_formatting:
            return {}
            
        try:
            rules = self.conditional_formatting.get('rules', [])
            for rule in rules:
                condition = rule['condition']
                if self._evaluate_condition(condition, value, row_data):
                    return rule.get('style', {})
        except Exception:
            return {}
            
        return {}
    
    def _evaluate_condition(self, condition, value, row_data):
        """Safely evaluate a conditional formatting condition."""
        try:
            # Create a safe context for evaluation
            context = {'value': value}
            if row_data:
                context.update(row_data)
            
            # Replace field references with actual values
            for field, field_value in row_data.items():
                condition = condition.replace(f"{{{field}}}", f"row_data['{field}']")
            
            return eval(condition, {"__builtins__": {}}, context)
        except Exception:
            return False

class ReportFilter(models.Model):
    OPERATOR_CHOICES = [
        ('exact', 'Equals'),
        ('icontains', 'Contains'),
        ('gt', 'Greater Than'),
        ('lt', 'Less Than'),
        ('gte', 'Greater Than or Equal'),
        ('lte', 'Less Than or Equal'),
        ('in', 'In'),
        ('range', 'Range'),
        ('isnull', 'Is Null'),
    ]

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='filters')
    field_path = models.CharField(max_length=255)
    operator = models.CharField(max_length=20, choices=OPERATOR_CHOICES)
    value = models.JSONField(help_text="Filter value stored as JSON")
    
    def __str__(self):
        return f"{self.field_path} {self.operator}"

    def apply_filter(self, queryset):
        """Apply this filter to a queryset"""
        try:
            # Get the model and field type
            model = self.report.root_model.model_class()
            field_type = None
            current_model = model
            
            # Get field type by traversing the field path
            field_parts = self.field_path.split('__')
            for part in field_parts:
                field = current_model._meta.get_field(part)
                if hasattr(field, 'get_internal_type'):
                    field_type = field.get_internal_type()
                if hasattr(field, 'related_model'):
                    current_model = field.related_model

            # Process the filter value based on operator and field type
            value = self.value
            if isinstance(value, str):
                if self.operator == 'in':
                    value = [v.strip() for v in value.split(',') if v.strip()]
                elif self.operator == 'range':
                    value = [v.strip() for v in value.split(',') if v.strip()]
                elif self.operator == 'isnull':
                    value = value.lower() == 'true'

            # Convert values based on field type
            if field_type in ['IntegerField', 'FloatField', 'DecimalField']:
                if self.operator == 'in':
                    try:
                        value = [float(v) for v in value]
                    except (ValueError, TypeError):
                        return queryset
                elif self.operator == 'range':
                    try:
                        if len(value) == 2:
                            value = [float(value[0]), float(value[1])]
                    except (ValueError, TypeError):
                        return queryset
                else:
                    try:
                        if not isinstance(value, bool):  # Don't convert boolean values
                            value = float(value)
                    except (ValueError, TypeError):
                        return queryset
            elif field_type in ['DateField', 'DateTimeField'] and self.operator == 'range':
                try:
                    if len(value) == 2:
                        value = [parse(value[0]), parse(value[1])]
                except (ValueError, TypeError):
                    return queryset

            # Build and apply the filter
            if self.operator == 'in':
                if not value:  # Skip empty lists
                    return queryset
                filter_kwargs = {f"{self.field_path}__in": value}
            elif self.operator == 'range':
                if len(value) != 2:  # Skip invalid ranges
                    return queryset
                filter_kwargs = {
                    f"{self.field_path}__gte": value[0],
                    f"{self.field_path}__lte": value[1]
                }
            else:
                filter_kwargs = {f"{self.field_path}__{self.operator}": value}

            return queryset.filter(**filter_kwargs)
            
        except Exception as e:
            print(f"Error applying filter: {str(e)}")
            return queryset

class ReportGrouping(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='groupings')
    field_path = models.CharField(max_length=255)
    order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.report.name} - Group by {self.field_path}"

class CalculatedField(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='calculated_fields')
    name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    formula = models.TextField(help_text="Python expression using column references")
    order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.report.name} - {self.display_name}"

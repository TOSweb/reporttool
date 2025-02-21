from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.db.models import F, Q, Count, Sum, Avg, Min, Max, Model
from django.core.paginator import Paginator
from django.contrib.contenttypes.models import ContentType
from datetime import datetime
import pandas as pd
import json
from dateutil.parser import parse
from .models import Report, ReportColumn, ReportFilter, ReportGrouping, CalculatedField
from .forms import ReportForm, ReportColumnForm, ReportFilterForm, ReportGroupingForm, CalculatedFieldForm
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache
from django.conf import settings
import hashlib
import traceback

def process_report_data(df, report, visible_columns, groupings):
    """Process report data with grouping and aggregation support"""
    has_grouping = groupings.exists()
    data = []
    grand_totals = {}
    group_boundaries = []
    
    # Get formula columns
    formula_columns = [col for col in visible_columns if col.is_formula]
    
    if has_grouping:
        group_fields = [g.field_path for g in groupings]
        print(f"DEBUG: Grouping by: {group_fields}")
        
        try:
            # Store original data for detail rows
            original_df = df.copy()
            
            # Format data for grouping based on field types
            for field in group_fields:
                if field in df.columns:
                    # Get field type from the model
                    field_type = None
                    current_model = report.root_model.model_class()
                    field_parts = field.split('__')
                    
                    for part in field_parts:
                        field_obj = current_model._meta.get_field(part)
                        if hasattr(field_obj, 'get_internal_type'):
                            field_type = field_obj.get_internal_type()
                        if hasattr(field_obj, 'related_model'):
                            current_model = field_obj.related_model
                    
                    # Format based on field type
                    if field_type in ['DateField', 'DateTimeField']:
                        df[field] = pd.to_datetime(df[field]).dt.strftime('%Y-%m-%d')
                    elif field_type in ['DecimalField', 'FloatField']:
                        df[field] = df[field].round(2)
                    elif field_type == 'BooleanField':
                        df[field] = df[field].map({True: 'Yes', False: 'No', None: 'N/A'})
            
            # First, create a grouped DataFrame without aggregations to get record counts
            grouped_df = df.groupby(group_fields, as_index=False).size().rename(columns={'size': 'record_count'})
            
            # Apply aggregations for each column
            agg_results = {}
            for column in visible_columns:
                if column.aggregation and not column.is_formula:  # Skip formula fields for aggregation
                    try:
                        # Apply the column's aggregation
                        agg_result = column.apply_aggregation(df, group_fields)
                        if isinstance(agg_result, pd.Series):
                            agg_results[column.field_path] = agg_result.reset_index(name=column.field_path)
                        else:
                            agg_results[column.field_path] = agg_result
                    except Exception as e:
                        print(f"Error applying aggregation for {column.field_path}: {str(e)}")
            
            # Merge all aggregation results with the grouped DataFrame
            for field_path, agg_result in agg_results.items():
                if isinstance(agg_result, pd.DataFrame):
                    grouped_df = pd.merge(grouped_df, agg_result, on=group_fields, how='left')
                else:
                    grouped_df[field_path] = agg_result
            
            # Calculate grand totals
            for column in visible_columns:
                if column.aggregation and not column.is_formula:  # Skip formula fields for grand totals
                    try:
                        grand_total = column.apply_aggregation(df)
                        if isinstance(grand_total, (pd.Series, pd.DataFrame)):
                            grand_total = grand_total.iloc[0] if len(grand_total) > 0 else None
                        
                        if isinstance(grand_total, (int, float)):
                            grand_totals[column.field_path] = round(grand_total, 2) if isinstance(grand_total, float) else grand_total
                        else:
                            grand_totals[column.field_path] = grand_total
                    except Exception as e:
                        print(f"DEBUG: Error calculating grand total for {column.field_path}: {str(e)}")
                        grand_totals[column.field_path] = 0
            
            # Convert grouped data to list of dicts with detail rows
            group_boundaries = []  # Track group start and end indices
            
            for idx, (_, group_row) in enumerate(grouped_df.iterrows()):
                group_start = len(data)
                
                # Add group row
                group_data = group_row.to_dict()
                group_data['is_group_row'] = True
                group_data['is_expanded'] = True
                
                # Apply formulas for group row
                for column in formula_columns:
                    group_data[column.field_path] = column.apply_formula(group_data)
                
                # Format numeric values in group data
                for key, value in group_data.items():
                    if isinstance(value, (int, float)) and key != 'record_count':
                        group_data[key] = round(value, 2) if isinstance(value, float) else value
                
                # Calculate group level
                try:
                    non_null_groups = [f for f in group_fields if pd.notna(group_data.get(f))]
                    if non_null_groups:
                        max_depth = max(len(f.split('__')) for f in group_fields)
                        current_depth = max(len(f.split('__')) for f in non_null_groups)
                        group_data['group_level'] = current_depth - 1
                    else:
                        group_data['group_level'] = 0
                except ValueError:
                    group_data['group_level'] = 0
                
                data.append(group_data)
                
                # Get detail rows for this group
                filter_conditions = pd.Series(True, index=original_df.index)
                for field in group_fields:
                    filter_conditions &= (original_df[field] == group_row[field])
                
                detail_df = original_df[filter_conditions]
                
                # Calculate group totals using the new aggregation method
                group_totals = {}
                for column in visible_columns:
                    if column.aggregation and not column.is_formula:  # Skip formula fields for group totals
                        try:
                            group_total = column.apply_aggregation(detail_df)
                            if isinstance(group_total, (pd.Series, pd.DataFrame)):
                                group_total = group_total.iloc[0] if len(group_total) > 0 else None
                            
                            if isinstance(group_total, (int, float)):
                                group_totals[column.field_path] = round(group_total, 2) if isinstance(group_total, float) else group_total
                            else:
                                group_totals[column.field_path] = group_total
                        except Exception as e:
                            print(f"DEBUG: Error calculating group total for {column.field_path}: {str(e)}")
                            group_totals[column.field_path] = 0
                
                # Convert detail rows to dicts and add to data
                detail_rows = detail_df.to_dict('records')
                for detail_row in detail_rows:
                    # Apply formulas for detail row
                    for column in formula_columns:
                        detail_row[column.field_path] = column.apply_formula(detail_row)
                    
                    # Format values based on field type
                    for key, value in detail_row.items():
                        if isinstance(value, (int, float)):
                            detail_row[key] = round(value, 2) if isinstance(value, float) else value
                    
                    detail_row['is_group_row'] = False
                    detail_row['is_detail_row'] = True
                    detail_row['group_level'] = group_data['group_level']
                    data.append(detail_row)
                
                # Add subtotal row for groups
                subtotal_row = group_data.copy()
                subtotal_row.update(group_totals)
                subtotal_row['is_subtotal'] = True
                data.append(subtotal_row)
                
                group_boundaries.append((group_start, len(data)))
        
        except Exception as e:
            print(f"DEBUG: Error in grouping/aggregation: {str(e)}")
            data = []
            grand_totals = {}
            group_boundaries = []  # Reset group_boundaries on error
    else:
        # No grouping, just format the data
        for row in df.to_dict('records'):
            formatted_row = {}
            # First copy all regular fields
            for key, value in row.items():
                if isinstance(value, (int, float)):
                    formatted_row[key] = round(value, 2) if isinstance(value, float) else value
                else:
                    formatted_row[key] = value
            
            # Then apply formulas
            for column in formula_columns:
                formatted_row[column.field_path] = column.apply_formula(formatted_row)
            
            data.append(formatted_row)
        
        # Calculate totals
        for column in visible_columns:
            if column.aggregation and not column.is_formula:
                try:
                    total = column.apply_aggregation(df)
                    if isinstance(total, (pd.Series, pd.DataFrame)):
                        total = total.iloc[0] if len(total) > 0 else None
                    
                    if isinstance(total, (int, float)):
                        grand_totals[column.field_path] = round(total, 2) if isinstance(total, float) else total
                    else:
                        grand_totals[column.field_path] = total
                except Exception as e:
                    print(f"Error calculating total for {column.field_path}: {str(e)}")
                    grand_totals[column.field_path] = 0
    
    return data, grand_totals, group_boundaries if has_grouping else None

class ReportListView(LoginRequiredMixin, ListView):
    model = Report
    template_name = 'report/report_list.html'
    context_object_name = 'reports'
    paginate_by = 10

class ReportCreateView(LoginRequiredMixin, CreateView):
    model = Report
    form_class = ReportForm
    template_name = 'report/report_form.html'
    success_url = reverse_lazy('report:report_list')

class ReportUpdateView(LoginRequiredMixin, UpdateView):
    model = Report
    form_class = ReportForm
    template_name = 'report/report_form.html'
    success_url = reverse_lazy('report:report_list')

class ReportBuilderView(LoginRequiredMixin, DetailView):
    model = Report
    template_name = 'report/report_builder.html'
    
    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        context = self.get_context_data(object=self.object)
        
        # If it's an AJAX request, return only the table content
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return render(request, 'report/partials/preview_table.html', context)
        
        return self.render_to_response(context)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        report = self.get_object()
        
        # Get the current page and page size from request
        page = self.request.GET.get('page', 1)
        page_size = int(self.request.GET.get('page_size', 10))
        
        # Get sorting parameters
        sort_field = self.request.GET.get('sort_field')
        sort_direction = self.request.GET.get('sort_direction', 'asc')
        
        # Validate page size
        allowed_page_sizes = [10, 25, 50, 100]
        if page_size not in allowed_page_sizes:
            page_size = 10
        
        # Get model fields and organize them into groups
        model = report.root_model.model_class()
        field_groups = []
        
        # Add direct fields group
        direct_fields = []
        for field in model._meta.get_fields():
            if not field.is_relation:
                direct_fields.append({
                    'name': field.name,
                    'verbose_name': field.verbose_name.title() if hasattr(field, 'verbose_name') else field.name.title(),
                    'path': field.name,
                    'icon': self.get_field_icon(field),
                    'type': field.get_internal_type(),
                    'operators': self.get_field_operators(field)
                })
        
        if direct_fields:
            field_groups.append({
                'name': f'{model._meta.verbose_name.title()} Fields',
                'fields': sorted(direct_fields, key=lambda x: x['name'])
            })
        
        # Add direct relations group
        direct_relations = []
        for field in model._meta.get_fields():
            if field.is_relation and hasattr(field, 'related_model'):
                related_model = field.related_model
                direct_relations.append({
                    'name': field.name,
                    'verbose_name': field.verbose_name.title() if hasattr(field, 'verbose_name') else field.name.title(),
                    'path': field.name,
                    'icon': 'fa-link',
                    'type': 'Relation',
                    'related_model': related_model._meta.verbose_name.title(),
                    'related_app': related_model._meta.app_label,
                    'fields': self.get_related_model_fields(related_model, field.name)
                })
        
        if direct_relations:
            field_groups.append({
                'name': 'Related Models',
                'fields': sorted(direct_relations, key=lambda x: x['name'])
            })
        
        # Add indirect relations (through related models)
        for relation in direct_relations:
            related_model = model._meta.get_field(relation['name']).related_model
            indirect_relations = []
            
            for field in related_model._meta.get_fields():
                if field.is_relation and hasattr(field, 'related_model'):
                    if field.related_model != model:  # Avoid circular references
                        indirect_model = field.related_model
                        base_path = f"{relation['name']}__{field.name}"
                        indirect_relations.append({
                            'name': f"{relation['name']} → {field.name}",
                            'verbose_name': f"{relation['verbose_name']} → {field.verbose_name.title() if hasattr(field, 'verbose_name') else field.name.title()}",
                            'path': base_path,
                            'icon': 'fa-project-diagram',
                            'type': 'Indirect Relation',
                            'related_model': indirect_model._meta.verbose_name.title(),
                            'related_app': indirect_model._meta.app_label,
                            'fields': self.get_related_model_fields(indirect_model, base_path)
                        })
            
            if indirect_relations:
                field_groups.append({
                    'name': f'{relation["verbose_name"]} Related Models',
                    'fields': sorted(indirect_relations, key=lambda x: x['name'])
                })

        context.update({
            'field_groups': field_groups,
            'column_form': ReportColumnForm(),
            'filter_form': ReportFilterForm(),
            'grouping_form': ReportGroupingForm(),
            'calculated_field_form': CalculatedFieldForm(),
            'preview_data': self.get_preview_data(report, page),
            'operators': self.get_all_operators(),
            'sort_field': sort_field,
            'sort_direction': sort_direction
        })
        return context
    
    def get_field_operators(self, field):
        """Return available operators based on field type"""
        field_type = field.get_internal_type()
        operators = {
            'CharField': ['exact', 'icontains', 'istartswith', 'iendswith', 'isnull'],
            'TextField': ['icontains', 'isnull'],
            'IntegerField': ['exact', 'gt', 'gte', 'lt', 'lte', 'in', 'range', 'isnull'],
            'FloatField': ['exact', 'gt', 'gte', 'lt', 'lte', 'in', 'range', 'isnull'],
            'DecimalField': ['exact', 'gt', 'gte', 'lt', 'lte', 'in', 'range', 'isnull'],
            'DateField': ['exact', 'gt', 'gte', 'lt', 'lte', 'range', 'year', 'month', 'day', 'isnull'],
            'DateTimeField': ['exact', 'gt', 'gte', 'lt', 'lte', 'range', 'year', 'month', 'day', 'isnull'],
            'BooleanField': ['exact', 'isnull'],
            'EmailField': ['exact', 'icontains', 'isnull'],
            'URLField': ['exact', 'icontains', 'isnull']
        }
        return operators.get(field_type, ['exact', 'isnull'])
    
    def get_all_operators(self):
        """Return all available operators with their display names"""
        return {
            'exact': 'Equals',
            'icontains': 'Contains',
            'istartswith': 'Starts with',
            'iendswith': 'Ends with',
            'gt': 'Greater than',
            'gte': 'Greater than or equal',
            'lt': 'Less than',
            'lte': 'Less than or equal',
            'in': 'In list',
            'range': 'Range',
            'year': 'Year equals',
            'month': 'Month equals',
            'day': 'Day equals',
            'isnull': 'Is empty',
        }
    
    def get_related_model_fields(self, model, base_path):
        """Get fields from a related model"""
        fields = []
        for field in model._meta.get_fields():
            if not field.is_relation:
                fields.append({
                    'name': field.name,
                    'verbose_name': field.verbose_name.title() if hasattr(field, 'verbose_name') else field.name.title(),
                    'path': f"{base_path}__{field.name}",
                    'icon': self.get_field_icon(field),
                    'type': field.get_internal_type(),
                    'operators': self.get_field_operators(field)
                })
        return sorted(fields, key=lambda x: x['name'])
    
    def get_field_icon(self, field):
        """Return appropriate Font Awesome icon class based on field type"""
        field_type = field.get_internal_type()
        icons = {
            'CharField': 'fa-font',
            'TextField': 'fa-align-left',
            'IntegerField': 'fa-hashtag',
            'FloatField': 'fa-calculator',
            'DecimalField': 'fa-calculator',
            'DateField': 'fa-calendar',
            'DateTimeField': 'fa-clock',
            'BooleanField': 'fa-check-square',
            'EmailField': 'fa-envelope',
            'FileField': 'fa-file',
            'ImageField': 'fa-image',
            'URLField': 'fa-link'
        }
        return icons.get(field_type, 'fa-cube')
    
    def get_preview_data(self, report, page=1):
        """Get preview data with grouping and aggregation support using pandas"""
        try:
            # Convert page to integer and handle invalid values
            try:
                page = int(page)
                if page < 1:
                    page = 1
            except (TypeError, ValueError):
                page = 1

            # Get page size from request or use default
            try:
                page_size = int(self.request.GET.get('page_size', 10))
                if page_size not in [10, 25, 50, 100]:
                    page_size = 10
            except (TypeError, ValueError):
                page_size = 10

            # Get the queryset and apply filters
            queryset = self.get_report_queryset(report)
            
            # Get visible columns and groupings
            visible_columns = report.columns.filter(is_visible=True)
            column_fields = [col.field_path for col in visible_columns]
            groupings = report.groupings.all().order_by('order')
            
            # Handle empty queryset or no columns
            if not queryset.exists() or not column_fields:
                return self.create_empty_page(page_size, page)
            
            # Get the data with only visible columns
            queryset = queryset.values(*column_fields)
            
            # Convert queryset to pandas DataFrame
            df = pd.DataFrame(list(queryset))
            if df.empty:
                return self.create_empty_page(page_size, page)
            
            # Apply sorting if specified
            sort_field = self.request.GET.get('sort_field')
            sort_direction = self.request.GET.get('sort_direction', 'asc')
            if sort_field and sort_field in df.columns:
                ascending = sort_direction != 'desc'
                df = df.sort_values(by=sort_field, ascending=ascending)
            
            # Process data using the global process_report_data function
            data, grand_totals, group_boundaries = process_report_data(df, report, visible_columns, groupings)
            
            if group_boundaries:
                # Calculate pagination based on group boundaries
                total_groups = len(group_boundaries)
                groups_per_page = max(1, page_size // 2)  # At least show one group per page
                total_pages = (total_groups + groups_per_page - 1) // groups_per_page
                current_page = min(max(1, page), total_pages)
                
                # Get the groups for the current page
                start_group = (current_page - 1) * groups_per_page
                end_group = min(start_group + groups_per_page, total_groups)
                
                if start_group < len(group_boundaries):
                    page_start = group_boundaries[start_group][0]
                    if end_group > 0:
                        page_end = group_boundaries[min(end_group - 1, len(group_boundaries) - 1)][1]
                    else:
                        page_end = len(data)
                    
                    # Create custom page object for grouped data
                    page_obj = self.create_group_aware_page(
                        data[page_start:page_end],
                        current_page,
                        total_pages,
                        total_groups,
                        groups_per_page,
                        grand_totals
                    )
                    return page_obj
            
            # Regular pagination for non-grouped data
            paginator = Paginator(data, page_size)
            
            try:
                page_obj = paginator.page(page)
            except Exception:
                # If page is out of range, deliver last page
                page_obj = paginator.page(paginator.num_pages)
            
            page_obj.grand_totals = grand_totals
            return page_obj
            
        except Exception as e:
            print(f"Error in get_preview_data: {str(e)}")
            return self.create_empty_page(page_size, page)

    def create_empty_page(self, page_size, page):
        """Create an empty page object for when there's no data"""
        paginator = Paginator([], page_size)
        try:
            page_obj = paginator.page(page)
        except Exception:
            page_obj = paginator.page(1)
        page_obj.grand_totals = {}
        return page_obj

    def create_group_aware_page(self, object_list, number, total_pages, total_objects, groups_per_page, grand_totals):
        """Create a custom page object for grouped data"""
        class GroupAwarePage:
            def __init__(self, object_list, number, total_pages, total_objects, groups_per_page):
                self.object_list = object_list
                self.number = number
                self.has_previous = number > 1
                self.has_next = number < total_pages
                self.paginator = type('Paginator', (), {
                    'count': total_objects,
                    'num_pages': total_pages,
                    'page_range': range(1, total_pages + 1)
                })
                self.groups_per_page = groups_per_page
            
            def __iter__(self):
                return iter(self.object_list)
            
            def __len__(self):
                return len(self.object_list)
            
            def has_other_pages(self):
                return self.has_previous or self.has_next
            
            def previous_page_number(self):
                return self.number - 1 if self.has_previous else None
            
            def next_page_number(self):
                return self.number + 1 if self.has_next else None
            
            def start_index(self):
                return ((self.number - 1) * self.groups_per_page) + 1
            
            def end_index(self):
                return min(self.start_index() + self.groups_per_page - 1, self.paginator.count)
        
        page_obj = GroupAwarePage(object_list, number, total_pages, total_objects, groups_per_page)
        page_obj.grand_totals = grand_totals
        return page_obj

    def get_report_queryset(self, report):
        """Get the base queryset for the report with filters and sorting applied"""
        print("DEBUG: Starting get_report_queryset")
        # Get the model class from the content type
        model = report.root_model.model_class()
        queryset = model.objects.all()
        print(f"DEBUG: Initial queryset model: {model.__name__}")

        # Apply filters
        # Group filters by field_path
        filters_by_field = {}
        for filter_obj in report.filters.all():
            if filter_obj.field_path not in filters_by_field:
                filters_by_field[filter_obj.field_path] = []
            filters_by_field[filter_obj.field_path].append(filter_obj)
        
        print(f"DEBUG: Filters by field: {filters_by_field}")

        # Process each field's filters and apply them progressively
        for field_path, field_filters in filters_by_field.items():
            print(f"DEBUG: Processing filters for field: {field_path}")
            # Create a Q object for OR conditions within the same field
            field_q = Q()

            # Get field type
            field_type = None
            current_model = model
            field_parts = field_path.split('__')
            
            # Get the actual field and its type
            for part in field_parts:
                field = current_model._meta.get_field(part)
                if hasattr(field, 'get_internal_type'):
                    field_type = field.get_internal_type()
                if hasattr(field, 'related_model'):
                    current_model = field.related_model
            
            print(f"DEBUG: Field type: {field_type}")

            # Process each filter for this field
            for filter_obj in field_filters:
                try:
                    value = filter_obj.value
                    operator = filter_obj.operator
                    print(f"DEBUG: Processing filter - operator: {operator}, value: {value}")

                    # Convert value based on field type and operator
                    if isinstance(value, str):
                        if operator == 'in':
                            value = [v.strip() for v in value.split(',') if v.strip()]
                        elif operator == 'range':
                            value = [v.strip() for v in value.split(',') if v.strip()]
                        elif operator == 'isnull':
                            value = value.lower() == 'true'

                    # Build filter kwargs based on operator and field type
                    filter_q = Q()
                    try:
                        if operator == 'in':
                            if not value:  # Skip empty lists
                                continue
                            if field_type in ['IntegerField', 'FloatField', 'DecimalField']:
                                try:
                                    value = [float(v) for v in value]
                                except (ValueError, TypeError):
                                    print(f"DEBUG: Error converting list values for field {field_path}")
                                    continue
                            filter_q = Q(**{f"{field_path}__in": value})
                        elif operator == 'range':
                            if len(value) != 2:  # Skip invalid ranges
                                continue
                            if field_type in ['IntegerField', 'FloatField', 'DecimalField']:
                                try:
                                    start, end = float(value[0]), float(value[1])
                                    filter_q = Q(**{f"{field_path}__gte": start}) & Q(**{f"{field_path}__lte": end})
                                except (ValueError, TypeError):
                                    print(f"DEBUG: Error converting range values for field {field_path}")
                                    continue
                            elif field_type in ['DateField', 'DateTimeField']:
                                try:
                                    start, end = parse(value[0]), parse(value[1])
                                    filter_q = Q(**{f"{field_path}__gte": start}) & Q(**{f"{field_path}__lte": end})
                                except (ValueError, TypeError):
                                    print(f"DEBUG: Error converting date range values for field {field_path}")
                                    continue
                        else:
                            filter_q = Q(**{f"{field_path}__{operator}": value})
                        
                        print(f"DEBUG: Adding filter Q object: {filter_q}")
                        field_q |= filter_q
                    except Exception as e:
                        print(f"DEBUG: Error building filter: {str(e)}")
                        continue
                except Exception as e:
                    print(f"DEBUG: Error processing filter: {str(e)}")
                    continue

            if field_q:
                print(f"DEBUG: Applying field filters: {field_q}")
                queryset = queryset.filter(field_q)
                print(f"DEBUG: Queryset after filter: {str(queryset.query)}")

        return queryset

@require_http_methods(["GET"])
def execute_report(request, report_id):
    """View to execute the report and show results"""
    try:
        report = get_object_or_404(Report, id=report_id)
        
        # Check if JSON response is requested
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return execute_report_json(request, report)
        
        # Get pagination parameters
        try:
            page = max(1, int(request.GET.get('page', 1)))
        except (TypeError, ValueError):
            page = 1
            
        try:
            per_page = int(request.GET.get('per_page', 50))
            if per_page not in [10, 25, 50, 100]:
                per_page = 50
        except (TypeError, ValueError):
            per_page = 50
        
        # Get visible columns
        visible_columns = report.columns.filter(is_visible=True)
        if not visible_columns.exists():
            return render(request, 'report/report_results.html', {
                'report': report,
                'error': 'No visible columns defined for this report.',
                'debug': settings.DEBUG
            })
        
        # Get column fields
        column_fields = [col.field_path for col in visible_columns]
        
        # Get base queryset and apply filters
        queryset = report.get_optimized_queryset()
        for filter_obj in report.filters.all():
            try:
                queryset = filter_obj.apply_filter(queryset)
            except Exception as e:
                print(f"Error applying filter {filter_obj}: {str(e)}")
                continue
        
        # Get data with visible columns
        queryset = queryset.values(*column_fields)
        
        # Convert to DataFrame
        df = pd.DataFrame(list(queryset))
        
        if df.empty:
            return render(request, 'report/report_results.html', {
                'report': report,
                'visible_columns': visible_columns,
                'data': [],
                'total': 0,
                'page': page,
                'per_page': per_page,
                'total_pages': 0
            })
        
        # Apply sorting
        sort_field = request.GET.get('sort_field')
        sort_direction = request.GET.get('sort_direction', 'asc')
        if sort_field and sort_field in df.columns:
            ascending = sort_direction != 'desc'
            df = df.sort_values(by=sort_field, ascending=ascending)
        
        # Process data
        data, grand_totals, group_boundaries = process_report_data(df, report, visible_columns, report.groupings.all())
        
        # Apply pagination
        total_records = len(data)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_data = data[start_idx:end_idx]
        
        # Calculate pagination info
        total_pages = (total_records + per_page - 1) // per_page
        start_index = start_idx + 1 if total_records > 0 else 0
        end_index = min(end_idx, total_records)
        
        # Generate page range
        if total_pages <= 5:
            page_range = range(1, total_pages + 1)
        else:
            if page <= 3:
                page_range = range(1, 6)
            elif page >= total_pages - 2:
                page_range = range(total_pages - 4, total_pages + 1)
            else:
                page_range = range(page - 2, page + 3)
        
        context = {
            'report': report,
            'visible_columns': visible_columns,
            'data': page_data,
            'total': total_records,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'grand_totals': grand_totals,
            'start_index': start_index,
            'end_index': end_index,
            'page_range': page_range,
            'debug': settings.DEBUG
        }
        
        # Handle Excel export
        if request.GET.get('export') == 'excel':
            return export_to_excel(data, visible_columns, report.name)
        
        return render(request, 'report/report_results.html', context)
        
    except Report.DoesNotExist:
        return render(request, 'report/report_results.html', {
            'error': 'Report not found.',
            'debug': settings.DEBUG
        })
    except Exception as e:
        print(f"Error executing report: {str(e)}")
        return render(request, 'report/report_results.html', {
            'error': str(e) if settings.DEBUG else 'An error occurred while executing the report.',
            'traceback': traceback.format_exc() if settings.DEBUG else None,
            'debug': settings.DEBUG
        })

def execute_report_json(request, report):
    """Execute report and return JSON response"""
    try:
        # Generate cache key
        cache_key = f"report_{report.id}_{hashlib.md5(str(request.GET).encode()).hexdigest()}"
        cached_result = cache.get(cache_key)
        
        if cached_result and not request.GET.get('bypass_cache'):
            return JsonResponse(cached_result)
        
        # Get pagination parameters
        try:
            page = max(1, int(request.GET.get('page', 1)))
        except (TypeError, ValueError):
            page = 1
            
        try:
            per_page = int(request.GET.get('per_page', 50))
            if per_page not in [10, 25, 50, 100]:
                per_page = 50
        except (TypeError, ValueError):
            per_page = 50
        
        # Get visible columns
        visible_columns = report.columns.filter(is_visible=True)
        if not visible_columns.exists():
            return JsonResponse({
                'error': 'No visible columns defined for this report.',
                'data': [],
                'total': 0,
                'page': page,
                'per_page': per_page,
                'total_pages': 0
            })
        
        # Get column fields
        column_fields = [col.field_path for col in visible_columns]
        
        # Get base queryset and apply filters
        queryset = report.get_optimized_queryset()
        for filter_obj in report.filters.all():
            try:
                queryset = filter_obj.apply_filter(queryset)
            except Exception as e:
                print(f"Error applying filter {filter_obj}: {str(e)}")
                continue
        
        # Get data with visible columns
        queryset = queryset.values(*column_fields)
        
        # Convert to DataFrame
        df = pd.DataFrame(list(queryset))
        
        if df.empty:
            return JsonResponse({
                'data': [],
                'total': 0,
                'page': page,
                'per_page': per_page,
                'total_pages': 0
            })
        
        # Apply sorting
        sort_field = request.GET.get('sort_field')
        sort_direction = request.GET.get('sort_direction', 'asc')
        if sort_field and sort_field in df.columns:
            ascending = sort_direction != 'desc'
            df = df.sort_values(by=sort_field, ascending=ascending)
        
        # Process data
        data, grand_totals, group_boundaries = process_report_data(df, report, visible_columns, report.groupings.all())
        
        # Apply pagination
        total_records = len(data)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_data = data[start_idx:end_idx]
        
        result = {
            'data': page_data,
            'total': total_records,
            'page': page,
            'per_page': per_page,
            'total_pages': (total_records + per_page - 1) // per_page,
            'grand_totals': grand_totals
        }
        
        # Cache the result
        cache.set(cache_key, result, timeout=getattr(settings, 'REPORT_CACHE_TIMEOUT', 300))
        
        return JsonResponse(result)
        
    except Exception as e:
        print(f"Error executing report: {str(e)}")
        return JsonResponse({
            'error': str(e) if settings.DEBUG else 'An error occurred while executing the report.',
            'traceback': traceback.format_exc() if settings.DEBUG else None,
            'data': [],
            'total': 0,
            'page': 1,
            'per_page': 50,
            'total_pages': 0
        }, status=500)

def export_to_excel(data, visible_columns, report_name):
    """Export report data to Excel"""
    import xlsxwriter
    from io import BytesIO
    
    # Create a new workbook in memory
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet()
    
    # Add headers
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#f8f9fa',
        'border': 1
    })
    for col, column in enumerate(visible_columns):
        worksheet.write(0, col, column.display_name, header_format)
    
    # Add data
    for row, record in enumerate(data, start=1):
        for col, column in enumerate(visible_columns):
            value = record.get(column.field_path)
            if isinstance(value, (int, float)):
                worksheet.write_number(row, col, value)
            else:
                worksheet.write(row, col, str(value) if value is not None else '')
    
    # Close the workbook
    workbook.close()
    
    # Prepare the response
    output.seek(0)
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{report_name}.xlsx"'
    
    return response

def get_model_fields(request):
    """AJAX endpoint to get available fields for a model"""
    model_id = request.GET.get('model_id')
    content_type = get_object_or_404(ContentType, id=model_id)
    model = content_type.model_class()
    model_name = model._meta.verbose_name.title()
    
    # Group fields by their type (direct fields, related fields)
    direct_fields = []
    related_fields = []
    
    for field in model._meta.get_fields():
        if hasattr(field, 'get_internal_type'):
            field_info = {
                'name': field.name,
                'verbose_name': getattr(field, 'verbose_name', field.name).title(),
                'type': field.get_internal_type(),
                'is_relation': field.is_relation,
                'path': field.name
            }
            
            if field.is_relation:
                field_info.update({
                    'related_model': field.related_model._meta.verbose_name.title(),
                    'related_model_app': field.related_model._meta.app_label
                })
                related_fields.append(field_info)
            else:
                direct_fields.append(field_info)
    
    return JsonResponse({
        'model_name': model_name,
        'direct_fields': direct_fields,
        'related_fields': related_fields
    })

def get_related_fields(request):
    """AJAX endpoint to get fields from related models"""
    model_id = request.GET.get('model_id')
    field_path = request.GET.get('field_path', '')
    
    content_type = get_object_or_404(ContentType, id=model_id)
    model = content_type.model_class()
    
    if field_path:
        parts = field_path.split('__')
        for part in parts:
            field = model._meta.get_field(part)
            if field.is_relation:
                model = field.related_model
    
    model_name = model._meta.verbose_name.title()
    direct_fields = []
    related_fields = []
    
    for field in model._meta.get_fields():
        if hasattr(field, 'get_internal_type'):
            field_info = {
                'name': field.name,
                'verbose_name': getattr(field, 'verbose_name', field.name).title(),
                'type': field.get_internal_type(),
                'is_relation': field.is_relation,
                'path': field.name
            }
            
            if field.is_relation:
                field_info.update({
                    'related_model': field.related_model._meta.verbose_name.title(),
                    'related_model_app': field.related_model._meta.app_label
                })
                related_fields.append(field_info)
            else:
                direct_fields.append(field_info)
    
    return JsonResponse({
        'model_name': model_name,
        'direct_fields': direct_fields,
        'related_fields': related_fields
    })

def save_report_column(request, report_id):
    """AJAX endpoint to add/update report columns"""
    report = get_object_or_404(Report, id=report_id)
    if request.method == 'POST':
        # Handle save state request
        if 'save_state' in request.POST:
            try:
                # Save current state (columns, filters, etc.)
                # You might want to add additional state saving logic here
                return JsonResponse({'success': True})
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})

        # Handle column deletion
        if 'delete' in request.POST:
            column_id = request.POST.get('delete')
            field_path = request.POST.get('field_path')
            
            try:
                # Delete any filters associated with this column
                report.filters.filter(field_path=field_path).delete()
                
                # Delete the column
                ReportColumn.objects.filter(id=column_id, report=report).delete()
                
                # Reorder remaining columns
                for index, column in enumerate(report.columns.all()):
                    column.order = index
                    column.save()
                
                return JsonResponse({'success': True})
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})
        
        # Handle column reordering
        elif 'order' in request.POST:
            try:
                order = json.loads(request.POST.get('order'))
                for index, column_id in enumerate(order):
                    ReportColumn.objects.filter(id=column_id, report=report).update(order=index)
                return JsonResponse({'success': True})
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})
        
        # Handle column addition
        else:
            field_path = request.POST.get('field_path')
            if not field_path:
                return JsonResponse({'success': False, 'error': 'Field path is required'})
                
            display_name = request.POST.get('display_name', field_path.split('__')[-1].replace('_', ' ').title())
            
            # Create new column
            try:
                column = ReportColumn.objects.create(
                    report=report,
                    name=field_path.split('__')[-1],
                    field_path=field_path,
                    display_name=display_name,
                    order=ReportColumn.objects.filter(report=report).count()
                )
                return JsonResponse({
                    'success': True,
                    'column': {
                        'id': column.id,
                        'display_name': column.display_name,
                        'field_path': column.field_path
                    }
                })
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})
                
    return JsonResponse({'success': False, 'error': 'Invalid request'})

def get_field_values(request, report_id):
    """AJAX endpoint to get unique values for a field"""
    report = get_object_or_404(Report, id=report_id)
    field_path = request.GET.get('field_path')
    
    try:
        # Get the model class and base queryset
        model = report.root_model.model_class()
        queryset = model.objects.all()
        
        # Handle related fields
        if '__' in field_path:
            # For related fields, we need to traverse the relationships
            parts = field_path.split('__')
            for part in parts[:-1]:
                field = model._meta.get_field(part)
                if field.is_relation:
                    model = field.related_model
        
        # Get unique values
        values = queryset.values_list(field_path, flat=True).distinct().order_by(field_path)
        values = [str(v) for v in values if v is not None]  # Convert to strings and filter out None
        
        return JsonResponse({
            'success': True,
            'values': values
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

def save_filter(request, report_id):
    """AJAX endpoint to add/update report filters"""
    report = get_object_or_404(Report, id=report_id)
    if request.method == 'POST':
        field_path = request.POST.get('field_path')
        operator = request.POST.get('operator')
        value = request.POST.get('value')

        # Handle special value cases
        if operator == 'in':
            value = [v.strip() for v in value.split(',')]
        elif operator == 'range':
            start, end = value.split(',')
            value = [start.strip(), end.strip()]
        elif operator == 'isnull':
            value = value.lower() == 'true'

        filter_obj = ReportFilter.objects.create(
            report=report,
            field_path=field_path,
            operator=operator,
            value=value
        )
        
        return JsonResponse({
            'success': True,
            'filter': {
                'id': filter_obj.id,
                'field_path': filter_obj.field_path,
                'operator': filter_obj.operator,
                'value': value
            }
        })
    return JsonResponse({'success': False, 'error': 'Invalid request'})

def save_aggregation(request, report_id):
    """AJAX endpoint to add/update report aggregations"""
    report = get_object_or_404(Report, id=report_id)
    if request.method == 'POST':
        field_path = request.POST.get('field_path')
        aggregation = request.POST.get('aggregation')
        
        if not field_path or not aggregation:
            return JsonResponse({'success': False, 'error': 'Field path and aggregation are required'})
        
        try:
            # Check if column already exists
            column = report.columns.filter(field_path=field_path).first()
            if column:
                # Update existing column
                column.aggregation = aggregation
                column.save()
            else:
                # Create new column with aggregation
                display_name = field_path.split('__')[-1].replace('_', ' ').title()
                column = ReportColumn.objects.create(
                    report=report,
                    name=field_path.split('__')[-1],
                    field_path=field_path,
                    display_name=f"{aggregation} of {display_name}",
                    order=ReportColumn.objects.filter(report=report).count(),
                    aggregation=aggregation
                )
            
            return JsonResponse({
                'success': True,
                'column': {
                    'id': column.id,
                    'display_name': column.display_name,
                    'field_path': column.field_path,
                    'aggregation': column.aggregation
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

def save_calculated_field(request, report_id):
    """AJAX endpoint to add/update calculated fields"""
    report = get_object_or_404(Report, id=report_id)
    if request.method == 'POST':
        name = request.POST.get('name')
        formula = request.POST.get('formula')
        
        calc_field = CalculatedField.objects.create(
            report=report,
            name=name,
            display_name=name,
            formula=formula,
            order=CalculatedField.objects.filter(report=report).count()
        )
        
        return JsonResponse({
            'success': True,
            'field': {
                'id': calc_field.id,
                'name': calc_field.name,
                'display_name': calc_field.display_name,
                'formula': calc_field.formula
            }
        })
    return JsonResponse({'success': False, 'error': 'Invalid request'})

def delete_filter(request, report_id):
    """AJAX endpoint to delete a specific filter"""
    if request.method == 'POST':
        report = get_object_or_404(Report, id=report_id)
        filter_id = request.POST.get('filter_id')
        if filter_id:
            report.filters.filter(id=filter_id).delete()
            return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'error': 'Invalid request'})

def reset_filters(request, report_id):
    """AJAX endpoint to reset all filters for a report"""
    if request.method == 'POST':
        report = get_object_or_404(Report, id=report_id)
        report.filters.all().delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'error': 'Invalid request'})

def save_grouping(request, report_id):
    """AJAX endpoint to add/update report groupings"""
    report = get_object_or_404(Report, id=report_id)
    if request.method == 'POST':
        field_path = request.POST.get('field_path')
        
        if not field_path:
            return JsonResponse({'success': False, 'error': 'Field path is required'})
        
        # Create new grouping
        try:
            grouping = ReportGrouping.objects.create(
                report=report,
                field_path=field_path,
                order=ReportGrouping.objects.filter(report=report).count()
            )
            return JsonResponse({
                'success': True,
                'group': {
                    'id': grouping.id,
                    'field_path': grouping.field_path
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})

def delete_grouping(request, report_id):
    """AJAX endpoint to delete a specific grouping"""
    if request.method == 'POST':
        report = get_object_or_404(Report, id=report_id)
        group_id = request.POST.get('group_id')
        if group_id:
            try:
                report.groupings.filter(id=group_id).delete()
                # Reorder remaining groups
                for index, group in enumerate(report.groupings.all()):
                    group.order = index
                    group.save()
                return JsonResponse({'success': True})
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})

def update_grouping_order(request, report_id):
    """AJAX endpoint to update the order of groupings"""
    if request.method == 'POST':
        report = get_object_or_404(Report, id=report_id)
        try:
            order = json.loads(request.POST.get('order', '[]'))
            for index, group_id in enumerate(order):
                ReportGrouping.objects.filter(id=group_id, report=report).update(order=index)
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})

def delete_aggregation(request, report_id):
    """AJAX endpoint to delete report aggregations"""
    report = get_object_or_404(Report, id=report_id)
    if request.method == 'POST':
        column_id = request.POST.get('column_id')
        
        try:
            # Get the column and remove its aggregation
            column = report.columns.get(id=column_id)
            column.aggregation = ''
            column.save()
            
            return JsonResponse({'success': True})
        except ReportColumn.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Column not found'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@require_http_methods(["POST"])
def add_column(request, report_id):
    """Add a new column to the report"""
    try:
        report = get_object_or_404(Report, id=report_id)
        
        # Get the next order value
        max_order = report.columns.aggregate(Max('order'))['order__max'] or 0
        next_order = max_order + 1
        
        # Create the column
        column = ReportColumn.objects.create(
            report=report,
            name=request.POST.get('display_name'),  # Use display_name as name initially
            display_name=request.POST.get('display_name'),
            field_path=request.POST.get('field_path', ''),  # Empty for formula fields
            order=next_order,
            is_visible=request.POST.get('is_visible') == 'true',
            formula=request.POST.get('formula'),
            is_formula=request.POST.get('is_formula') == 'true'
        )
        
        return JsonResponse({
            'success': True,
            'column': {
                'id': column.id,
                'name': column.name,
                'display_name': column.display_name,
                'field_path': column.field_path,
                'is_formula': column.is_formula,
                'formula': column.formula,
                'is_visible': column.is_visible
            }
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@require_http_methods(["GET"])
def get_column(request):
    """Get column details"""
    try:
        column_id = request.GET.get('id')
        column = get_object_or_404(ReportColumn, id=column_id)
        
        return JsonResponse({
            'success': True,
            'id': column.id,
            'name': column.name,
            'display_name': column.display_name,
            'field_path': column.field_path,
            'is_formula': column.is_formula,
            'formula': column.formula,
            'aggregation': column.aggregation,
            'is_visible': column.is_visible
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@require_http_methods(["POST"])
def update_column(request):
    """Update an existing column"""
    try:
        column_id = request.POST.get('column_id')
        column = get_object_or_404(ReportColumn, id=column_id)
        
        # Update fields
        column.display_name = request.POST.get('display_name', column.display_name)
        if request.POST.get('formula') is not None:
            column.formula = request.POST.get('formula')
        if request.POST.get('aggregation') is not None:
            column.aggregation = request.POST.get('aggregation')
        if request.POST.get('is_visible') is not None:
            column.is_visible = request.POST.get('is_visible') == 'true'
        
        column.save()
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@require_http_methods(["POST"])
def delete_column(request):
    """Delete a column"""
    try:
        column_id = request.POST.get('column_id')
        column = get_object_or_404(ReportColumn, id=column_id)
        column.delete()
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@require_POST
@csrf_exempt
def reorder_columns(request, report_id):
    """Reorder columns in a report"""
    try:
        report = Report.objects.get(id=report_id)
        columns = json.loads(request.POST.get('columns', '[]'))
        
        # Update the order of columns
        for index, column_id in enumerate(columns):
            ReportColumn.objects.filter(id=column_id, report=report).update(order=index)
        
        return JsonResponse({'success': True})
    except (Report.DoesNotExist, ValueError, json.JSONDecodeError) as e:
        return JsonResponse({'success': False, 'error': str(e)})

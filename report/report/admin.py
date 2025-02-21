from django.contrib import admin
from .models import Report, ReportColumn, ReportFilter, ReportGrouping, CalculatedField

@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('name', 'root_model', 'created_at', 'updated_at')
    search_fields = ('name', 'description')
    list_filter = ('root_model', 'created_at')

@admin.register(ReportColumn)
class ReportColumnAdmin(admin.ModelAdmin):
    list_display = ('report', 'name', 'display_name', 'field_path', 'order', 'is_visible', 'aggregation')
    list_filter = ('report', 'is_visible', 'aggregation')
    search_fields = ('name', 'display_name', 'field_path')
    ordering = ('report', 'order')

@admin.register(ReportFilter)
class ReportFilterAdmin(admin.ModelAdmin):
    list_display = ('report', 'field_path', 'operator')
    list_filter = ('report', 'operator')
    search_fields = ('field_path',)

@admin.register(ReportGrouping)
class ReportGroupingAdmin(admin.ModelAdmin):
    list_display = ('report', 'field_path', 'order')
    list_filter = ('report',)
    search_fields = ('field_path',)
    ordering = ('report', 'order')

@admin.register(CalculatedField)
class CalculatedFieldAdmin(admin.ModelAdmin):
    list_display = ('report', 'name', 'display_name', 'formula', 'order')
    list_filter = ('report',)
    search_fields = ('name', 'display_name', 'formula')
    ordering = ('report', 'order')

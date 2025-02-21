from django.urls import path
from . import views

app_name = 'report'

urlpatterns = [
    path('', views.ReportListView.as_view(), name='report_list'),
    path('create/', views.ReportCreateView.as_view(), name='report_create'),
    path('<int:pk>/update/', views.ReportUpdateView.as_view(), name='report_update'),
    path('<int:pk>/builder/', views.ReportBuilderView.as_view(), name='report_builder'),
    path('<int:report_id>/execute/', views.execute_report, name='execute_report'),
    
    # AJAX endpoints
    path('<int:report_id>/save-column/', views.save_report_column, name='save_report_column'),
    path('<int:report_id>/save-filter/', views.save_filter, name='save_filter'),
    path('<int:report_id>/delete-filter/', views.delete_filter, name='delete_filter'),
    path('<int:report_id>/reset-filters/', views.reset_filters, name='reset_filters'),
    path('<int:report_id>/get-field-values/', views.get_field_values, name='get_field_values'),
    path('get-model-fields/', views.get_model_fields, name='get_model_fields'),
    path('get-related-fields/', views.get_related_fields, name='get_related_fields'),
    
    # Column management endpoints
    path('<int:report_id>/add-column/', views.add_column, name='add_column'),
    path('get-column/', views.get_column, name='get_column'),
    path('update-column/', views.update_column, name='update_column'),
    path('delete-column/', views.delete_column, name='delete_column'),
    path('<int:report_id>/reorder-columns/', views.reorder_columns, name='reorder_columns'),
    
    # New grouping and aggregation endpoints
    path('<int:report_id>/save-grouping/', views.save_grouping, name='save_grouping'),
    path('<int:report_id>/delete-grouping/', views.delete_grouping, name='delete_grouping'),
    path('<int:report_id>/update-grouping-order/', views.update_grouping_order, name='update_grouping_order'),
    path('<int:report_id>/save-aggregation/', views.save_aggregation, name='save_aggregation'),
    path('<int:report_id>/delete-aggregation/', views.delete_aggregation, name='delete_aggregation'),
]
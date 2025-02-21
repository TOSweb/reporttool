from django import forms
from django.contrib.contenttypes.models import ContentType
from .models import Report, ReportColumn, ReportFilter, ReportGrouping, CalculatedField

class ReportForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = ['name', 'description', 'root_model']
        widgets = {
            'root_model': forms.Select(attrs={'class': 'form-control select2'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show models that are registered in the admin
        self.fields['root_model'].queryset = ContentType.objects.filter(
            app_label__in=['auth', 'report', 'testapp']  # Add your app labels here
        ).order_by('app_label', 'model')

class ReportColumnForm(forms.ModelForm):
    class Meta:
        model = ReportColumn
        fields = ['name', 'display_name', 'field_path', 'aggregation', 'is_visible', 'order']
        widgets = {
            'field_path': forms.Select(attrs={'class': 'form-control select2'}),
            'aggregation': forms.Select(attrs={'class': 'form-control'}),
        }

class ReportFilterForm(forms.ModelForm):
    class Meta:
        model = ReportFilter
        fields = ['field_path', 'operator', 'value']
        widgets = {
            'field_path': forms.Select(attrs={'class': 'form-control select2'}),
            'operator': forms.Select(attrs={'class': 'form-control'}),
            'value': forms.TextInput(attrs={'class': 'form-control'}),
        }

class ReportGroupingForm(forms.ModelForm):
    class Meta:
        model = ReportGrouping
        fields = ['field_path', 'order']
        widgets = {
            'field_path': forms.Select(attrs={'class': 'form-control select2'}),
        }

class CalculatedFieldForm(forms.ModelForm):
    class Meta:
        model = CalculatedField
        fields = ['name', 'display_name', 'formula']
        widgets = {
            'formula': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        } 
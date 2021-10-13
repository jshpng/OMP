"""
应用商店相关过滤器
"""
import django_filters
from django_filters.rest_framework import FilterSet

from db_models.models import (
    Labels, ApplicationHub, ProductHub
)


class LabelFilter(FilterSet):
    """ 标签过滤类 """
    label_type = django_filters.CharFilter(
        help_text="标签类型: 0-组件 1-应用", field_name="label_type", lookup_expr="exact")

    class Meta:
        model = Labels
        fields = ("label_type",)


class ComponentFilter(FilterSet):
    """ 基础组件过滤类 """
    app_name = django_filters.CharFilter(
        help_text="基础组件名称，模糊匹配", field_name="app_name", lookup_expr="icontains")
    type = django_filters.CharFilter(
        help_text="类型名称", field_name="app_labels__label_name", lookup_expr="exact")

    class Meta:
        model = ApplicationHub
        fields = ("app_name", "type")


class ServiceFilter(FilterSet):
    """ 应用服务过滤器类 """
    pro_name = django_filters.CharFilter(
        help_text="应用服务名称，模糊匹配", field_name="pro_name", lookup_expr="icontains")
    type = django_filters.CharFilter(
        help_text="类型名称", field_name="pro_labels__label_name", lookup_expr="exact")

    class Meta:
        model = ProductHub
        fields = ("pro_name", "type")
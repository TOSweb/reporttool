from django.contrib import admin
from .models import Customer, Product, Order, OrderItem, ProductReview, Promotion

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'customer_type', 'date_joined', 'lifetime_value')
    search_fields = ('name', 'email', 'phone')
    list_filter = ('customer_type', 'date_joined')

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'GST', 'stock_level', 'launch_date')
    search_fields = ('name', 'description')
    list_filter = ('category', 'launch_date')
    readonly_fields = ('profit_margin',)

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('customer', 'order_date', 'status', 'total', 'total_with_shipping')
    list_filter = ('order_date', 'status', 'customer')
    search_fields = ('customer__name', 'tracking_number')
    inlines = [OrderItemInline]
    readonly_fields = ('total_with_shipping', 'days_to_delivery')

@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ('product', 'customer', 'rating', 'review_date', 'verified_purchase')
    list_filter = ('rating', 'review_date', 'verified_purchase')
    search_fields = ('product__name', 'customer__name', 'review_text')

@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_date', 'end_date', 'discount_percentage', 'is_active')
    list_filter = ('start_date', 'end_date')
    search_fields = ('name',)
    filter_horizontal = ('products',)
    readonly_fields = ('is_active',)

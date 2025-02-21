from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator

# Create your models here.

class Customer(models.Model):
    CUSTOMER_TYPES = [
        ('retail', 'Retail'),
        ('wholesale', 'Wholesale'),
        ('corporate', 'Corporate'),
    ]
    
    name = models.CharField(max_length=100)
    email = models.EmailField(max_length=100)
    phone = models.CharField(max_length=100)
    address = models.TextField()
    customer_type = models.CharField(max_length=20, choices=CUSTOMER_TYPES, default='retail')
    date_joined = models.DateTimeField(default=timezone.now)
    credit_score = models.IntegerField(
        validators=[MinValueValidator(300), MaxValueValidator(850)],
        null=True,
        blank=True
    )
    lifetime_value = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        default=0.00
    )

    def __str__(self):
        return self.name

class Product(models.Model):
    CATEGORIES = [
        ('electronics', 'Electronics'),
        ('clothing', 'Clothing'),
        ('food', 'Food'),
        ('books', 'Books'),
    ]
    
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    GST = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORIES)
    stock_level = models.IntegerField(default=0)
    reorder_point = models.IntegerField(default=10)
    weight = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Weight in kg",
        null=True,
        blank=True
    )
    manufacturing_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Cost to manufacture/acquire"
    )
    launch_date = models.DateField(default=timezone.now)

    def profit_margin(self):
        return (self.price - self.manufacturing_cost) / self.price * 100

    def __str__(self):
        return self.name

class OrderItem(models.Model):
    order = models.ForeignKey('Order', on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    @property
    def subtotal(self):
        return self.quantity * self.unit_price * (1 - self.discount_percentage / 100)

    def __str__(self):
        return f"{self.quantity}x {self.product.name} in Order #{self.order.id}"

class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]
    
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    order_date = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    shipping_address = models.TextField()
    tracking_number = models.CharField(max_length=100, null=True, blank=True)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_cost = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    payment_method = models.CharField(max_length=50, default='credit_card')
    notes = models.TextField(blank=True)
    estimated_delivery = models.DateTimeField(null=True, blank=True)

    @property
    def days_to_delivery(self):
        if self.estimated_delivery and self.order_date:
            return (self.estimated_delivery - self.order_date).days
        return None

    @property
    def total_with_shipping(self):
        return self.total + self.shipping_cost

    @property
    def products(self):
        return Product.objects.filter(orderitem__order=self)

    def __str__(self):
        return f"{self.customer.name} - {self.order_date.date()}"

class ProductReview(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    review_text = models.TextField()
    review_date = models.DateTimeField(default=timezone.now)
    helpful_votes = models.IntegerField(default=0)
    verified_purchase = models.BooleanField(default=False)

    def __str__(self):
        return f"Review for {self.product.name} by {self.customer.name}"

class Promotion(models.Model):
    name = models.CharField(max_length=100)
    products = models.ManyToManyField(Product, related_name='promotions')
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    minimum_order_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00
    )
    usage_count = models.IntegerField(default=0)
    max_usage = models.IntegerField(null=True, blank=True)

    @property
    def is_active(self):
        now = timezone.now()
        return self.start_date <= now <= self.end_date and (
            self.max_usage is None or self.usage_count < self.max_usage
        )

    def __str__(self):
        return self.name  

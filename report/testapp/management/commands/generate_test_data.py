from django.core.management.base import BaseCommand
from django.utils import timezone
from testapp.models import Customer, Product, Order
from faker import Faker
import random
from decimal import Decimal
from datetime import datetime, timedelta

fake = Faker()

class Command(BaseCommand):
    help = 'Generates test data for the testapp models'

    def add_arguments(self, parser):
        parser.add_argument('--customers', type=int, default=50, help='Number of customers to create')
        parser.add_argument('--products', type=int, default=100, help='Number of products to create')
        parser.add_argument('--orders', type=int, default=200, help='Number of orders to create')

    def handle(self, *args, **options):
        self.stdout.write('Generating test data...')
        
        # Create customers
        customers = []
        self.stdout.write('Creating customers...')
        for _ in range(options['customers']):
            customer = Customer.objects.create(
                name=fake.name(),
                email=fake.email(),
                phone=fake.phone_number(),
                address=fake.address()
            )
            customers.append(customer)
        
        # Create products
        products = []
        self.stdout.write('Creating products...')
        categories = ['Electronics', 'Books', 'Clothing', 'Home & Garden', 'Sports', 'Toys']
        adjectives = ['Premium', 'Basic', 'Professional', 'Ultimate', 'Essential', 'Deluxe']
        
        for _ in range(options['products']):
            category = random.choice(categories)
            adjective = random.choice(adjectives)
            base_name = fake.word().title()
            name = f"{adjective} {category} {base_name}"
            
            price = Decimal(random.uniform(10.0, 1000.0)).quantize(Decimal('0.01'))
            gst = price * Decimal('0.18')  # 18% GST
            
            product = Product.objects.create(
                name=name,
                price=price,
                GST=gst,
                description=fake.paragraph()
            )
            products.append(product)
        
        # Create orders
        self.stdout.write('Creating orders...')
        start_date = datetime.now() - timedelta(days=365)  # Orders from last year
        
        for _ in range(options['orders']):
            customer = random.choice(customers)
            order_products = random.sample(products, random.randint(1, 5))
            order_date = fake.date_between(start_date=start_date)
            
            # Calculate total including GST
            total = sum((p.price + p.GST) for p in order_products)
            
            order = Order.objects.create(
                customer=customer,
                order_date=order_date,
                total=total
            )
            order.products.set(order_products)
        
        self.stdout.write(self.style.SUCCESS(f'''
Successfully created:
- {options['customers']} customers
- {options['products']} products
- {options['orders']} orders
        ''')) 
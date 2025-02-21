from django.core.management.base import BaseCommand
from django.utils import timezone
from testapp.models import Customer, Product, Order, OrderItem, ProductReview, Promotion
from faker import Faker
import random
from decimal import Decimal
from datetime import timedelta

fake = Faker()

class Command(BaseCommand):
    help = 'Generates fake data for testing'

    def add_arguments(self, parser):
        parser.add_argument('--customers', type=int, default=50, help='Number of customers')
        parser.add_argument('--products', type=int, default=100, help='Number of products')
        parser.add_argument('--orders', type=int, default=200, help='Number of orders')
        parser.add_argument('--reviews', type=int, default=300, help='Number of reviews')
        parser.add_argument('--promotions', type=int, default=10, help='Number of promotions')

    def handle(self, *args, **options):
        self.stdout.write('Starting fake data generation...')
        
        # Create Customers
        self.stdout.write('Creating customers...')
        customers = []
        for _ in range(options['customers']):
            customer = Customer.objects.create(
                name=fake.name(),
                email=fake.email(),
                phone=fake.phone_number(),
                address=fake.address(),
                customer_type=random.choice(['retail', 'wholesale', 'corporate']),
                date_joined=fake.date_time_between(start_date='-2y'),
                credit_score=random.randint(300, 850),
                lifetime_value=Decimal(random.uniform(0, 10000)).quantize(Decimal('0.01'))
            )
            customers.append(customer)

        # Create Products
        self.stdout.write('Creating products...')
        products = []
        categories = ['electronics', 'clothing', 'food', 'books']
        for _ in range(options['products']):
            price = Decimal(random.uniform(10, 1000)).quantize(Decimal('0.01'))
            manufacturing_cost = price * Decimal(random.uniform(0.3, 0.7)).quantize(Decimal('0.01'))
            product = Product.objects.create(
                name=fake.catch_phrase(),
                price=price,
                GST=Decimal(random.uniform(0.05, 0.15)).quantize(Decimal('0.01')),
                description=fake.text(),
                category=random.choice(categories),
                stock_level=random.randint(0, 1000),
                reorder_point=random.randint(10, 100),
                weight=Decimal(random.uniform(0.1, 50)).quantize(Decimal('0.01')),
                manufacturing_cost=manufacturing_cost,
                launch_date=fake.date_between(start_date='-1y')
            )
            products.append(product)

        # Create Orders and OrderItems
        self.stdout.write('Creating orders and order items...')
        for _ in range(options['orders']):
            order_date = fake.date_time_between(start_date='-1y')
            estimated_delivery = order_date + timedelta(days=random.randint(1, 14))
            order = Order.objects.create(
                customer=random.choice(customers),
                order_date=order_date,
                status=random.choice(['pending', 'processing', 'shipped', 'delivered', 'cancelled']),
                shipping_address=fake.address(),
                tracking_number=fake.uuid4() if random.random() > 0.3 else None,
                shipping_cost=Decimal(random.uniform(5, 50)).quantize(Decimal('0.01')),
                payment_method=random.choice(['credit_card', 'debit_card', 'paypal', 'bank_transfer']),
                notes=fake.text() if random.random() > 0.7 else '',
                estimated_delivery=estimated_delivery,
                total=Decimal('0')  # Will be updated after adding items
            )
            
            # Add 1-5 items to each order
            total = Decimal('0')
            for _ in range(random.randint(1, 5)):
                product = random.choice(products)
                quantity = random.randint(1, 5)
                discount = Decimal(random.uniform(0, 30)).quantize(Decimal('0.01'))
                item = OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=quantity,
                    unit_price=product.price,
                    discount_percentage=discount
                )
                total += item.subtotal
            
            order.total = total
            order.save()

        # Create Product Reviews
        self.stdout.write('Creating product reviews...')
        for _ in range(options['reviews']):
            product = random.choice(products)
            customer = random.choice(customers)
            verified = random.random() > 0.3
            ProductReview.objects.create(
                product=product,
                customer=customer,
                rating=random.randint(1, 5),
                review_text=fake.paragraph(),
                review_date=fake.date_time_between(start_date='-1y'),
                helpful_votes=random.randint(0, 100) if random.random() > 0.5 else 0,
                verified_purchase=verified
            )

        # Create Promotions
        self.stdout.write('Creating promotions...')
        for _ in range(options['promotions']):
            start_date = fake.date_time_between(start_date='-6m', end_date='+6m')
            end_date = start_date + timedelta(days=random.randint(7, 90))
            promo = Promotion.objects.create(
                name=fake.catch_phrase(),
                start_date=start_date,
                end_date=end_date,
                discount_percentage=Decimal(random.uniform(5, 50)).quantize(Decimal('0.01')),
                minimum_order_value=Decimal(random.uniform(0, 500)).quantize(Decimal('0.01')),
                usage_count=random.randint(0, 1000),
                max_usage=random.randint(1000, 5000) if random.random() > 0.3 else None
            )
            # Add 1-10 products to each promotion
            promo_products = random.sample(products, random.randint(1, 10))
            promo.products.set(promo_products)

        self.stdout.write(self.style.SUCCESS('Successfully generated fake data'))
        self.stdout.write(f'''
Summary:
- {options['customers']} customers created
- {options['products']} products created
- {options['orders']} orders created
- {options['reviews']} reviews created
- {options['promotions']} promotions created
        ''') 
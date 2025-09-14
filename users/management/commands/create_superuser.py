from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()

class Command(BaseCommand):
    help = 'Creates a superuser with predefined credentials'

    def handle(self, *args, **options):
        if not User.objects.filter(email='admin@saungseo.com').exists():
            User.objects.create_superuser(
                email='admin@saungseo.com',
                username='daffyshaci',
                password='daffy160508',
                first_name='Daffy',
                last_name='Shaci',
                is_staff=True,
                is_superuser=True,
                is_active=True
            )
            self.stdout.write(self.style.SUCCESS('Superuser created successfully'))
        else:
            self.stdout.write(self.style.WARNING('Superuser already exists'))
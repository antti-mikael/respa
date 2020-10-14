from django.core.management.base import BaseCommand, CommandError
from resources.models import Resource
from datetime import timedelta


class Command(BaseCommand):
    help = 'Updates max_period of Resources whenever it is null'

    def handle(self, *args, **options):

        resources = Resource.objects.filter(max_period=None)

        for resource in resources:
            resource.max_period = timedelta(hours=12)
            resource.save()
            self.stdout.write(self.style.SUCCESS('Successfully updated resource "%s"' % resource.id))

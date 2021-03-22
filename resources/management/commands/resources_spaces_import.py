import csv
import enum
import os

from django.core.management import BaseCommand, CommandError
from django.utils import translation

from resources.models import Resource, Unit, ResourceType, Purpose, ResourceGroup
from respa_exchange.models import ExchangeConfiguration, ExchangeResource


class Columns(enum.Enum):
    is_public = 0
    unit = 1
    recourse_type = 2
    purpose = 3
    name = 4
    description = 5
    authentication_type = 6
    people_capacity = 7
    area = 8
    min_period = 9
    max_period = 10
    is_reservable = 11
    reservation_info = 12
    resource_group = 13
    exchange = 14


class Command(BaseCommand):
    help = "Import resources via csv file. This is for importing resources for spaces"

    def add_arguments(self, parser):
        parser.add_argument(
            "file_path", help="Path to the csv file",
        )

    @staticmethod
    def get_authentication_type(authentication_type_fi):
        if authentication_type_fi.lower() == "ei mitään":
            return "none"
        with translation.override("fi"):
            authentication_type = dict(Resource.AUTHENTICATION_TYPES)
            name = [k for k in authentication_type.keys() if
                    authentication_type[k] == authentication_type_fi]
            return name[0]

    def handle(self, *args, **options):
        file_path = options["file_path"]
        if not os.path.exists(file_path):
            raise CommandError("File {0} does not exist".format(file_path))

        with open(file_path) as f:
            csv_reader = csv.reader(f, delimiter=";")
            print("Processing...")
            for idx, row in enumerate(csv_reader):
                if idx == 0 or not row[Columns.name.value]:
                    continue
                resource = Resource()
                resource.public = True if row[Columns.is_public.value] else False
                unit, created = Unit.objects.update_or_create(
                    street_address__iexact=row[Columns.unit.value],
                    defaults={'name': row[Columns.unit.value].split(",")[0],
                              'street_address': row[Columns.unit.value]})
                resource.unit = unit
                resource_type, created = ResourceType.objects.update_or_create(
                    name__iexact=row[Columns.recourse_type.value],
                    main_type="space",
                    defaults={'name': row[Columns.recourse_type.value]}
                )
                resource.type = resource_type
                resource.name = row[Columns.name.value]
                resource.description = row[Columns.description.value]
                resource.authentication = self.get_authentication_type(row[Columns.authentication_type.value])
                resource.people_capacity = None if row[Columns.people_capacity.value] == "" else row[
                    Columns.people_capacity.value]
                resource.area = None if row[Columns.area.value] == "" else row[Columns.area.value]
                if not row[Columns.min_period.value] == "":
                    resource.min_period = row[Columns.min_period.value]
                if not row[Columns.max_period.value] == "":
                    resource.max_period = row[Columns.max_period.value]
                resource.reservable = True if row[Columns.is_reservable.value] else False
                resource.reservation_info = row[Columns.reservation_info.value]
                resource.save()
                purpose, created = Purpose.objects.update_or_create(
                    name__iexact=row[Columns.purpose.value],
                    defaults={'name': row[Columns.purpose.value]})
                resource.purposes.add(purpose)

                resource_group, created = ResourceGroup.objects.update_or_create(
                    name__iexact=row[Columns.resource_group.value],
                    defaults={'name': row[Columns.resource_group.value]})

                resource_group.resources.add(resource)

                exchange_configuration_count = ExchangeConfiguration.objects.count()
                if exchange_configuration_count is not 0:
                    if row[Columns.exchange.value] is not '':
                        exchange_configuration = ExchangeConfiguration.objects.first()
                        ExchangeResource.objects.update_or_create(
                            principal_email__iexact=row[Columns.exchange.value],
                            defaults={'principal_email': row[Columns.exchange.value], 'resource_id': resource.pk,
                                      'exchange_id': exchange_configuration.pk})
                else:
                    print('Can not find exchange_configuration. Skipping add exchange resource')
            print("Done!")

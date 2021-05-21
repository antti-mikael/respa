import logging

from django.db import migrations
from django.db.models import Q

logger = logging.getLogger(__name__)

GROUP_ID_HTP = 9
GROUP_ID_KANSLIA = 2
METADATASET_NAME = "Helsingin työllisyyspalvelut"


def get_groups(ResourceGroup):
    return (
        ResourceGroup.objects.get(id=GROUP_ID_HTP, name="Helsingin työllisyyspalvelut"),
        ResourceGroup.objects.get(id=GROUP_ID_KANSLIA, name="Kanslia"),
    )


def get_metadataset(apps, create):
    ReservationMetadataSet = apps.get_model("resources", "ReservationMetadataSet")

    if not create:
        return ReservationMetadataSet.objects.filter(name=METADATASET_NAME).first()

    metadataset, created = ReservationMetadataSet.objects.get_or_create(
        name=METADATASET_NAME
    )
    if created:
        # Fields copied from _Kanslia_ metadata set.
        required_fields = (
            "event_subject",
            "reserver_name",
        )
        supported_fields = (
            "event_description",
            "event_subject",
            "host_name",
            "number_of_participants",
            "participants",
            "reserver_email_address",
            "reserver_name",
            "reserver_phone_number",
        )

        Field = apps.get_model("resources", "ReservationMetadataField")
        metadataset.required_fields.add(
            *Field.objects.filter(field_name__in=required_fields)
        )
        metadataset.supported_fields.add(
            *Field.objects.filter(field_name__in=supported_fields)
        )

    return metadataset


def get_models(apps):
    return (
        apps.get_model("resources", "Resource"),
        apps.get_model("resources", "ResourceGroup"),
    )


def backward(apps, schema_editor):
    Resource, ResourceGroup = get_models(apps)
    try:
        # Make sure that resource groups exist.
        htp, kanslia = get_groups(ResourceGroup)
    except ResourceGroup.DoesNotExist:
        logger.warn("Unable to find resource group for Kanslia or HTP.")
        return

    metadataset = get_metadataset(apps, create=False)
    if not metadataset:
        # Nothing to do.
        return

    Resource.objects.filter(groups__id__in=[htp.id]).filter(
        reservation_metadata_set_id=metadataset.id
    ).update(reservation_metadata_set_id=None)


def forward(apps, schema_editor):
    Resource, ResourceGroup = get_models(apps)
    try:
        # Make sure that resource groups exist.
        htp, kanslia = get_groups(ResourceGroup)
    except ResourceGroup.DoesNotExist:
        logger.warn("Unable to find resource group for Kanslia or HTP.")
        return

    metadataset = get_metadataset(apps, create=True)
    Resource.objects.filter(groups__id__in=[htp.id]).filter(
        reservation_metadata_set__isnull=True
    ).update(reservation_metadata_set_id=metadataset.id)


class Migration(migrations.Migration):
    """
    Create a new reservation metadata set for Helsingin työllisyyspalvelut.
    """

    dependencies = [
        ("resources", "0068_data_htp_add_unit_prefix"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]

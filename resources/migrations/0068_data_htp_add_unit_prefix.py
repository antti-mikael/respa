import logging

from django.db import migrations
from django.db.models import Q

logger = logging.getLogger(__name__)

GROUP_ID_HTP = 9
GROUP_ID_KANSLIA = 2
UNIT_NAME_PREFIX = "Työllisyyspalvelut / "


def get_groups(ResourceGroup):
    return (
        ResourceGroup.objects.get(id=GROUP_ID_HTP, name="Helsingin työllisyyspalvelut"),
        ResourceGroup.objects.get(id=GROUP_ID_KANSLIA, name="Kanslia"),
    )


def get_models(apps):
    return (
        apps.get_model("resources", "Resource"),
        apps.get_model("resources", "ResourceGroup"),
        apps.get_model("resources", "Unit"),
    )


def backward(apps, schema_editor):
    Resource, ResourceGroup, Unit = get_models(apps)
    try:
        # Make sure that resource groups exist.
        get_groups(ResourceGroup)
    except ResourceGroup.DoesNotExist:
        logger.warn("Unable to find resource group for Kanslia or HTP.")
        return

    units_qs = (
        Unit.objects
        .filter(
            Q(name__startswith=UNIT_NAME_PREFIX)
            | Q(name_fi__startswith=UNIT_NAME_PREFIX)
        )
    )

    for unit in units_qs:
        for field in ("name", "name_fi"):
            value = getattr(unit, field)
            if value.startswith(UNIT_NAME_PREFIX):
                setattr(unit, field, value[len(UNIT_NAME_PREFIX) :])
        unit.save()


def forward(apps, schema_editor):
    Resource, ResourceGroup, Unit = get_models(apps)
    try:
        # Make sure that resource groups exist.
        htp, kanslia = get_groups(ResourceGroup)
    except ResourceGroup.DoesNotExist:
        logger.warn("Unable to find resource group for Kanslia or HTP.")
        return

    resource_id_qs = (
        Resource.objects
        .filter(groups__id__in=[htp.id])
        .filter(groups__id__in=[kanslia.id])
        .values_list("unit__id", flat=True)
    )
    units_qs = (
        Unit.objects
        .filter(id__in=resource_id_qs)
    )

    for unit in units_qs:
        for field in ("name", "name_fi"):
            value = getattr(unit, field)
            if value and not value.startswith(UNIT_NAME_PREFIX):
                setattr(unit, field, UNIT_NAME_PREFIX + value)
        unit.save()


class Migration(migrations.Migration):
    """
    For units that have resources belonging to both _Kanslia_ group and
    _Helsingin työllisyyspalvelut_ groups, prefix the name of the unit
    with `UNIT_NAME_PREFIX`.
    """

    dependencies = [
        ("resources", "0067_data_htp_group_changes"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]

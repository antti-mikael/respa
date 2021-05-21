import logging

from django.db import migrations
from django.db.models import Q

logger = logging.getLogger(__name__)

EXTRA_DESCRIPTION = "Näitä tiloja voidaan varata vain Työllisyyspalveluiden käyttöön."
GROUP_ID_HTP = 9
GROUP_ID_KANSLIA = 2


def get_groups(ResourceGroup):
    return (
        ResourceGroup.objects.get(id=GROUP_ID_HTP, name="Helsingin työllisyyspalvelut"),
        ResourceGroup.objects.get(id=GROUP_ID_KANSLIA, name="Kanslia"),
    )


def get_models(apps):
    return (
        apps.get_model("resources", "Resource"),
        apps.get_model("resources", "ResourceGroup"),
    )


def backward(apps, schema_editor):
    Resource, ResourceGroup = get_models(apps)
    try:
        # Make sure that resource groups exist.
        _, kanslia = get_groups(ResourceGroup)
    except ResourceGroup.DoesNotExist:
        logger.warn("Unable to find resource group for Kanslia or HTP.")
        return

    qs = (
        Resource.objects
        .filter(
            Q(description__startswith=EXTRA_DESCRIPTION)
            | Q(description_fi__startswith=EXTRA_DESCRIPTION)
        )
        .filter(groups__id__in=[kanslia.id])
    )

    for resource in qs:
        for field in ("description", "description_fi"):
            value = getattr(resource, field)
            if value.startswith(EXTRA_DESCRIPTION):
                setattr(resource, field, value[len(EXTRA_DESCRIPTION)].lstrip())

        resource.groups.remove(kanslia)
        resource.save()


def forward(apps, schema_editor):
    Resource, ResourceGroup = get_models(apps)
    try:
        # Make sure that resource groups exist.
        htp, kanslia = get_groups(ResourceGroup)
    except ResourceGroup.DoesNotExist:
        logger.warn("Unable to find resource group for Kanslia or HTP.")
        return

    qs = (
        Resource.objects
        .filter(groups__id__in=[htp.id])
        .exclude(groups__id__in=[kanslia.id])
    )

    for resource in qs:
        for field in ("description", "description_fi"):
            value = getattr(resource, field)
            if not value.startswith(EXTRA_DESCRIPTION):
                setattr(
                    resource,
                    field,
                    EXTRA_DESCRIPTION + (" " if value else "") + value,
                )

        resource.groups.add(kanslia)
        resource.save()


class Migration(migrations.Migration):
    """
    Add resources in _Helsingin työllisyyspalvelut_ group to _Kanslia_ group.

    In addition to that, prepend the description with a notice (`EXTRA_DESCRIPTION`).
    """

    dependencies = [
        ("resources", "0066_support_for_django_2"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]

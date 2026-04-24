import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "redcap_cdc.settings")

app = Celery("redcap_cdc")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()
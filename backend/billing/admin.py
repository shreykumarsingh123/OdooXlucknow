from django.contrib import admin

from . import models

for model in [models.Subscription, models.Invoice, models.Payment]:
    admin.site.register(model)

from django.contrib import admin

from . import models

for model in [models.Tax, models.PaymentTerm, models.Product, models.Plan, models.Discount, models.QuotationTemplate]:
    admin.site.register(model)

from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("taxes", views.TaxViewSet)
router.register("payment-terms", views.PaymentTermViewSet)
router.register("products", views.ProductViewSet)
router.register("plans", views.PlanViewSet)
router.register("discounts", views.DiscountViewSet)
router.register("templates", views.QuotationTemplateViewSet)
urlpatterns = router.urls

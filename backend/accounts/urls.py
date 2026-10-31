from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("customers", views.CustomerViewSet, basename="customer")
router.register("staff", views.StaffViewSet, basename="staff")
urlpatterns = router.urls

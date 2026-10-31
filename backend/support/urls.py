from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("tickets", views.TicketViewSet, basename="ticket")
router.register("team-chat", views.TeamMessageViewSet, basename="team-chat")
router.register("admin-chat", views.AdminMessageViewSet, basename="admin-chat")
urlpatterns = router.urls

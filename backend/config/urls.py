from django.conf import settings
from django.contrib import admin
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import include, path

urlpatterns = [
    path("", lambda request: HttpResponseRedirect(settings.FRONTEND_URL)),
    path("admin/", admin.site.urls),
    path("api/health/", lambda request: JsonResponse({"status": "ok"})),
    path("api/auth/", include("accounts.auth_urls")),
    path("api/", include("accounts.urls")),
    path("api/", include("catalog.urls")),
    path("api/", include("billing.urls")),
    path("api/", include("support.urls")),
]

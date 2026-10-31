from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_admin


class IsTeam(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_team


class IsBackOffice(BasePermission):
    """Finance and billing work. Not for the customer care and sales departments."""

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_back_office


class IsPlatform(BasePermission):
    """The administrator and Brightloop's own staff, who see across every business."""

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_team and request.user.is_platform


class AdminWriteTeamRead(BasePermission):
    """Admin manages the catalog. Staff can read it. Customers cannot see it."""

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        return user.is_team if request.method in SAFE_METHODS else user.is_admin

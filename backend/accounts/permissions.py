from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_admin


class IsTeam(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_team


class AdminWriteTeamRead(BasePermission):
    """Admin manages the catalog. Staff can read it. Customers cannot see it."""

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        return user.is_team if request.method in SAFE_METHODS else user.is_admin

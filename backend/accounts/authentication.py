from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication


class BusinessJWTAuthentication(JWTAuthentication):
    """A suspended business locks out everyone in it, and turning it back on restores them unchanged."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if user.business_id and not user.business.is_active:
            raise AuthenticationFailed("This business has been suspended. Please contact Brightloop.")
        return user

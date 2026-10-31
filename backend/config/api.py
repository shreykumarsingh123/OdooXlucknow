from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import exception_handler as drf_handler


class Pagination(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 200


class Conflict(APIException):
    """A valid request that the record's current state does not allow."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"
    default_detail = "This action is not allowed in the current state."


def exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(exc.message_dict if hasattr(exc, "error_dict") else exc.messages)
    if isinstance(exc, ProtectedError):
        exc = Conflict("This record is in use and cannot be deleted. Deactivate it instead.")
    response = drf_handler(exc, context)
    if response is None:
        return None
    data = response.data
    if isinstance(data, dict) and "detail" in data:
        response.data = {"message": str(data["detail"]), "fields": {}}
    else:
        fields = data if isinstance(data, dict) else {"non_field_errors": data}
        first = next(iter(fields.values()), "Invalid input.")
        first = first[0] if isinstance(first, list) and first else first
        message = first if isinstance(first, str) else "Please check the highlighted fields."
        response.data = {"message": str(message), "fields": fields}
    return response

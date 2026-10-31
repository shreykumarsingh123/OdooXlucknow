"""The email address says who someone is. Parsing is one dictionary lookup, so it stays fast with any number of businesses."""
import re

from .models import Business, User

ROOT_EMAIL_DOMAIN = "admin.com"
NAME = r"[a-z][a-z0-9]*"
CODE_LENGTH = Business.CODE_LENGTH
WORK_DOMAINS = {"sale.com", "support.com", "adminsale.com", ROOT_EMAIL_DOMAIN}


def classify(email):
    """Return kind, department and business code for an address. Kind is None when the format is not allowed."""
    local, _, domain = str(email).strip().lower().partition("@")
    result = {"kind": None, "department": "", "code": None}
    if domain == "gmail.com" and re.fullmatch(r"[a-z0-9][a-z0-9._+-]*", local):
        result["kind"] = "user"
    elif domain == ROOT_EMAIL_DOMAIN and re.fullmatch(NAME, local):
        result["kind"] = "root"
    elif domain == "adminsale.com" and re.fullmatch(NAME, local):
        result.update(kind="platform_staff", department=User.Department.SALES)
    elif domain == "support.com" and re.fullmatch(NAME, local):
        result.update(kind="platform_staff", department=User.Department.SUPPORT)
    elif domain == "support.com" and re.fullmatch(rf"{NAME}\.[a-z0-9]{{{CODE_LENGTH}}}", local):
        result.update(kind="business_staff", department=User.Department.SUPPORT, code=local.rpartition(".")[2])
    elif domain == "sale.com" and len(local) > CODE_LENGTH and re.fullmatch(NAME, local[:-CODE_LENGTH]) and re.fullmatch(r"[a-z0-9]+", local[-CODE_LENGTH:]):
        result.update(kind="business_staff", department=User.Department.SALES, code=local[-CODE_LENGTH:])
    return result


def staff_email(first_name, department, business):
    name = re.sub(r"[^a-z0-9]", "", str(first_name).lower()).lstrip("0123456789")
    if not name:
        return None
    if business.is_platform:
        return f"{name}@adminsale.com" if department == User.Department.SALES else f"{name}@support.com"
    if department == User.Department.SALES:
        return f"{name}{business.code}@sale.com"
    return f"{name}.{business.code}@support.com"


def customers_of(business_id, is_platform=False):
    """Brightloop's customers are the owners of other businesses. A business's customers are its subscribers."""
    if is_platform:
        return User.objects.filter(role=User.Role.ADMIN, business__is_platform=False)
    return User.objects.filter(role=User.Role.CUSTOMER, business_id=business_id)

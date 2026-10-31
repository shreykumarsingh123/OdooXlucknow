import re

from django.core.exceptions import ValidationError

MIN_LENGTH = 9  # the brief says "more than eight characters"


class BrightloopPasswordValidator:
    def validate(self, password, user=None):
        problems = []
        if len(password) < MIN_LENGTH:
            problems.append("more than eight characters")
        if not re.search(r"[A-Z]", password):
            problems.append("an uppercase letter")
        if not re.search(r"[a-z]", password):
            problems.append("a lowercase letter")
        if not re.search(r"[^A-Za-z0-9\s]", password):
            problems.append("a special character")
        if problems:
            raise ValidationError("Password must have " + ", ".join(problems) + ".", code="weak_password")

    def get_help_text(self):
        return "Use more than eight characters, with an uppercase letter, a lowercase letter and a special character."

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django_filters import rest_framework as filters
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import IsTeam
from billing.models import Subscription

from .models import TeamMessage, Ticket, TicketMessage

logger = logging.getLogger(__name__)
MAX_BODY = 5000


class MessageSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.display_name", read_only=True)
    from_team = serializers.BooleanField(source="author.is_team", read_only=True)

    class Meta:
        model = TicketMessage
        fields = ["id", "author_name", "from_team", "body", "is_internal", "created_at"]


class TicketSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.display_name", read_only=True)
    assigned_name = serializers.SerializerMethodField()
    subscription_number = serializers.CharField(source="subscription.number", read_only=True, default=None)

    class Meta:
        model = Ticket
        fields = [
            "id", "number", "customer", "customer_name", "subscription", "subscription_number", "subject", "status", "priority",
            "assigned_to", "assigned_name", "escalated", "created_at", "updated_at",
        ]

    def get_assigned_name(self, ticket):
        return ticket.assigned_to.display_name if ticket.assigned_to else None


class TicketDetailSerializer(TicketSerializer):
    messages = serializers.SerializerMethodField()

    class Meta(TicketSerializer.Meta):
        fields = TicketSerializer.Meta.fields + ["messages"]

    def get_messages(self, ticket):
        rows = ticket.messages.select_related("author")
        if not self.context["request"].user.is_team:
            rows = rows.filter(is_internal=False)
        return MessageSerializer(rows, many=True).data


class TicketInSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=200)
    body = serializers.CharField(max_length=MAX_BODY)
    subscription = serializers.PrimaryKeyRelatedField(queryset=Subscription.objects.all(), required=False, allow_null=True)
    customer = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(role=User.Role.CUSTOMER), required=False)


class ManageSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Ticket.Status.choices, required=False)
    priority = serializers.ChoiceField(choices=Ticket.Priority.choices, required=False)
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role__in=[User.Role.ADMIN, User.Role.STAFF], is_active=True), required=False, allow_null=True
    )
    escalated = serializers.BooleanField(required=False)


class TicketFilter(filters.FilterSet):
    class Meta:
        model = Ticket
        fields = ["status", "priority", "escalated", "customer", "assigned_to"]


class TicketViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    filterset_class = TicketFilter
    search_fields = ["number", "subject", "customer__email", "customer__company", "customer__first_name"]
    ordering_fields = ["updated_at", "created_at"]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.user.is_sales:
            raise PermissionDenied("Tickets are handled by customer care.")

    def get_queryset(self):
        rows = Ticket.objects.select_related("customer", "assigned_to", "subscription")
        return rows if self.request.user.is_team else rows.filter(customer=self.request.user)

    def get_serializer_class(self):
        return TicketSerializer if self.action == "list" else TicketDetailSerializer

    def _render(self, ticket, code=200):
        return Response(TicketDetailSerializer(self.get_queryset().get(pk=ticket.pk), context=self.get_serializer_context()).data, status=code)

    def create(self, request, *args, **kwargs):
        form = TicketInSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        user = request.user
        customer = data.get("customer") if user.is_team else user
        if customer is None:
            raise serializers.ValidationError({"customer": ["Choose a customer."]})
        subscription = data.get("subscription")
        if subscription and subscription.customer_id != customer.pk:
            raise serializers.ValidationError({"subscription": ["This subscription belongs to another customer."]})
        with transaction.atomic():
            ticket = Ticket.objects.create(customer=customer, subscription=subscription, subject=data["subject"])
            ticket.number = f"TCK-{ticket.pk:06d}"
            ticket.save(update_fields=["number"])
            TicketMessage.objects.create(ticket=ticket, author=user, body=data["body"])
        return self._render(ticket, 201)

    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        ticket = self.get_object()
        body = str(request.data.get("body", "")).strip()
        if not body or len(body) > MAX_BODY:
            raise serializers.ValidationError({"body": [f"Write a message of up to {MAX_BODY} characters."]})
        user = request.user
        internal = user.is_team and request.data.get("internal") is True
        with transaction.atomic():
            TicketMessage.objects.create(ticket=ticket, author=user, body=body, is_internal=internal)
            if not internal:
                if user.is_team and ticket.status == Ticket.Status.OPEN:
                    ticket.status = Ticket.Status.IN_PROGRESS
                elif not user.is_team and ticket.status == Ticket.Status.RESOLVED:
                    ticket.status = Ticket.Status.OPEN  # the customer still needs help
            ticket.save(update_fields=["status", "updated_at"])
        if user.is_team and not internal:
            self._email_customer(ticket)
        return self._render(ticket)

    def _email_customer(self, ticket):
        try:
            send_mail(
                f"Reply on your request {ticket.number}",
                f"Hello {ticket.customer.display_name},\n\nWe have replied to \"{ticket.subject}\".\n\n"
                f"Read it here: {settings.FRONTEND_URL}/tickets/{ticket.pk}\n",
                settings.DEFAULT_FROM_EMAIL,
                [ticket.customer.email],
            )
        except Exception:
            logger.exception("Could not email the reply on %s", ticket.number)

    @action(detail=True, methods=["post"], permission_classes=[IsTeam])
    def manage(self, request, pk=None):
        ticket = self.get_object()
        form = ManageSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        for name, value in form.validated_data.items():
            setattr(ticket, name, value)
        ticket.save()
        return self._render(ticket)


class TeamMessageSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.display_name", read_only=True)
    author_role = serializers.SerializerMethodField()
    body = serializers.CharField(max_length=MAX_BODY)

    class Meta:
        model = TeamMessage
        fields = ["id", "author", "author_name", "author_role", "body", "created_at"]
        read_only_fields = ["author", "created_at"]

    def get_author_role(self, message):
        return message.author.get_department_display() or message.author.get_role_display()


class TeamMessageViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsTeam]
    serializer_class = TeamMessageSerializer
    queryset = TeamMessage.objects.select_related("author")

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

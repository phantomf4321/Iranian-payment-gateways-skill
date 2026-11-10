from django.contrib import admin

from .models import FulfillmentEvent, Payment, PaymentAttempt


class ReadOnlyPaymentAdmin(admin.ModelAdmin):
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(ReadOnlyPaymentAdmin):
    list_display = ("id", "provider", "amount", "currency", "status", "created_at")
    list_filter = ("status", "sandbox")
    search_fields = ("id", "order_reference", "reference_id")


@admin.register(PaymentAttempt)
class AttemptAdmin(ReadOnlyPaymentAdmin):
    list_display = ("id", "payment_id", "status", "verification_attempts", "initiated_at")
    list_filter = ("status",)


@admin.register(FulfillmentEvent)
class FulfillmentAdmin(ReadOnlyPaymentAdmin):
    list_display = ("id", "payment_id", "created_at", "delivered_at")

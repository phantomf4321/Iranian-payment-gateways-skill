from payments.exceptions import AccessDenied
from payments.payment_service import OrderSnapshot


def load_order(user, reference):
    if reference != f"order-{user.pk}":
        raise AccessDenied("Order access denied.")
    return OrderSnapshot(reference, 50_000)

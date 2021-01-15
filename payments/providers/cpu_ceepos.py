import hashlib
import hmac
import logging
from typing import Dict

import requests
from django.http import HttpResponse
from requests.exceptions import RequestException

from ..exceptions import (
    DuplicateOrderError,
    OrderStateTransitionError,
    PayloadValidationError,
    PaymentCreationFailedError,
    ServiceUnavailableError,
    UnknownReturnCodeError,
)
from ..models import Order, OrderLine, Product
from ..utils import price_as_sub_units
from .base import PaymentProvider

LOG = logging.getLogger(__name__)

# Keys the provider expects to find in the config
RESPA_PAYMENTS_CEEPOS_API_URL = "RESPA_PAYMENTS_CEEPOS_API_URL"
RESPA_PAYMENTS_CEEPOS_API_KEY = "RESPA_PAYMENTS_CEEPOS_API_KEY"
RESPA_PAYMENTS_CEEPOS_API_SECRET = "RESPA_PAYMENTS_CEEPOS_API_SECRET"

REQUEST_CHECKSUM_PARAMS = (
    "Id",
    "Status",
    "Reference",
    "PaymentMethod",
    "PaymentSum",
    "Timestamp",
    "PaymentDescription",
)
RESPONSE_CHECKSUM_PARAMS = (
    "Id",
    "Status",
    "Reference",
    "Action",
    "PaymentAddress",
    "PaymentExpires",
)


class CPUCeeposProvider(PaymentProvider):
    """CPU Ceepos specific integration utilities and configuration"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.url_payment_api = self.config.get(RESPA_PAYMENTS_CEEPOS_API_URL)

    @staticmethod
    def get_config_template() -> Dict[str, str]:
        """Keys and values that CeePos requires from environment"""
        return {
            RESPA_PAYMENTS_CEEPOS_API_URL: str,
            RESPA_PAYMENTS_CEEPOS_API_KEY: str,
            RESPA_PAYMENTS_CEEPOS_API_SECRET: str,
        }

    def initiate_payment(self, order: Order) -> str:
        """
        Creates a payment to the provider. The insertion order of the
        fields in the payload data is important here since the values
        are used for checksum calculations.

        Returns an URL to which the user is redirected
        to actually pay the order.
        """

        payload = {
            "ApiVersion": "3.0.0",
            "Source": self.config.get(RESPA_PAYMENTS_CEEPOS_API_KEY),
            "Id": str(order.order_number),
            "Mode": 3,
            "Action": "new payment",
        }
        secret = self.config.get(RESPA_PAYMENTS_CEEPOS_API_SECRET)

        self.payload_add_products(payload, order)
        self.payload_add_customer(payload, order)
        self.payload_add_return_and_notification_urls(payload)
        self.payload_add_checksum(payload, secret)

        try:
            r = requests.post(self.url_payment_api, json=payload, timeout=60)
            r.raise_for_status()
            return self.handle_initiate_payment_response(r.json())
        except RequestException as e:
            raise ServiceUnavailableError("Payment service is unreachable") from e

    def payload_add_products(self, payload, order):
        """Attaches product data to the payload

        Order lines that contain bought products are retrieved through order"""

        def get_product_taxcode(product: Product) -> str:
            tax = product.tax_percentage
            taxcode = {
                24_000_000: "24",
                14_000_000: "14",
                10_000_000: "10",
                0: "0",
            }.get(int(tax * 1_000_000))
            if not taxcode:
                raise ValueError(
                    f"Unsupported tax percentage {tax} for product {product}"
                )
            return taxcode

        reservation = order.reservation
        order_lines = OrderLine.objects.filter(order=order.id)
        items = []
        for order_line in order_lines:
            product = order_line.product
            items.append(
                {
                    "Code": product.sku,
                    "Amount": order_line.quantity,
                    "Price": price_as_sub_units(
                        product.get_price_for_reservation(reservation)
                    ),
                    "Description": product.name,
                    "Taxcode": get_product_taxcode(product),
                }
            )
            payload["Products"] = items

    def payload_add_customer(self, payload, order):
        """Attaches customer data to the payload"""
        reservation = order.reservation
        payload.update(
            {
                "Email": reservation.billing_email_address,
                "FirstName": reservation.billing_first_name,
                "LastName": reservation.billing_last_name,
            }
        )

    def payload_add_return_and_notification_urls(self, payload):
        """Attaches return and notification URLs to the payload"""
        payload.update(
            {
                "ReturnAddress": self.get_success_url(),
                "NotificationAddress": self.get_notify_url(),
            }
        )

    def payload_add_checksum(self, payload, secret):
        """
        Attaches the checksum to the payload.

        The checksum is calculated from a string that consists of the values of
        the parameters in the payload and the source system specific secret key.
        """
        checksum_calc_values = []
        for key, value in payload.items():
            if isinstance(value, list):
                for item in value:
                    checksum_calc_values.extend(item.values())
            else:
                checksum_calc_values.append(value)
        payload["Hash"] = self.calculate_checksum(checksum_calc_values, secret)

    def validate_ceepos_response(self, response):
        return self._validate_payload(response, RESPONSE_CHECKSUM_PARAMS)

    def validate_ceepos_request(self, request):
        data = request.POST if request.method == "POST" else request.GET
        return self._validate_payload(data, REQUEST_CHECKSUM_PARAMS)

    def _validate_payload(self, data, params):
        """
        Validates that the message payload received from CeePos has not been tampered with.

        If the checksum calculated is the same as the Hash parameter in the request/response,
        the message has been received intact and directly from CeePos.
        """
        checksum_received = data["Hash"]
        checksum_calc_values = [data[x] for x in params if x in data]
        secret = self.config.get(RESPA_PAYMENTS_CEEPOS_API_SECRET)
        correct_checksum = self.calculate_checksum(checksum_calc_values, secret)

        if not hmac.compare_digest(checksum_received, correct_checksum):
            LOG.warning('Incorrect checksum "{}".'.format(checksum_received))
            return False

        return True

    def calculate_checksum(self, param_values, secret) -> str:
        """
        Calculates and returns an SHA-256 checksum which is calculated from
        a string that consists of the values of the parameters in the message
        and the source system specific secret key. The & sign is used to
        separate the values in the string that is used for the calculation.
        """
        param_values.append(secret)
        string = "&".join(str(val) for val in param_values)
        return hashlib.sha256(string.encode("utf-8")).hexdigest()

    def handle_initiate_payment_response(self, response) -> str:
        """
        Handles CeePos' response to the initiate payment request.
        If the response is valid, returns the URL to which the user
        is redirected to pay the order.

        Relevant payment statuses:
            0 = Payment creation failed or cancelled
            2 = Processing of payment in progress
            97 = Double Id
            98 = System error
            99 = Faulty payment request
        """

        status_code = response["Status"]  # The status of the payment.
        if status_code == 2:
            # Return the URL where the user is redirected to complete the payment
            if not self.validate_ceepos_response(response):
                raise PayloadValidationError("Invalid response checksum")
            return response["PaymentAddress"]
        elif status_code == 0:
            raise PaymentCreationFailedError("Payment creation failed or was cancelled")
        elif status_code == 97:
            raise DuplicateOrderError("Order with the same ID already exists")
        elif status_code == 98:
            raise ServiceUnavailableError("Payment service is unavailable")
        elif status_code == 99:
            raise PayloadValidationError("Payment payload data validation failed")
        else:
            raise UnknownReturnCodeError(
                "Status code was not recognized: {}".format(status_code)
            )

    def handle_success_request(self):  # noqa: C901
        """
        Handles the CeePos payment complete request (GET) after user has completed
        the payment flow in normal fashion.

        If everything goes smoothly, should redirect the client back to the UI return URL.

        Relevant payment statuses:
            1 = Payment successful/action complete
            0 = Payment creation failed or cancelled
            98 = System error
        """
        request = self.request
        LOG.debug(
            "Handling CeePos user return request, params: {}.".format(request.GET)
        )

        if not self.validate_ceepos_request(request):
            return self.ui_redirect_failure()

        try:
            order = Order.objects.get(order_number=request.GET["Id"])
        except Order.DoesNotExist:
            LOG.warning("Order does not exist.")
            return self.ui_redirect_failure()

        status_code = request.GET["Status"]
        if status_code == "1":
            LOG.debug("Payment completed successfully.")
            try:
                order.set_state(
                    Order.CONFIRMED,
                    "Code 1 (payment succeeded) in CeePos success request.",
                )
                return self.ui_redirect_success(order)
            except OrderStateTransitionError as oste:
                LOG.warning(oste)
                order.create_log_entry(
                    "Code 1 (payment succeeded) in CeePos success request."
                )
                return self.ui_redirect_failure(order)
        elif status_code == "0":
            LOG.debug("Payment failed.")
            try:
                order.set_state(
                    Order.REJECTED,
                    "Code 0 (payment failed) in CeePos success request.",
                )
                return self.ui_redirect_failure(order)
            except OrderStateTransitionError as oste:
                LOG.warning(oste)
                order.create_log_entry(
                    "Code 0 (payment failed) in CeePos success request."
                )
                return self.ui_redirect_failure(order)
        elif status_code == "98":
            LOG.debug("CeePos system error.")
            order.create_log_entry("Code 98: CeePos system error")
            return self.ui_redirect_failure(order)
        else:
            LOG.warning('Incorrect status_code "{}".'.format(status_code))
            order.create_log_entry(
                'CeePos incorrect status code "{}".'.format(status_code)
            )
            return self.ui_redirect_failure(order)

    def handle_notify_request(self):  # noqa: C901
        """
        Handles incoming notify request (POST) from CeePos and set the order status accordingly.

        The notification is sent for the first time when CeePos is notified of a successful payment.
        In some cases, this can happen before the user has been redirected to the return address.

        CeePos expects a 200 OK response to acknowledge the notification was received.

        Relevant payment statuses:
            1 = Payment successful/action complete
            0 = Payment creation failed or cancelled
            98 = System error
        """
        request = self.request
        LOG.debug("Handling CeePos notify request, params: {}.".format(request.POST))

        if not self.validate_ceepos_request(request=request):
            return HttpResponse(status=200)

        try:
            order = Order.objects.get(order_number=request.POST.get("Id"))
        except Order.DoesNotExist:
            LOG.warning("Notify: Order does not exist.")
            return HttpResponse(status=200)

        status_code = request.POST.get("Status")
        if status_code == "1":
            LOG.debug("Notify: Payment completed successfully.")
            try:
                order.set_state(
                    Order.CONFIRMED,
                    "Code 1 (payment succeeded) in CeePos notify request.",
                )
            except OrderStateTransitionError as oste:
                LOG.warning(oste)
        elif status_code == "0":
            LOG.debug("Notify: Payment failed.")
            try:
                order.set_state(
                    Order.REJECTED, "Code 0 (payment failed) in CeePos notify request."
                )
            except OrderStateTransitionError as oste:
                LOG.warning(oste)
        elif status_code == "98":
            LOG.debug('Notify: CeePos system error "Code 98".')
        else:
            LOG.debug('Notify: Incorrect STATUS CODE "{}".'.format(status_code))

        return HttpResponse(status=200)

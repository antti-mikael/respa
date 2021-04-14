import hmac
import json
from unittest import mock

import pytest
from django.http import HttpResponse
from django.test.client import RequestFactory
from requests.exceptions import RequestException
from rest_framework.reverse import reverse

from payments.models import Order
from payments.providers.cpu_ceepos import (
    CPUCeeposProvider,
    DuplicateOrderError,
    PayloadValidationError,
    ServiceUnavailableError,
    UnknownReturnCodeError,
)

FAKE_CEEPOS_API_URL = "https://fake-ceepos-api-url/maksu.html"
UI_RETURN_URL = "https://front-end-url"
RESERVATION_LIST_URL = reverse("reservation-list")


@pytest.fixture(autouse=True)
def auto_use_django_db(db):
    pass


@pytest.fixture()
def provider_base_config():
    return {
        "RESPA_PAYMENTS_CEEPOS_API_URL": "https://real-ceepos-api-url/maksu.html",
        "RESPA_PAYMENTS_CEEPOS_API_KEY": "dummy-key",
        "RESPA_PAYMENTS_CEEPOS_API_SECRET": "123",
    }


@pytest.fixture()
def payment_provider(provider_base_config):
    """When it doesn't matter if request is contained within provider the fixture can still be used"""
    return CPUCeeposProvider(config=provider_base_config)


def create_ceepos_provider(provider_base_config, request, return_url=None):
    """Helper for creating a new instance of provider with request and optional return_url contained within"""
    return CPUCeeposProvider(
        config=provider_base_config, request=request, ui_return_url=return_url
    )


def mocked_response_create(*args, **kwargs):
    """Mock Ceepos initiate payment responses based on provider url"""

    class MockResponse:
        def __init__(self, data, status_code=200):
            self.json_data = data
            self.status_code = status_code

        def json(self):
            return self.json_data

        def raise_for_status(self):
            if self.status_code != 200:
                raise RequestException(
                    "Mock request error with status_code {}.".format(self.status_code)
                )
            pass

    if args[0].startswith(FAKE_CEEPOS_API_URL):
        return MockResponse(data={}, status_code=500)
    else:
        return MockResponse(
            data={
                "Status": 2,
                "PaymentAddress": "https://ceepos-payment-url",
                "Hash": "483e298570c959e5b4af637c63cc216752c6f7ee1ee5149548fde4c4c977e89c",
            }
        )


def test_initiate_payment_success(provider_base_config, order_with_products):
    """Test the request creator constructs the payload base and returns an url."""
    rf = RequestFactory()
    request = rf.post(RESERVATION_LIST_URL)

    payment_provider = create_ceepos_provider(
        provider_base_config, request, UI_RETURN_URL
    )
    with mock.patch(
        "payments.providers.cpu_ceepos.requests.post",
        side_effect=mocked_response_create,
    ):
        url = payment_provider.initiate_payment(order_with_products)
        assert url == "https://ceepos-payment-url"


def test_initiate_payment_error_unavailable(provider_base_config, order_with_products):
    """Test the request creator raises service unavailable if request doesn't go through"""
    rf = RequestFactory()
    request = rf.post(RESERVATION_LIST_URL)

    provider_base_config["RESPA_PAYMENTS_CEEPOS_API_URL"] = FAKE_CEEPOS_API_URL
    unavailable_payment_provider = create_ceepos_provider(
        provider_base_config, request, UI_RETURN_URL
    )

    with mock.patch(
        "payments.providers.cpu_ceepos.requests.post",
        side_effect=mocked_response_create,
    ):
        with pytest.raises(ServiceUnavailableError):
            unavailable_payment_provider.initiate_payment(order_with_products)


def test_handle_initiate_payment_success(payment_provider):
    """Test the response handler recognizes success and returns the payment address"""
    response = json.loads(
        """{
        "Id": "12345",
        "Status": 2,
        "Reference": "10456",
        "Action": "new payment",
        "PaymentAddress": "https://www.example.com/checkout",
        "Hash": "eb4e4b8e30fc1320a3f922bd84e249b518c18b2caa52d9071387685f95b32736"
    }"""
    )
    return_value = payment_provider.handle_initiate_payment_response(response)
    assert response["PaymentAddress"] in return_value


def test_handle_initiate_payment_error_validation_on_status_99(payment_provider):
    """Test the response handler raises PayloadValidationError when the payment status is 99"""
    response = json.loads(
        """{
        "Status": 99,
        "PaymentAddress": "https://www.example.com/checkout",
        "Hash": "47994b075053851153c1a87efa362840f4dd2ce20217f9b5566169677f526f62"
    }"""
    )
    with pytest.raises(PayloadValidationError):
        payment_provider.handle_initiate_payment_response(response)


def test_handle_initiate_payment_error_validation_on_incorrect_checksum(
    payment_provider,
):
    """Test the response handler raises PayloadValidationError when the checksum is incorrect"""
    response = json.loads(
        """{
        "Status": 2,
        "PaymentAddress": "https://www.example.com/checkout",
        "Hash": "12345"
    }"""
    )
    with pytest.raises(PayloadValidationError):
        payment_provider.handle_initiate_payment_response(response)


def test_handle_initiate_payment_error_duplicate(payment_provider):
    """Test the response handler raises DuplicateOrderError as expected"""
    response = json.loads(
        """{
        "Status": 97,
        "PaymentAddress": "https://www.example.com/checkout",
        "Hash": "47994b075053851153c1a87efa362840f4dd2ce20217f9b5566169677f526f62"
    }"""
    )
    with pytest.raises(DuplicateOrderError):
        payment_provider.handle_initiate_payment_response(response)


def test_handle_initiate_payment_error_unavailable(payment_provider):
    """Test the response handler raises ServiceUnavailableError as expected"""
    response = json.loads(
        """{
        "Status": 98,
        "PaymentAddress": "https://www.example.com/checkout",
        "Hash": "47994b075053851153c1a87efa362840f4dd2ce20217f9b5566169677f526f62"
    }"""
    )
    with pytest.raises(ServiceUnavailableError):
        payment_provider.handle_initiate_payment_response(response)


def test_handle_initiate_payment_error_unknown_code(payment_provider):
    """Test the response handler raises UnknownReturnCodeError as expected"""
    response = json.loads(
        """{
        "Status": 15,
        "PaymentAddress": "https://www.example.com/checkout",
        "Hash": "47994b075053851153c1a87efa362840f4dd2ce20217f9b5566169677f526f62"
    }"""
    )
    with pytest.raises(UnknownReturnCodeError):
        payment_provider.handle_initiate_payment_response(response)


def test_payload_add_products_success(payment_provider, order_with_products):
    """Test the products are added correctly into payload"""
    payload = {}
    payment_provider.payload_add_products(payload, order_with_products)

    assert "Products" in payload
    products = payload.get("Products")
    assert len(products) == 2
    # Make sure that all the keys are added
    for product in products:
        assert "Code" in product
        assert "Amount" in product
        assert "Price" in product
        assert "Description" in product
        assert "Taxcode" in product


def test_payload_add_customer_success(payment_provider, order_with_products):
    """Test the customer data from order is added correctly into payload"""
    payload = {}
    payment_provider.payload_add_customer(payload, order_with_products)

    assert payload.get("Email") == "test@example.com"
    assert payload.get("FirstName") == "Seppo"
    assert payload.get("LastName") == "Testi"


def test_payload_add_checksum_success(payment_provider):
    """Test the checksum (hash) is added correctly into the payload"""
    secret = "123"
    payload = {
        "ApiVersion": "2.1.2",
        "Source": "examplecom",
        "Id": "12345",
        "Mode": 3,
        "Action": "new payment",
        "Description": "Charlie Customer",
        "Products": [
            {
                "Code": "1111",
                "Amount": 1,
                "Price": 100,
                "Description": "Product-specific info",
            },
            {"Code": "1212", "Price": 150, "Taxcode": "10"},
        ],
        "Email": "charlie.customer@example.com",
        "FirstName": "Charlie",
        "LastName": "Customer",
        "ReturnAddress": "https://www.example.com/return-path",
        "NotificationAddress": "https://www.example.com/notification-path",
    }
    payment_provider.payload_add_checksum(payload, secret)
    assert "Hash" in payload
    assert (
        payload.get("Hash")
        == "734a651b873a5410d4894ece8261ccd34901942b49871c7c05c68a2a3a6c3561"
    )


def test_calculate_checksum_success(payment_provider):
    """Test the checksum calculation returns a correct hash"""
    values = ["test", 123, "abc123"]
    secret = "123"
    calculated_hash = payment_provider.calculate_checksum(values, secret)
    assert hmac.compare_digest(
        calculated_hash,
        "b020844c98e7959e95967296c2bb50301287f455ee9fbaafa4b6bc1041f7d5d9",
    )


def test_handle_success_request_success(provider_base_config, order_with_products):
    """Test request handling changes the order status to confirmed

    Also check it returns a success url with order number"""
    params = {
        "Id": "abc123",
        "Status": "1",
        "Reference": "123",
        "Hash": "daac0c407cc08b5e679bd2aaa1b39cc3e3e70b6cf5de8b9063cbc66bb9952fd5",
        "RESPA_UI_RETURN_URL": "http%3A%2F%2F127.0.0.1%3A8000%2Fv1",
    }
    rf = RequestFactory()
    request = rf.get("/payments/success/", params)
    payment_provider = create_ceepos_provider(
        provider_base_config, request, UI_RETURN_URL
    )
    returned = payment_provider.handle_success_request()
    order_after = Order.objects.get(order_number=params.get("Id"))
    assert order_after.state == Order.CONFIRMED
    assert isinstance(returned, HttpResponse)
    assert "payment_status=success" in returned.url
    assert "reservation_id={}".format(order_after.reservation.id) in returned.url


def test_handle_success_request_order_not_found(
    provider_base_config, order_with_products
):
    """Test request handling returns a failure url when order can't be found"""
    params = {
        "Id": "abc456",  # no order exists with this id
        "Status": "1",
        "Reference": "123",
        "Hash": "ebe63dd26229fac6310c2cbac206fe5d92f1eac6c40630e65a329b54fb2330ee",
        "RESPA_UI_RETURN_URL": "http%3A%2F%2F127.0.0.1%3A8000%2Fv1",
    }
    rf = RequestFactory()
    request = rf.get("/payments/success/", params)
    payment_provider = create_ceepos_provider(
        provider_base_config, request, UI_RETURN_URL
    )
    returned = payment_provider.handle_success_request()
    assert isinstance(returned, HttpResponse)
    assert "payment_status=failure" in returned.url


def test_handle_success_request_incorrect_checksum(
    provider_base_config, order_with_products
):
    """
    Test request handling returns a failure url when the checksum does not match the payload
    """
    params = {
        "Id": "abc123",
        "Status": "1",
        "Reference": "123",
        "Hash": "abc124354364554765754643634634643574533hogesho38294wdabwcjoeg894",
        "RESPA_UI_RETURN_URL": "http%3A%2F%2F127.0.0.1%3A8000%2Fv1",
    }
    rf = RequestFactory()
    request = rf.get("/payments/success/", params)
    payment_provider = create_ceepos_provider(
        provider_base_config, request, UI_RETURN_URL
    )
    returned = payment_provider.handle_success_request()
    assert isinstance(returned, HttpResponse)
    assert "payment_status=failure" in returned.url


def test_handle_success_request_payment_failed(
    provider_base_config, order_with_products
):
    """Test request handling changes the order status to rejected and returns a failure url"""
    params = {
        "Id": "abc123",
        "Status": "0",
        "Reference": "123",
        "Hash": "d2e9c1286460b6d1cd7d06394de969ab9d12719528f2328b2326469aac57dfcb",
        "RESPA_UI_RETURN_URL": "http%3A%2F%2F127.0.0.1%3A8000%2Fv1",
    }
    rf = RequestFactory()
    request = rf.get("/payments/success/", params)
    payment_provider = create_ceepos_provider(
        provider_base_config, request, UI_RETURN_URL
    )
    returned = payment_provider.handle_success_request()
    order_after = Order.objects.get(order_number=params.get("Id"))
    assert order_after.state == Order.REJECTED
    assert isinstance(returned, HttpResponse)
    assert "payment_status=failure" in returned.url


def test_handle_success_request_system_error(provider_base_config, order_with_products):
    """Test request handling reacts to ceepos system error by returning a failure url"""
    params = {
        "Id": "abc123",
        "Status": "98",
        "Reference": "123",
        "Hash": "b9e0429c78a92c731b4e49144bd581fd958e798152655e733a9e03192840ef16",
        "RESPA_UI_RETURN_URL": "http%3A%2F%2F127.0.0.1%3A8000%2Fv1",
    }
    rf = RequestFactory()
    request = rf.get("/payments/success/", params)
    payment_provider = create_ceepos_provider(
        provider_base_config, request, UI_RETURN_URL
    )
    returned = payment_provider.handle_success_request()
    assert isinstance(returned, HttpResponse)
    assert "payment_status=failure" in returned.url


def test_handle_success_request_unknown_error(
    provider_base_config, order_with_products
):
    """Test request handling returns a failure url when status code is unknown"""
    params = {
        "Id": "abc123",
        "Status": "77",
        "Reference": "123",
        "Hash": "f712cd108691bd22d39b321eb93b8320dd484fe7fa9e71daf0ff0c0ac2e1d41e",
        "RESPA_UI_RETURN_URL": "http%3A%2F%2F127.0.0.1%3A8000%2Fv1",
    }
    rf = RequestFactory()
    request = rf.get("/payments/success/", params)
    payment_provider = create_ceepos_provider(
        provider_base_config, request, UI_RETURN_URL
    )
    returned = payment_provider.handle_success_request()
    assert isinstance(returned, HttpResponse)
    assert "payment_status=failure" in returned.url


def test_handle_notify_request_order_not_found(
    provider_base_config, order_with_products
):
    """Test notify request handling returns HTTP 200 when order can't be found"""
    params = {
        "Id": "abc456",  # no order exists with this id
        "Status": "1",
        "Reference": "123",
        "Hash": "ebe63dd26229fac6310c2cbac206fe5d92f1eac6c40630e65a329b54fb2330ee",
    }
    rf = RequestFactory()
    request = rf.post(
        "/payments/notify/", data=json.dumps(params), content_type="application/json"
    )
    payment_provider = create_ceepos_provider(
        provider_base_config, request, UI_RETURN_URL
    )
    returned = payment_provider.handle_notify_request()
    assert isinstance(returned, HttpResponse)
    assert returned.status_code == 200


@pytest.mark.parametrize(
    "order_state, expected_order_state",
    (
        (Order.WAITING, Order.CONFIRMED),
        (Order.CONFIRMED, Order.CONFIRMED),
        (Order.EXPIRED, Order.EXPIRED),
        (Order.REJECTED, Order.REJECTED),
    ),
)
def test_handle_notify_request_success(
    provider_base_config, order_with_products, order_state, expected_order_state
):
    """Test notify request handling returns HTTP 200 and order status is correct when successful"""
    params = {
        "Id": "abc123",
        "Status": "1",
        "Reference": "123",
        "Hash": "daac0c407cc08b5e679bd2aaa1b39cc3e3e70b6cf5de8b9063cbc66bb9952fd5",
    }
    order_with_products.set_state(order_state)

    rf = RequestFactory()
    request = rf.post(
        "/payments/notify/", data=json.dumps(params), content_type="application/json"
    )
    payment_provider = create_ceepos_provider(
        provider_base_config, request, UI_RETURN_URL
    )
    returned = payment_provider.handle_notify_request()
    order_after = Order.objects.get(order_number=params.get("Id"))
    assert order_after.state == expected_order_state
    assert isinstance(returned, HttpResponse)
    assert returned.status_code == 200


@pytest.mark.parametrize(
    "order_state, expected_order_state",
    (
        (Order.WAITING, Order.REJECTED),
        (Order.REJECTED, Order.REJECTED),
        (Order.EXPIRED, Order.EXPIRED),
        (Order.CONFIRMED, Order.CONFIRMED),
    ),
)
def test_handle_notify_request_payment_failed(
    provider_base_config, order_with_products, order_state, expected_order_state
):
    """Test notify request handling returns HTTP 200 and order status is correct when payment fails"""
    params = {
        "Id": "abc123",
        "Status": "0",
        "Reference": "123",
        "Hash": "d2e9c1286460b6d1cd7d06394de969ab9d12719528f2328b2326469aac57dfcb",
    }
    order_with_products.set_state(order_state)

    rf = RequestFactory()
    request = rf.post(
        "/payments/notify/", data=json.dumps(params), content_type="application/json"
    )
    payment_provider = create_ceepos_provider(
        provider_base_config, request, UI_RETURN_URL
    )
    returned = payment_provider.handle_notify_request()
    order_after = Order.objects.get(order_number=params.get("Id"))
    assert order_after.state == expected_order_state
    assert isinstance(returned, HttpResponse)
    assert returned.status_code == 200


def test_handle_notify_request_unknown_error(provider_base_config, order_with_products):
    """Test notify request handling returns HTTP 200 when status code is unknown"""
    params = {
        "Id": "abc123",
        "Status": "77",
        "Reference": "123",
        "Hash": "f712cd108691bd22d39b321eb93b8320dd484fe7fa9e71daf0ff0c0ac2e1d41e",
    }
    rf = RequestFactory()
    request = rf.post(
        "/payments/notify/", data=json.dumps(params), content_type="application/json"
    )
    payment_provider = create_ceepos_provider(
        provider_base_config, request, UI_RETURN_URL
    )
    returned = payment_provider.handle_notify_request()
    assert isinstance(returned, HttpResponse)
    assert returned.status_code == 200

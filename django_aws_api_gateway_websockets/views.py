import json
import logging
from typing import Union

from django.conf import settings
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class WebSocketView(View):
    route_selection_key = 'action'
    model = None
    body = dict()
    aws_api_gateway_id = None  # Set to None to allow all
    required_headers = [
        'Host', 'X-Real-Ip', 'X-Forwarded-For', 'X-Forwarded-Proto', 'Connection', 'Content-Length',
        'X-Forwarded-Port', 'X-Amzn-Trace-Id', 'Connectionid', 'User-Agent', 'X-Amzn-Apigateway-Api-Id'
    ]
    required_connection_headers = [
        'Cookie', 'Origin', 'Sec-Websocket-Extensions', 'Sec-Websocket-Key', 'Sec-Websocket-Version'
    ]
    expected_useragent_prefix = 'AmazonAPIGateway_'

    def setup(self, request, *args, **kwargs):
        """Converts the request.body string back into a dictionary and assign to the objets body property for ease"""
        super().setup(request, *args, **kwargs)
        self.body = json.loads(request.body) if request.body else dict()

    def _return_bad_request(self, request, msg):
        """Common method for logging and returning the HTTP400 response"""
        logger.warning(msg, extra={'status_code': 400, 'request': request})
        return HttpResponseBadRequest(msg)

    def route_selection_key_missing(self, request, *args, **kwargs) -> HttpResponseBadRequest:
        """Method for handling missing route_selection_key"""
        msg = f'route_select_key {self.route_selection_key} missing from request body.'
        return self._return_bad_request(request, msg)

    def missing_headers(self, request, *args, **kwargs) -> HttpResponseBadRequest:
        """Method for handling missing headers"""
        msg = f'Some of the required headers are missing; Expected {self.required_headers}, Received {request.headers}'
        return self._return_bad_request(request, msg)

    def invalid_useragent(self, request, *args, **kwargs) -> HttpResponseBadRequest:
        """Method for handling unexpected useragents"""
        msg = f'Unexpected Useragent; Expected {self.expected_useragent_prefix}{self.aws_api_gateway_id}, ' \
              f"Received {request.headers['User-Agent']}"
        return self._return_bad_request(request, msg)

    def _expected_headers(self, request, *args, **kwargs) -> bool:
        """Ensure that all required headers exist within the request header"""
        request_headers = request.headers.keys()
        return all(h in request_headers for h in self.required_headers)

    def _expected_apigateway_id(self, request, *args, **kwargs) -> bool:
        """Ensure expected AWS Gateway ID if one is set, if expected value not set then allow all"""
        return self.aws_api_gateway_id and request.headers['X-Amzn-Apigateway-Api-Id'] is not self.aws_api_gateway_id

    def _expected_useragent(self, request, *args, **kwargs) -> bool:
        """Validated that the useragent is the expected one for all calls except the connect method"""
        if self.aws_api_gateway_id:
            return request.headers['User-Agent'] is not f'{self.expected_useragent_prefix}{self.aws_api_gateway_id}'
        return self.expected_useragent_prefix in request.headers['User-Agent']

    @staticmethod
    def _check_allowed_hosts(request) -> bool:
        """Check that the host is within the allowed hosts"""
        if settings.ALLOWED_HOSTS and request.headers['Host'] not in settings.ALLOWED_HOSTS:
            logger.warning(
                f"{request.headers['Host']} not in settings.ALLOWED_HOSTS",
                extra={'status_code': 400, 'request': request}
            )
            return False
        return True

    @staticmethod
    def _check_host_is_in_origin(request) -> bool:
        """Check that the value of the Host header is within the Origin header. Origin will have the protocol as well"""
        if request.headers['Host'] not in request.headers['Origin']:
            logger.warning(
                f"{request.headers['Host']} not in {request.headers['Origin']}",
                extra={'status_code': 400, 'request': request}
            )
            return False
        return True

    def _expected_connection_headers(self, request, *args, **kwargs) -> bool:
        """Run additional checks for the connection route for security"""
        request_headers = request.headers.keys()
        return all(h in request_headers for h in self.required_connection_headers)

    def _add_user_to_request(self, request):
        """Fetch the user from the model and append it back into the request variable"""
        # todo - Implement this when the model is used
        # wss = WebSocketSession.objects.get(connection_id=request.headers['Connectionid'])
        # request.user = wss.user
        pass

    def dispatch(self, request, *args, **kwargs):
        """Determine the correct method to call. The method will map to the route_selection_key or default.

        Checks for the expected headers first of all.
        Tries to dispatch to the right method; if a method doesn't exist defer to the default handler.
        If the Route Selection Key is missing defer to the route selection error handler.
        If the request method isn't on the approved list then defer to the normal error handler .
        """
        if self._expected_headers(request):
            if request.method.lower() in self.http_method_names:
                if 'connect' == self.kwargs['slug']:
                    handler = self.connect
                elif 'disconnect' == self.kwargs['slug']:
                    if not self._expected_useragent(request, *args, **kwargs):
                        handler = self.invalid_useragent
                    else:
                        handler = self.disconnect
                        self._add_user_to_request(request)
                elif self.route_selection_key in self.body:
                    handler = getattr(self, self.body[self.route_selection_key], self.default)
                    if not self._expected_useragent(request, *args, **kwargs):
                        handler = self.invalid_useragent
                    else:
                        self._add_user_to_request(request)
                else:
                    handler = self.route_selection_key_missing
            else:
                handler = self.http_method_not_allowed
        else:
            handler = self.missing_headers
        return handler(request, *args, **kwargs)

    def connect(self, request, *args, **kwargs) -> Union[JsonResponse, HttpResponseBadRequest]:
        """Handle the connection route in a standard way that ensures the User to Connectionid mapping persists"""
        if not self._expected_connection_headers(request, *args, **kwargs):
            msg = f'Missing headers; Expected {self.required_connection_headers}, Received {request.headers}'
            return self._return_bad_request(request, msg)

        if not self._check_allowed_hosts(request):
            msg = f"Host {request.headers['Host']} not in AllowedHosts {settings.ALLOWED_HOSTS}"
            return self._return_bad_request(request, msg)

        if not self._check_host_is_in_origin(request):
            msg = f"Host {request.headers['Host']} not in Origin {request.headers['Host']}"
            return self._return_bad_request(request, msg)

        # todo - Could add in additional steps for certificates, APIGateway Authorizers etc

        # Todo - Once the model is defined enable these
        # `channel` could be set via a querystring parameter passed to the API
        # WebSocketSession.objects.create(user=request.user, connection_id=request.headers['Connectionid'])

        logger.debug(f"\n\n\nslug={self.kwargs['slug']}; request.user.pk={request.user.pk}\n\n")

        return JsonResponse(dict())

    def disconnect(self, request, *args, **kwargs) -> JsonResponse:
        """Using connectionId update websocket table to show as disconnected"""
        # Todo - Once the model is defined enable these
        # wss = WebSocketSession.objects.get(connection_id=request.headers['Connectionid'])
        # wss.connected = False
        # wss.save()

        logger.debug("Would update the websocket class to set connected as false")

        return JsonResponse(dict())

    def default(self, request, *args, **kwargs) -> JsonResponse:
        raise NotImplementedError("This logic needs to be defined within the subclass")
import logging
from collections import OrderedDict
from pathlib import Path

import litellm
import requests
from allauth.mfa import signals
from allauth.mfa.adapter import get_adapter as get_mfa_adapter
from allauth.mfa.base.internal.flows import delete_and_cleanup
from allauth.mfa.models import Authenticator
from allauth.mfa.recovery_codes.internal.flows import auto_generate_recovery_codes
from allauth.mfa.totp.internal import auth as totp_auth
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.contrib.staticfiles.storage import staticfiles_storage
from django.db.models.functions import Lower
from django.http import FileResponse
from django.http import HttpResponseBadRequest
from django.http import HttpResponseForbidden
from django.http import HttpResponseNotFound
from django.views.generic import View
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import extend_schema_view
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.generics import GenericAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import DjangoModelPermissions
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from documents.index import DelayedQuery
from documents.permissions import PaperlessObjectPermissions
from documents.tasks import llmindex_index
from paperless.filters import GroupFilterSet
from paperless.filters import UserFilterSet
from paperless.models import ApplicationConfiguration
from paperless.serialisers import ApplicationConfigurationSerializer
from paperless.serialisers import GroupSerializer
from paperless.serialisers import PaperlessAuthTokenSerializer
from paperless.serialisers import ProfileSerializer
from paperless.serialisers import UserSerializer
from paperless_ai.indexing import vector_store_file_exists

logger = logging.getLogger("paperless.views")


class PaperlessObtainAuthTokenView(ObtainAuthToken):
    serializer_class = PaperlessAuthTokenSerializer


class StandardPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100000

    def get_paginated_response(self, data):
        return Response(
            OrderedDict(
                [
                    ("count", self.page.paginator.count if self.page else 0),
                    ("next", self.get_next_link()),
                    ("previous", self.get_previous_link()),
                    ("all", self.get_all_result_ids()),
                    ("results", data),
                ],
            ),
        )

    def get_all_result_ids(self):
        if not self.page:
            return []
        query = self.page.paginator.object_list
        if isinstance(query, DelayedQuery):
            try:
                ids = [
                    query.searcher.ixreader.stored_fields(
                        doc_num,
                    )["id"]
                    for doc_num in query.saved_results.get(0).results.docs()
                ]
            except Exception:
                ids = []
        else:
            ids = list(self.page.paginator.object_list.values_list("pk", flat=True))
        return ids

    def get_paginated_response_schema(self, schema):
        response_schema = super().get_paginated_response_schema(schema)
        response_schema["properties"]["all"] = {
            "type": "array",
            "example": "[1, 2, 3]",
            "items": {"type": "integer"},
        }
        return response_schema


class FaviconView(View):
    def get(self, request, *args, **kwargs):
        try:
            path = Path(staticfiles_storage.path("paperless/img/favicon.ico"))
            return FileResponse(path.open("rb"), content_type="image/x-icon")
        except FileNotFoundError:
            return HttpResponseNotFound("favicon.ico not found")


class UserViewSet(ModelViewSet):
    model = User

    queryset = User.objects.exclude(
        username__in=["consumer", "AnonymousUser"],
    ).order_by(Lower("username"))

    serializer_class = UserSerializer
    pagination_class = StandardPagination
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)
    filter_backends = (DjangoFilterBackend, OrderingFilter)
    filterset_class = UserFilterSet
    ordering_fields = ("username",)

    def create(self, request, *args, **kwargs):
        if not request.user.is_superuser and request.data.get("is_superuser") is True:
            return HttpResponseForbidden(
                "Superuser status can only be granted by a superuser",
            )
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        user_to_update: User = self.get_object()
        if not request.user.is_superuser and user_to_update.is_superuser:
            return HttpResponseForbidden(
                "Superusers can only be modified by other superusers",
            )
        if (
            not request.user.is_superuser
            and request.data.get("is_superuser") is not None
            and request.data.get("is_superuser") != user_to_update.is_superuser
        ):
            return Response(
                "Superuser status can only be changed by a superuser",
                status=403,
            )
        return super().update(request, *args, **kwargs)

    @extend_schema(
        request=None,
        responses={
            200: OpenApiTypes.BOOL,
            404: OpenApiTypes.STR,
        },
    )
    @action(detail=True, methods=["post"])
    def deactivate_totp(self, request, pk=None):
        request_user = request.user
        user = User.objects.get(pk=pk)
        if not request_user.is_superuser and request_user != user:
            return HttpResponseForbidden(
                "You do not have permission to deactivate TOTP for this user",
            )
        authenticator = Authenticator.objects.filter(
            user=user,
            type=Authenticator.Type.TOTP,
        ).first()
        if authenticator is not None:
            delete_and_cleanup(request, authenticator)
            return Response(data=True)
        else:
            return HttpResponseNotFound("TOTP not found")


class GroupViewSet(ModelViewSet):
    model = Group

    queryset = Group.objects.order_by(Lower("name"))

    serializer_class = GroupSerializer
    pagination_class = StandardPagination
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)
    filter_backends = (DjangoFilterBackend, OrderingFilter)
    filterset_class = GroupFilterSet
    ordering_fields = ("name",)


class ProfileView(GenericAPIView):
    """
    User profile view, only available when logged in
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ProfileSerializer

    def get(self, request, *args, **kwargs):
        user = self.request.user

        serializer = self.get_serializer(data=request.data)
        return Response(serializer.to_representation(user))

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = self.request.user if hasattr(self.request, "user") else None

        password = serializer.validated_data.pop("password", None)
        if password and password.replace("*", ""):
            user.set_password(password)
            user.save()

        for key, value in serializer.validated_data.items():
            setattr(user, key, value)
        user.save()

        return Response(serializer.to_representation(user))


@extend_schema_view(
    get=extend_schema(
        responses={
            (200, "application/json"): OpenApiTypes.OBJECT,
        },
    ),
    post=extend_schema(
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "secret": {"type": "string"},
                    "code": {"type": "string"},
                },
                "required": ["secret", "code"],
            },
        },
        responses={
            (200, "application/json"): OpenApiTypes.OBJECT,
        },
    ),
    delete=extend_schema(
        responses={
            (200, "application/json"): OpenApiTypes.BOOL,
            404: OpenApiTypes.STR,
        },
    ),
)
class TOTPView(GenericAPIView):
    """
    TOTP views
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        """
        Generates a new TOTP secret and returns the URL and SVG
        """
        user = self.request.user
        mfa_adapter = get_mfa_adapter()
        secret = totp_auth.get_totp_secret(regenerate=True)
        url = mfa_adapter.build_totp_url(user, secret)
        svg = mfa_adapter.build_totp_svg(url)
        return Response(
            {
                "url": url,
                "qr_svg": svg,
                "secret": secret,
            },
        )

    def post(self, request, *args, **kwargs):
        """
        Validates a TOTP code and activates the TOTP authenticator
        """
        valid = totp_auth.validate_totp_code(
            request.data["secret"],
            request.data["code"],
        )
        recovery_codes = None
        if valid:
            auth = totp_auth.TOTP.activate(
                request.user,
                request.data["secret"],
            ).instance
            signals.authenticator_added.send(
                sender=Authenticator,
                request=request,
                user=request.user,
                authenticator=auth,
            )
            rc_auth: Authenticator = auto_generate_recovery_codes(request)
            if rc_auth:
                recovery_codes = rc_auth.wrap().get_unused_codes()
        return Response(
            {
                "success": valid,
                "recovery_codes": recovery_codes,
            },
        )

    def delete(self, request, *args, **kwargs):
        """
        Deactivates the TOTP authenticator
        """
        user = self.request.user
        authenticator = Authenticator.objects.filter(
            user=user,
            type=Authenticator.Type.TOTP,
        ).first()
        if authenticator is not None:
            delete_and_cleanup(request, authenticator)
            return Response(data=True)
        else:
            return HttpResponseNotFound("TOTP not found")


@extend_schema_view(
    post=extend_schema(
        request={
            "application/json": None,
        },
        responses={
            (200, "application/json"): OpenApiTypes.STR,
        },
    ),
)
class GenerateAuthTokenView(GenericAPIView):
    """
    Generates (or re-generates) an auth token, requires a logged in user
    unlike the default DRF endpoint
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = self.request.user

        existing_token = Token.objects.filter(user=user).first()
        if existing_token is not None:
            existing_token.delete()
        token = Token.objects.create(user=user)
        return Response(
            token.key,
        )


@extend_schema_view(
    list=extend_schema(
        description="Get the application configuration",
        external_docs={
            "description": "Application Configuration",
            "url": "https://docs.paperless-ngx.com/configuration/",
        },
    ),
)
class ApplicationConfigurationViewSet(ModelViewSet):
    model = ApplicationConfiguration

    queryset = ApplicationConfiguration.objects

    serializer_class = ApplicationConfigurationSerializer
    permission_classes = (IsAuthenticated, DjangoModelPermissions)

    @extend_schema(exclude=True)
    def create(self, request, *args, **kwargs):
        return Response(status=405)  # Not Allowed

    def perform_update(self, serializer):
        old_instance = ApplicationConfiguration.objects.all().first()
        old_ai_index_enabled = (
            old_instance.ai_enabled and old_instance.llm_embedding_backend
        )

        new_instance: ApplicationConfiguration = serializer.save()
        new_ai_index_enabled = (
            new_instance.ai_enabled and new_instance.llm_embedding_backend
        )

        if (
            old_instance
            and not old_ai_index_enabled
            and new_ai_index_enabled
            and not vector_store_file_exists()
        ):
            # AI index was just enabled and vector store file does not exist
            llmindex_index.delay(
                progress_bar_disable=True,
                rebuild=True,
                scheduled=False,
                auto=True,
            )

    @action(detail=False, methods=["post"])
    def rebuild_index(self, request, *args, **kwargs):
        llmindex_index.delay(
            progress_bar_disable=True,
            rebuild=True,
            scheduled=False,
            auto=False,
        )
        return Response({"status": "Index rebuild started"})


@extend_schema_view(
    post=extend_schema(
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                },
                "required": ["id"],
            },
        },
        responses={
            (200, "application/json"): OpenApiTypes.INT,
            400: OpenApiTypes.STR,
        },
    ),
)
class DisconnectSocialAccountView(GenericAPIView):
    """
    Disconnects a social account provider from the user account
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = self.request.user

        try:
            account = user.socialaccount_set.get(pk=request.data["id"])
            account_id = account.id
            account.delete()
            return Response(account_id)
        except SocialAccount.DoesNotExist:
            return HttpResponseBadRequest("Social account not found")


@extend_schema_view(
    get=extend_schema(
        responses={
            (200, "application/json"): OpenApiTypes.OBJECT,
        },
    ),
)
class SocialAccountProvidersView(GenericAPIView):
    """
    List of social account providers
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        adapter = get_adapter()
        providers = adapter.list_providers(request)
        resp = [
            {"name": p.name, "login_url": p.get_login_url(request, process="connect")}
            for p in providers
            if p.id != "openid"
        ]

        for openid_provider in filter(lambda p: p.id == "openid", providers):
            resp += [
                {
                    "name": b["name"],
                    "login_url": openid_provider.get_login_url(
                        request,
                        process="connect",
                        openid=b["openid_url"],
                    ),
                }
                for b in openid_provider.get_brands()
            ]

        return Response(sorted(resp, key=lambda p: p["name"]))


class LLMProxyView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    def _get_endpoint(self, request):
        # check if passed in body
        endpoint = request.data.get("endpoint")
        if not endpoint:
            endpoint = request.query_params.get("endpoint")

        # If not passed, check configured backend
        if not endpoint:
            from paperless.config import AIConfig
            from paperless.config import OllamaConfig

            # Ideally we check which backend is being tested
            backend = request.data.get("backend") or request.query_params.get("backend")

            # Check general AI configuration first if backend matches
            # This ensures that testing the LLM uses the LLM endpoint even if
            # the OCR engine is using a different (or default) Ollama endpoint.
            ai_config = AIConfig()
            if backend == ai_config.llm_backend and ai_config.llm_endpoint:
                endpoint = ai_config.llm_endpoint

            # Fallback to specific OCR config if still not found
            if not endpoint:
                if backend == "ollama":
                    config = OllamaConfig()
                    endpoint = config.endpoint
                elif ai_config.llm_backend == backend:
                    # Final fallback to what we found earlier (safeguard)
                    endpoint = ai_config.llm_endpoint

        return endpoint

    def _normalize_endpoint(self, endpoint):
        if not endpoint:
            return None

        if not endpoint.startswith("http"):
            endpoint = f"http://{endpoint}"

        return endpoint.rstrip("/")

    def get(self, request, path=None, *args, **kwargs):
        endpoint = self._get_endpoint(request)
        endpoint = self._normalize_endpoint(endpoint)

        backend = request.query_params.get("backend")

        # For OpenAI-compatible or other providers that don't need proxying for models,
        # we can return a static list or filtered list
        if backend == "openai" or not endpoint:
            # Return common OpenAI models
            return Response(
                [
                    {"id": "gpt-4o", "name": "gpt-4o"},
                    {"id": "gpt-4-turbo", "name": "gpt-4-turbo"},
                    {"id": "gpt-4", "name": "gpt-4"},
                    {"id": "gpt-3.5-turbo", "name": "gpt-3.5-turbo"},
                ],
            )

        # For Ollama, proxy to /api/tags to get actual models
        if backend == "ollama" and endpoint:
            try:
                url = f"{endpoint}/api/tags"
                response = requests.get(url, timeout=30)  # Increase timeout
                if response.status_code == 200:
                    return Response(response.json())
            except Exception as e:
                logger.warning(
                    f"Failed to fetch Ollama models from {endpoint}/api/tags: {e}",
                )

        return Response([])

    def post(self, request, path=None, *args, **kwargs):
        # Handle test connection
        if path == "test":
            return self.test_connection(request)
        return Response(status=404)

    def test_connection(self, request):
        endpoint = self._get_endpoint(request)
        endpoint = self._normalize_endpoint(endpoint)

        backend = request.data.get("backend") or "ollama"
        api_key = request.data.get("api_key")
        model = request.data.get("model") or "test"

        try:
            import time

            start_time = time.time()

            # FAST PATH for Ollama: Check version instead of full generation
            if backend == "ollama" and endpoint:
                try:
                    resp = requests.get(f"{endpoint}/api/version", timeout=5)
                    if resp.status_code == 200:
                        latency = int((time.time() - start_time) * 1000)
                        return Response(
                            {
                                "success": True,
                                "latency_ms": latency,
                                "model_info": {
                                    "provider": backend,
                                    "version": resp.json().get("version"),
                                },
                            },
                        )
                except Exception as e:
                    logger.warning(f"Ollama fast version check failed: {e}")
                    # Fallback to standard generation test if version check fails

            # Construct model name with prefix if needed
            model_name = f"{backend}/{model}" if "/" not in model else model

            # Determine params based on backend
            params = {
                "model": model_name,
                "messages": [{"role": "user", "content": "Hi"}],
                "api_key": api_key,
                # Short timeout for testing
                "timeout": 30,
            }

            if endpoint:
                params["api_base"] = endpoint

            # Make request
            _response = litellm.completion(**params)

            latency = int((time.time() - start_time) * 1000)

            return Response(
                {
                    "success": True,
                    "latency_ms": latency,
                    "model_info": {
                        "provider": backend,
                        "model": model_name,
                    },
                },
            )

        except Exception as e:
            return Response(
                {
                    "success": False,
                    "error": str(e),
                },
            )


class OllamaProxyView(LLMProxyView):
    permission_classes = [IsAuthenticated]

    def _get_endpoint(self, request):
        # Original logic for backward compatibility
        endpoint = request.query_params.get("endpoint")
        if not endpoint:
            from paperless.config import OllamaConfig

            config = OllamaConfig()
            endpoint = config.endpoint

        if not endpoint:
            return None

        if not endpoint.startswith("http"):
            endpoint = f"http://{endpoint}"

        return endpoint.rstrip("/")

    def get(self, request, path=None, *args, **kwargs):
        endpoint = self._get_endpoint(request)
        if not endpoint:
            return HttpResponseBadRequest("Ollama endpoint not configured")

        path = path or "api/tags"
        try:
            url = f"{endpoint}/{path}"
            # Extract params and remove proxy-specific ones
            params = request.GET.copy()
            params.pop("endpoint", None)
            params.pop("backend", None)
            response = requests.get(url, params=params, timeout=30)
            return Response(response.json(), status=response.status_code)
        except requests.RequestException as e:
            return Response({"error": str(e)}, status=400)

    def post(self, request, path=None, *args, **kwargs):
        # We need to check if it's the test endpoint from the base class
        # But the original OllamaProxyView used path for proxying too.
        # "path" comes from the URL capture.
        if path == "test":
            return self.test_connection(request)

        endpoint = self._get_endpoint(request)
        if not endpoint:
            return HttpResponseBadRequest("Ollama endpoint not configured")

        path = path or "api/generate"
        try:
            url = f"{endpoint}/{path}"
            # Extract data and remove proxy-specific ones if any
            data = request.data.copy()
            # Ollama doesn't use these but we might have them from LLM proxy interface
            data.pop("endpoint", None)
            data.pop("backend", None)
            response = requests.post(url, json=data, timeout=120)
            return Response(response.json(), status=response.status_code)
        except requests.RequestException as e:
            return Response({"error": str(e)}, status=400)


class DoclingProxyView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        endpoint = request.query_params.get("endpoint")
        if not endpoint:
            return HttpResponseBadRequest("Missing endpoint parameter")

        try:
            # Ensure protocol
            if not endpoint.startswith("http"):
                endpoint = f"http://{endpoint}"

            # Strip trailing slash
            if endpoint.endswith("/"):
                endpoint = endpoint[:-1]

            # Try health endpoint first
            try:
                response = requests.get(f"{endpoint}/v1/health", timeout=5)
                response.raise_for_status()
                return Response(
                    {"status": "ok", "detail": "Connected to Docling Health Endpoint"},
                )
            except requests.RequestException:
                # Fallback to root if health endpoint missing
                response = requests.get(endpoint, timeout=5)
                # Docling server might return 404 on root but connection works
                # We consider connection success if we get a response
                return Response(
                    {
                        "status": "ok",
                        "detail": f"Connected (Status {response.status_code})",
                    },
                )

        except requests.RequestException as e:
            return Response({"error": str(e)}, status=400)

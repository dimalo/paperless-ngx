import logging

import magic
from allauth.mfa.adapter import get_adapter as get_mfa_adapter
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import TOTP
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.models import SocialApp
from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.files.uploadedfile import UploadedFile
from rest_framework import serializers
from rest_framework.authtoken.serializers import AuthTokenSerializer

from paperless.models import ApplicationConfiguration
from paperless.validators import reject_dangerous_svg
from paperless_mail.serialisers import ObfuscatedPasswordField

logger = logging.getLogger("paperless.settings")


class PasswordValidationMixin:
    def _has_real_password(self, value: str | None) -> bool:
        return bool(value) and value.replace("*", "") != ""

    def validate_password(self, value: str) -> str:
        if not self._has_real_password(value):
            return value

        request = self.context.get("request") if hasattr(self, "context") else None
        user = self.instance or (
            request.user if request and hasattr(request, "user") else None
        )
        validate_password(value, user)  # raise ValidationError if invalid

        return value


class PaperlessAuthTokenSerializer(AuthTokenSerializer):
    code = serializers.CharField(
        label="MFA Code",
        write_only=True,
        required=False,
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        user = attrs.get("user")
        code = attrs.get("code")
        mfa_adapter = get_mfa_adapter()
        if mfa_adapter.is_mfa_enabled(user):
            if not code:
                raise serializers.ValidationError(
                    "MFA code is required",
                )
            authenticator = Authenticator.objects.get(
                user=user,
                type=Authenticator.Type.TOTP,
            )
            if not TOTP(instance=authenticator).validate_code(
                code,
            ):
                raise serializers.ValidationError(
                    "Invalid MFA code",
                )
        return attrs


class UserSerializer(PasswordValidationMixin, serializers.ModelSerializer):
    password = ObfuscatedPasswordField(required=False)
    user_permissions = serializers.SlugRelatedField(
        many=True,
        queryset=Permission.objects.exclude(content_type__app_label="admin"),
        slug_field="codename",
        required=False,
    )
    inherited_permissions = serializers.SerializerMethodField()
    is_mfa_enabled = serializers.SerializerMethodField()

    def get_is_mfa_enabled(self, user: User) -> bool:
        mfa_adapter = get_mfa_adapter()
        return mfa_adapter.is_mfa_enabled(user)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "password",
            "first_name",
            "last_name",
            "date_joined",
            "is_staff",
            "is_active",
            "is_superuser",
            "groups",
            "user_permissions",
            "inherited_permissions",
            "is_mfa_enabled",
        )

    def get_inherited_permissions(self, obj) -> list[str]:
        return obj.get_group_permissions()

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        if self._has_real_password(password):
            instance.set_password(password)
            instance.save()

        super().update(instance, validated_data)
        return instance

    def create(self, validated_data):
        groups = None
        if "groups" in validated_data:
            groups = validated_data.pop("groups")
        user_permissions = None
        if "user_permissions" in validated_data:
            user_permissions = validated_data.pop("user_permissions")
        password = validated_data.pop("password", None)
        user = User.objects.create(**validated_data)
        # set groups
        if groups:
            user.groups.set(groups)
        # set permissions
        if user_permissions:
            user.user_permissions.set(user_permissions)
        # set password
        if self._has_real_password(password):
            user.set_password(password)
        user.save()
        return user


class GroupSerializer(serializers.ModelSerializer):
    permissions = serializers.SlugRelatedField(
        many=True,
        queryset=Permission.objects.exclude(content_type__app_label="admin"),
        slug_field="codename",
    )

    class Meta:
        model = Group
        fields = (
            "id",
            "name",
            "permissions",
        )


class SocialAccountSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = SocialAccount
        fields = (
            "id",
            "provider",
            "name",
        )

    def get_name(self, obj: SocialAccount) -> str:
        try:
            return obj.get_provider_account().to_str()
        except SocialApp.DoesNotExist:
            return "Unknown App"


class ProfileSerializer(PasswordValidationMixin, serializers.ModelSerializer):
    email = serializers.EmailField(allow_blank=True, required=False)
    password = ObfuscatedPasswordField(required=False, allow_null=False)
    auth_token = serializers.SlugRelatedField(read_only=True, slug_field="key")
    social_accounts = SocialAccountSerializer(
        many=True,
        read_only=True,
        source="socialaccount_set",
    )
    is_mfa_enabled = serializers.SerializerMethodField()
    has_usable_password = serializers.SerializerMethodField()

    def get_is_mfa_enabled(self, user: User) -> bool:
        mfa_adapter = get_mfa_adapter()
        return mfa_adapter.is_mfa_enabled(user)

    def get_has_usable_password(self, user: User) -> bool:
        return user.has_usable_password()

    class Meta:
        model = User
        fields = (
            "email",
            "password",
            "first_name",
            "last_name",
            "auth_token",
            "social_accounts",
            "has_usable_password",
            "is_mfa_enabled",
        )


class ApplicationConfigurationSerializer(serializers.ModelSerializer):
    user_args = serializers.JSONField(binary=True, allow_null=True)
    barcode_tag_mapping = serializers.JSONField(binary=True, allow_null=True)
    llm_api_key = ObfuscatedPasswordField(
        required=False,
        allow_null=True,
    )

    # Defaults (read-only) to show what's active if the DB value is empty
    defaults = serializers.SerializerMethodField()

    def get_defaults(self, obj):
        return {
            "output_type": settings.OCR_OUTPUT_TYPE,
            "pages": settings.OCR_PAGES,
            "language": settings.OCR_LANGUAGE,
            "mode": settings.OCR_MODE,
            "skip_archive_file": settings.OCR_SKIP_ARCHIVE_FILE,
            "image_dpi": settings.OCR_IMAGE_DPI,
            "unpaper_clean": settings.OCR_CLEAN,
            "deskew": settings.OCR_DESKEW,
            "rotate_pages": settings.OCR_ROTATE_PAGES,
            "rotate_pages_threshold": settings.OCR_ROTATE_PAGES_THRESHOLD,
            "max_image_pixels": settings.OCR_MAX_IMAGE_PIXELS,
            "color_conversion_strategy": settings.OCR_COLOR_CONVERSION_STRATEGY,
            "ocr_engine_priority": settings.OCR_ENGINE_PRIORITY,
            # Barcodes
            "barcodes_enabled": settings.CONSUMER_ENABLE_BARCODES,
            "barcode_enable_tiff_support": settings.CONSUMER_BARCODE_TIFF_SUPPORT,
            "barcode_string": settings.CONSUMER_BARCODE_STRING,
            "barcode_retain_split_pages": settings.CONSUMER_BARCODE_RETAIN_SPLIT_PAGES,
            "barcode_enable_asn": settings.CONSUMER_ENABLE_ASN_BARCODE,
            "barcode_asn_prefix": settings.CONSUMER_ASN_BARCODE_PREFIX,
            "barcode_upscale": settings.CONSUMER_BARCODE_UPSCALE,
            "barcode_dpi": settings.CONSUMER_BARCODE_DPI,
            "barcode_max_pages": settings.CONSUMER_BARCODE_MAX_PAGES,
            "barcode_enable_tag": settings.CONSUMER_ENABLE_TAG_BARCODE,
            "barcode_tag_mapping": settings.CONSUMER_TAG_BARCODE_MAPPING,
            "barcode_tag_split": settings.CONSUMER_TAG_BARCODE_SPLIT,
            # AI
            "ai_enabled": settings.AI_ENABLED,
            "llm_embedding_backend": settings.LLM_EMBEDDING_BACKEND,
            "llm_embedding_model": settings.LLM_EMBEDDING_MODEL,
            "llm_backend": settings.LLM_BACKEND,
            "llm_model": settings.LLM_MODEL,
            "llm_endpoint": settings.LLM_ENDPOINT,
            # Docling
            "docling_force_ocr": settings.DOCLING_FORCE_OCR,
            "docling_language": settings.DOCLING_LANGUAGE,
            "docling_endpoint": settings.DOCLING_ENDPOINT,
            "docling_timeout": settings.DOCLING_TIMEOUT,
        }

    def run_validation(self, data):
        # Empty strings treated as None to avoid unexpected behavior
        if "user_args" in data and data["user_args"] == "":
            data["user_args"] = None
        if "barcode_tag_mapping" in data and data["barcode_tag_mapping"] == "":
            data["barcode_tag_mapping"] = None
        if "language" in data and data["language"] == "":
            data["language"] = None
        if "llm_api_key" in data and data["llm_api_key"] is not None:
            if data["llm_api_key"] == "":
                data["llm_api_key"] = None
            elif len(data["llm_api_key"].replace("*", "")) == 0:
                del data["llm_api_key"]
        return super().run_validation(data)

    def update(self, instance, validated_data):
        if instance.app_logo and "app_logo" in validated_data:
            instance.app_logo.delete()
        return super().update(instance, validated_data)

    def validate_app_logo(self, file: UploadedFile):
        if file and magic.from_buffer(file.read(2048), mime=True) == "image/svg+xml":
            reject_dangerous_svg(file)
        return file

    class Meta:
        model = ApplicationConfiguration
        fields = "__all__"

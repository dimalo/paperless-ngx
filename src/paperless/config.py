import dataclasses
import json

from django.conf import settings

from paperless.models import ApplicationConfiguration


@dataclasses.dataclass
class BaseConfig:
    """
    Almost all parsers care about the chosen PDF output format
    """

    @staticmethod
    def _get_config_instance() -> ApplicationConfiguration:
        from django.db.utils import ProgrammingError

        from paperless.models import ApplicationConfiguration

        try:
            app_config = ApplicationConfiguration.objects.all().first()
            return app_config if app_config is not None else ApplicationConfiguration()
        except (ProgrammingError, AttributeError):
            return ApplicationConfiguration()


@dataclasses.dataclass
class OutputTypeConfig(BaseConfig):
    """
    Almost all parsers care about the chosen PDF output format
    """

    output_type: str = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        app_config = self._get_config_instance()

        self.output_type = app_config.output_type or settings.OCR_OUTPUT_TYPE


@dataclasses.dataclass
class OcrConfig(OutputTypeConfig):
    """
    Specific settings for the Tesseract based parser.  Options generally
    correspond almost directly to the OCRMyPDF options
    """

    pages: int | None = dataclasses.field(init=False)
    language: str = dataclasses.field(init=False)
    mode: str = dataclasses.field(init=False)
    skip_archive_file: str = dataclasses.field(init=False)
    image_dpi: int | None = dataclasses.field(init=False)
    clean: str = dataclasses.field(init=False)
    deskew: bool = dataclasses.field(init=False)
    rotate: bool = dataclasses.field(init=False)
    rotate_threshold: float = dataclasses.field(init=False)
    max_image_pixel: float | None = dataclasses.field(init=False)
    color_conversion_strategy: str = dataclasses.field(init=False)
    user_args: dict[str, str] | None = dataclasses.field(init=False)
    sharpen: bool = dataclasses.field(init=False)
    custom_alignment: bool = dataclasses.field(init=False)
    sharpen_radius: float = dataclasses.field(init=False)
    sharpen_percent: float = dataclasses.field(init=False)
    sharpen_threshold: float = dataclasses.field(init=False)
    alignment_threshold: float = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()

        app_config = self._get_config_instance()

        self.pages = app_config.pages or settings.OCR_PAGES
        self.language = app_config.language or settings.OCR_LANGUAGE
        self.mode = app_config.mode or settings.OCR_MODE
        self.skip_archive_file = (
            app_config.skip_archive_file or settings.OCR_SKIP_ARCHIVE_FILE
        )
        self.image_dpi = app_config.image_dpi or settings.OCR_IMAGE_DPI
        self.clean = app_config.unpaper_clean or settings.OCR_CLEAN
        self.deskew = (
            app_config.deskew if app_config.deskew is not None else settings.OCR_DESKEW
        )
        self.rotate = (
            app_config.rotate_pages
            if app_config.rotate_pages is not None
            else settings.OCR_ROTATE_PAGES
        )
        self.rotate_threshold = (
            app_config.rotate_pages_threshold or settings.OCR_ROTATE_PAGES_THRESHOLD
        )
        self.max_image_pixel = (
            app_config.max_image_pixels or settings.OCR_MAX_IMAGE_PIXELS
        )
        self.color_conversion_strategy = (
            app_config.color_conversion_strategy
            or settings.OCR_COLOR_CONVERSION_STRATEGY
        )

        user_args = None
        if app_config.user_args:
            user_args = app_config.user_args
        elif settings.OCR_USER_ARGS is not None:  # pragma: no cover
            try:
                user_args = json.loads(settings.OCR_USER_ARGS)
            except json.JSONDecodeError:
                user_args = {}
        self.user_args = user_args

        self.sharpen = (
            app_config.ocr_sharpen
            if app_config.ocr_sharpen is not None
            else settings.OCR_SHARPEN
        )
        self.custom_alignment = (
            app_config.ocr_custom_alignment
            if app_config.ocr_custom_alignment is not None
            else settings.OCR_CUSTOM_ALIGNMENT
        )
        self.sharpen_radius = (
            app_config.ocr_sharpen_radius or settings.OCR_SHARPEN_RADIUS
        )
        self.sharpen_percent = (
            app_config.ocr_sharpen_percent or settings.OCR_SHARPEN_PERCENT
        )
        self.sharpen_threshold = (
            app_config.ocr_sharpen_threshold or settings.OCR_SHARPEN_THRESHOLD
        )
        self.alignment_threshold = (
            app_config.ocr_alignment_threshold or settings.OCR_ALIGNMENT_THRESHOLD
        )


@dataclasses.dataclass
class BarcodeConfig(BaseConfig):
    """
    Barcodes settings
    """

    barcodes_enabled: bool = dataclasses.field(init=False)
    barcode_enable_tiff_support: bool = dataclasses.field(init=False)
    barcode_string: str = dataclasses.field(init=False)
    barcode_retain_split_pages: bool = dataclasses.field(init=False)
    barcode_enable_asn: bool = dataclasses.field(init=False)
    barcode_asn_prefix: str = dataclasses.field(init=False)
    barcode_upscale: float = dataclasses.field(init=False)
    barcode_dpi: int = dataclasses.field(init=False)
    barcode_max_pages: int = dataclasses.field(init=False)
    barcode_enable_tag: bool = dataclasses.field(init=False)
    barcode_tag_mapping: dict[str, str] = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        app_config = self._get_config_instance()

        self.barcodes_enabled = (
            app_config.barcodes_enabled or settings.CONSUMER_ENABLE_BARCODES
        )
        self.barcode_enable_tiff_support = (
            app_config.barcode_enable_tiff_support
            or settings.CONSUMER_BARCODE_TIFF_SUPPORT
        )
        self.barcode_string = (
            app_config.barcode_string or settings.CONSUMER_BARCODE_STRING
        )
        self.barcode_retain_split_pages = (
            app_config.barcode_retain_split_pages
            or settings.CONSUMER_BARCODE_RETAIN_SPLIT_PAGES
        )
        self.barcode_enable_asn = (
            app_config.barcode_enable_asn or settings.CONSUMER_ENABLE_ASN_BARCODE
        )
        self.barcode_asn_prefix = (
            app_config.barcode_asn_prefix or settings.CONSUMER_ASN_BARCODE_PREFIX
        )
        self.barcode_upscale = (
            app_config.barcode_upscale or settings.CONSUMER_BARCODE_UPSCALE
        )
        self.barcode_dpi = app_config.barcode_dpi or settings.CONSUMER_BARCODE_DPI
        self.barcode_max_pages = (
            app_config.barcode_max_pages or settings.CONSUMER_BARCODE_MAX_PAGES
        )
        self.barcode_enable_tag = (
            app_config.barcode_enable_tag or settings.CONSUMER_ENABLE_TAG_BARCODE
        )
        self.barcode_tag_mapping = (
            app_config.barcode_tag_mapping or settings.CONSUMER_TAG_BARCODE_MAPPING
        )


@dataclasses.dataclass
class GeneralConfig(BaseConfig):
    """
    General application settings that require global scope
    """

    app_title: str = dataclasses.field(init=False)
    app_logo: str = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        app_config = self._get_config_instance()

        self.app_title = app_config.app_title or None
        self.app_logo = app_config.app_logo.url if app_config.app_logo else None


@dataclasses.dataclass
class AIConfig(BaseConfig):
    """
    AI related settings that require global scope
    """

    ai_enabled: bool = dataclasses.field(init=False)
    llm_embedding_backend: str = dataclasses.field(init=False)
    llm_embedding_endpoint: str = dataclasses.field(init=False)
    llm_embedding_api_key: str = dataclasses.field(init=False)
    llm_backend: str = dataclasses.field(init=False)
    llm_model: str = dataclasses.field(init=False)
    llm_api_key: str = dataclasses.field(init=False)
    llm_endpoint: str = dataclasses.field(init=False)
    llm_timeout: int = dataclasses.field(init=False)
    enable_auto_ai_enhancement: bool = dataclasses.field(init=False)
    confidence_threshold: float = dataclasses.field(init=False)
    auto_create_threshold: float = dataclasses.field(init=False)
    force_ai_update: bool = dataclasses.field(init=False)
    rollback_enabled: bool = dataclasses.field(init=False)
    rollback_retention_days: int = dataclasses.field(init=False)
    audit_log_level: str = dataclasses.field(init=False)
    rate_limit_requests: int = dataclasses.field(init=False)
    rate_limit_window: int = dataclasses.field(init=False)
    graceful_degradation: bool = dataclasses.field(init=False)

    # Vector store settings
    vector_store_backend: str = dataclasses.field(init=False)
    vector_store_name: str | None = dataclasses.field(init=False)
    vector_store_host: str | None = dataclasses.field(init=False)
    vector_store_port: int | None = dataclasses.field(init=False)
    vector_store_user: str | None = dataclasses.field(init=False)
    vector_store_pass: str | None = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        app_config = self._get_config_instance()

        self.ai_enabled = app_config.ai_enabled or settings.AI_ENABLED
        self.llm_embedding_backend = (
            app_config.llm_embedding_backend
            if app_config.llm_embedding_backend
            else getattr(settings, "LLM_EMBEDDING_BACKEND", None)
        )
        self.llm_embedding_model = (
            app_config.llm_embedding_model
            if app_config.llm_embedding_model is not None
            else getattr(settings, "LLM_EMBEDDING_MODEL", None)
        )
        self.llm_embedding_endpoint = getattr(
            app_config,
            "llm_embedding_endpoint",
            None,
        ) or getattr(settings, "LLM_EMBEDDING_ENDPOINT", None)
        self.llm_embedding_api_key = getattr(
            app_config,
            "llm_embedding_api_key",
            None,
        ) or getattr(settings, "LLM_EMBEDDING_API_KEY", None)

        self.llm_backend = (
            app_config.llm_backend
            if app_config.llm_backend is not None
            else getattr(settings, "LLM_BACKEND", None)
        )
        self.llm_model = (
            app_config.llm_model
            if app_config.llm_model is not None
            else getattr(settings, "LLM_MODEL", None)
        )
        self.llm_api_key = (
            app_config.llm_api_key
            if app_config.llm_api_key is not None
            else getattr(settings, "LLM_API_KEY", None)
        )
        self.llm_endpoint = (
            app_config.llm_endpoint
            if app_config.llm_endpoint is not None
            else getattr(settings, "LLM_ENDPOINT", None)
        )
        self.llm_timeout = (
            app_config.llm_timeout
            if app_config.llm_timeout is not None
            else getattr(settings, "LLM_TIMEOUT", None)
        )

        # Auto-enhancement settings
        self.enable_auto_ai_enhancement = getattr(
            app_config,
            "enable_auto_ai_enhancement",
            None,
        ) or getattr(settings, "PAPERLESS_AI_AUTO_ASSIGN", False)
        self.confidence_threshold = getattr(
            app_config,
            "confidence_threshold",
            None,
        ) or getattr(settings, "PAPERLESS_AI_CONFIDENCE_THRESHOLD", 0.7)
        self.auto_create_threshold = getattr(
            app_config,
            "auto_create_threshold",
            None,
        ) or getattr(settings, "PAPERLESS_AI_AUTO_CREATE_THRESHOLD", 0.8)
        self.force_ai_update = getattr(app_config, "force_ai_update", None) or getattr(
            settings,
            "PAPERLESS_AI_FORCE_UPDATE",
            False,
        )

        # Safety and configuration settings
        self.rollback_enabled = getattr(
            app_config,
            "rollback_enabled",
            None,
        ) or getattr(
            settings,
            "ROLLBACK_ENABLED",
            True,
        )
        self.rollback_retention_days = getattr(
            app_config,
            "rollback_retention_days",
            None,
        ) or getattr(
            settings,
            "ROLLBACK_RETENTION_DAYS",
            30,
        )
        self.audit_log_level = getattr(app_config, "audit_log_level", None) or getattr(
            settings,
            "AUDIT_LOG_LEVEL",
            "INFO",
        )
        self.rate_limit_requests = getattr(
            app_config,
            "rate_limit_requests",
            None,
        ) or getattr(
            settings,
            "RATE_LIMIT_REQUESTS",
            100,
        )
        self.rate_limit_window = getattr(
            app_config,
            "rate_limit_window",
            None,
        ) or getattr(
            settings,
            "RATE_LIMIT_WINDOW",
            60,
        )
        self.graceful_degradation = getattr(
            app_config,
            "graceful_degradation",
            None,
        ) or getattr(
            settings,
            "GRACEFUL_DEGRADATION",
            True,
        )

        # Vector store settings
        self.vector_store_backend = (
            app_config.vector_store_backend
            if app_config.vector_store_backend
            else getattr(settings, "PAPERLESS_AI_VECTOR_STORE", "auto")
        )
        self.vector_store_name = (
            app_config.vector_store_name
            if app_config.vector_store_name
            else getattr(settings, "PAPERLESS_AI_VECTOR_DB_NAME", None)
        )
        self.vector_store_host = (
            app_config.vector_store_host
            if app_config.vector_store_host
            else getattr(settings, "PAPERLESS_AI_VECTOR_HOST", None)
        )
        self.vector_store_port = (
            app_config.vector_store_port
            if app_config.vector_store_port
            else getattr(settings, "PAPERLESS_AI_VECTOR_PORT", None)
        )
        self.vector_store_user = (
            app_config.vector_store_user
            if app_config.vector_store_user
            else getattr(settings, "PAPERLESS_AI_VECTOR_USER", None)
        )
        self.vector_store_pass = (
            app_config.vector_store_pass
            if app_config.vector_store_pass
            else getattr(settings, "PAPERLESS_AI_VECTOR_PASS", None)
        )

        # Validate thresholds
        if not (0.0 <= self.confidence_threshold <= 1.0):
            raise ValueError("Confidence threshold must be between 0.0 and 1.0")
        if not (0.0 <= self.auto_create_threshold <= 1.0):
            raise ValueError("Auto-create threshold must be between 0.0 and 1.0")
        if self.rollback_retention_days <= 0:
            raise ValueError("Rollback retention days must be greater than 0")
        if self.rate_limit_requests <= 0:
            raise ValueError("Rate limit requests must be greater than 0")
        if self.rate_limit_window <= 0:
            raise ValueError("Rate limit window must be greater than 0")

    @property
    def llm_index_enabled(self) -> bool:
        return bool(self.ai_enabled and self.llm_embedding_backend)


@dataclasses.dataclass
class DoclingConfig(BaseConfig):
    """
    Specific settings for the Docling OCR parser
    """

    force_ocr: bool = dataclasses.field(init=False)
    language: str = dataclasses.field(init=False)
    endpoint: str = dataclasses.field(init=False)
    timeout: int = dataclasses.field(init=False)
    sharpen: bool = dataclasses.field(init=False)
    custom_alignment: bool = dataclasses.field(init=False)
    sharpen_radius: float = dataclasses.field(init=False)
    sharpen_percent: float = dataclasses.field(init=False)
    sharpen_threshold: float = dataclasses.field(init=False)
    alignment_threshold: float = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        app_config = self._get_config_instance()

        self.force_ocr = (
            app_config.docling_force_ocr
            if app_config.docling_force_ocr is not None
            else settings.DOCLING_FORCE_OCR
        )
        self.language = app_config.docling_language or settings.DOCLING_LANGUAGE
        self.endpoint = app_config.docling_endpoint or settings.DOCLING_ENDPOINT
        self.timeout = app_config.docling_timeout or settings.DOCLING_TIMEOUT
        self.sharpen = (
            app_config.ocr_sharpen
            if app_config.ocr_sharpen is not None
            else settings.OCR_SHARPEN
        )
        self.custom_alignment = (
            app_config.ocr_custom_alignment
            if app_config.ocr_custom_alignment is not None
            else settings.OCR_CUSTOM_ALIGNMENT
        )
        self.sharpen_radius = (
            app_config.ocr_sharpen_radius or settings.OCR_SHARPEN_RADIUS
        )
        self.sharpen_percent = (
            app_config.ocr_sharpen_percent or settings.OCR_SHARPEN_PERCENT
        )
        self.sharpen_threshold = (
            app_config.ocr_sharpen_threshold or settings.OCR_SHARPEN_THRESHOLD
        )
        self.alignment_threshold = (
            app_config.ocr_alignment_threshold or settings.OCR_ALIGNMENT_THRESHOLD
        )


@dataclasses.dataclass
class OllamaConfig(BaseConfig):
    """
    Specific settings for the Ollama OCR parser
    """

    endpoint: str = dataclasses.field(init=False)
    model: str = dataclasses.field(init=False)
    prompt_template: str = dataclasses.field(init=False)
    timeout: int = dataclasses.field(init=False)
    sharpen: bool = dataclasses.field(init=False)
    custom_alignment: bool = dataclasses.field(init=False)
    sharpen_radius: float = dataclasses.field(init=False)
    sharpen_percent: float = dataclasses.field(init=False)
    sharpen_threshold: float = dataclasses.field(init=False)
    alignment_threshold: float = dataclasses.field(init=False)
    ollama_ocr_debug_thumbnail: bool = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        app_config = self._get_config_instance()

        self.endpoint = app_config.ollama_endpoint or settings.OLLAMA_ENDPOINT
        self.model = app_config.ollama_model or settings.OLLAMA_MODEL
        self.prompt_template = (
            app_config.ollama_prompt_template or settings.OLLAMA_PROMPT_TEMPLATE
        )
        self.timeout = app_config.ollama_timeout or settings.OLLAMA_TIMEOUT
        self.ollama_ocr_debug_thumbnail = (
            getattr(app_config, "ollama_ocr_debug_thumbnail", None)
            if hasattr(app_config, "ollama_ocr_debug_thumbnail")
            else settings.OLLAMA_OCR_DEBUG_THUMBNAIL
        )
        self.sharpen = (
            app_config.ocr_sharpen
            if app_config.ocr_sharpen is not None
            else settings.OCR_SHARPEN
        )
        self.custom_alignment = (
            app_config.ocr_custom_alignment
            if app_config.ocr_custom_alignment is not None
            else settings.OCR_CUSTOM_ALIGNMENT
        )
        self.sharpen_radius = (
            app_config.ocr_sharpen_radius or settings.OCR_SHARPEN_RADIUS
        )
        self.sharpen_percent = (
            app_config.ocr_sharpen_percent or settings.OCR_SHARPEN_PERCENT
        )
        self.sharpen_threshold = (
            app_config.ocr_sharpen_threshold or settings.OCR_SHARPEN_THRESHOLD
        )
        self.alignment_threshold = (
            app_config.ocr_alignment_threshold or settings.OCR_ALIGNMENT_THRESHOLD
        )

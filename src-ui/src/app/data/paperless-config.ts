import { ObjectWithId } from './object-with-id'

// see /src/paperless/models.py

export enum OutputTypeConfig {
  PDF = 'pdf',
  PDF_A = 'pdfa',
  PDF_A1 = 'pdfa-1',
  PDF_A2 = 'pdfa-2',
  PDF_A3 = 'pdfa-3',
}

export enum ModeConfig {
  SKIP = 'skip',
  REDO = 'redo',
  FORCE = 'force',
  SKIP_NO_ARCHIVE = 'skip_noarchive',
}

export enum ArchiveFileConfig {
  NEVER = 'never',
  WITH_TEXT = 'with_text',
  ALWAYS = 'always',
}

export enum CleanConfig {
  CLEAN = 'clean',
  FINAL = 'clean-final',
  NONE = 'none',
}

export enum ColorConvertConfig {
  UNCHANGED = 'LeaveColorUnchanged',
  RGB = 'RGB',
  INDEPENDENT = 'UseDeviceIndependentColor',
  GRAY = 'Gray',
  CMYK = 'CMYK',
}

export enum ConfigOptionType {
  String = 'string',
  Number = 'number',
  Select = 'select',
  Boolean = 'boolean',
  JSON = 'json',
  File = 'file',
  Textarea = 'textarea',
  Password = 'password',
  Header = 'header',
}

export const ConfigCategory = {
  General: $localize`General Settings`,
  OCR: $localize`OCR Settings`,
  Barcode: $localize`Barcode Settings`,
  AI: $localize`AI Settings`,
}

export const LLMEmbeddingBackendConfig = {
  OPENAI: 'openai',
  HUGGINGFACE: 'huggingface',
  OLLAMA: 'ollama',
}

export const LLMBackendConfig = {
  OPENAI: 'openai',
  OLLAMA: 'ollama',
}

export const VectorStoreBackendConfig = {
  AUTO: 'auto',
  FAISS: 'faiss',
  POSTGRES: 'postgres',
}

export interface ConfigOption {
  key: string
  title: string
  type: ConfigOptionType
  choices?: Array<{ id: string; name: string }>
  config_key?: string
  category: string
  note?: string
}

function mapToItems(enumObj: Object): Array<{ id: string; name: string }> {
  return Object.keys(enumObj).map((key) => {
    return {
      id: enumObj[key],
      name: enumObj[key],
    }
  })
}

export const PaperlessConfigOptions: ConfigOption[] = [
  {
    key: 'output_type',
    title: $localize`Output Type`,
    type: ConfigOptionType.Select,
    choices: mapToItems(OutputTypeConfig),
    config_key: 'PAPERLESS_OCR_OUTPUT_TYPE',
    category: ConfigCategory.OCR,
  },
  {
    key: 'ocr_engine',
    title: $localize`OCR Engine`,
    type: ConfigOptionType.Select,
    choices: [
      { id: 'tesseract', name: 'Tesseract' },
      { id: 'docling', name: 'Docling (Local)' },
      { id: 'docling_server', name: 'Docling Server' },
      { id: 'ollama', name: 'Ollama' },
    ],
    config_key: 'PAPERLESS_OCR_ENGINE',
    category: ConfigCategory.OCR,
  },
  {
    key: 'ocr_image_enhancement_header',
    title: $localize`Image Enhancements`,
    type: ConfigOptionType.Header,
    category: ConfigCategory.OCR,
  },
  {
    key: 'ocr_sharpen',
    title: $localize`Sharpen Images`,
    type: ConfigOptionType.Boolean,
    config_key: 'PAPERLESS_OCR_SHARPEN',
    category: ConfigCategory.OCR,
  },
  {
    key: 'ocr_sharpen_radius',
    title: $localize`Sharpen Radius`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_OCR_SHARPEN_RADIUS',
    category: ConfigCategory.OCR,
  },
  {
    key: 'ocr_sharpen_percent',
    title: $localize`Sharpen Percent`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_OCR_SHARPEN_PERCENT',
    category: ConfigCategory.OCR,
  },
  {
    key: 'ocr_sharpen_threshold',
    title: $localize`Sharpen Threshold`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_OCR_SHARPEN_THRESHOLD',
    category: ConfigCategory.OCR,
  },
  {
    key: 'ocr_custom_alignment',
    title: $localize`Custom Alignment`,
    type: ConfigOptionType.Boolean,
    config_key: 'PAPERLESS_OCR_CUSTOM_ALIGNMENT',
    category: ConfigCategory.OCR,
  },
  {
    key: 'ocr_alignment_threshold',
    title: $localize`Alignment Threshold`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_OCR_ALIGNMENT_THRESHOLD',
    category: ConfigCategory.OCR,
  },
  {
    key: 'docling_header',
    title: $localize`Docling Settings`,
    type: ConfigOptionType.Header,
    category: ConfigCategory.OCR,
  },
  {
    key: 'docling_endpoint',
    title: $localize`Docling Endpoint`,
    type: ConfigOptionType.String,
    config_key: 'PAPERLESS_DOCLING_ENDPOINT',
    category: ConfigCategory.OCR,
  },
  {
    key: 'docling_language',
    title: $localize`Docling Language`,
    type: ConfigOptionType.String,
    config_key: 'PAPERLESS_DOCLING_LANGUAGE',
    category: ConfigCategory.OCR,
  },
  {
    key: 'docling_timeout',
    title: $localize`Docling Timeout`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_DOCLING_TIMEOUT',
    category: ConfigCategory.OCR,
  },
  {
    key: 'docling_force_ocr',
    title: $localize`Force OCR`,
    type: ConfigOptionType.Boolean,
    config_key: 'PAPERLESS_DOCLING_FORCE_OCR',
    category: ConfigCategory.OCR,
  },
  {
    key: 'ollama_header',
    title: $localize`Ollama Settings`,
    type: ConfigOptionType.Header,
    category: ConfigCategory.OCR,
  },
  {
    key: 'ollama_endpoint',
    title: $localize`Ollama Endpoint`,
    type: ConfigOptionType.String,
    config_key: 'PAPERLESS_OLLAMA_ENDPOINT',
    category: ConfigCategory.OCR,
  },
  {
    key: 'ollama_model',
    title: $localize`Ollama Model`,
    type: ConfigOptionType.Select,
    choices: [],
    config_key: 'PAPERLESS_OLLAMA_MODEL',
    category: ConfigCategory.OCR,
  },
  {
    key: 'ollama_timeout',
    title: $localize`Ollama Timeout`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_OLLAMA_TIMEOUT',
    category: ConfigCategory.OCR,
  },
  {
    key: 'ollama_prompt_template',
    title: $localize`Ollama Prompt Template`,
    type: ConfigOptionType.String,
    config_key: 'PAPERLESS_OLLAMA_PROMPT_TEMPLATE',
    category: ConfigCategory.OCR,
  },
  {
    key: 'ollama_ocr_debug_thumbnail',
    title: $localize`Debug Thumbnails`,
    type: ConfigOptionType.Boolean,
    config_key: 'PAPERLESS_OLLAMA_OCR_DEBUG_THUMBNAIL',
    category: ConfigCategory.OCR,
  },
  {
    key: 'tesseract_header',
    title: $localize`Tesseract Settings`,
    type: ConfigOptionType.Header,
    category: ConfigCategory.OCR,
  },
  {
    key: 'language',
    title: $localize`Language`,
    type: ConfigOptionType.String,
    config_key: 'PAPERLESS_OCR_LANGUAGE',
    category: ConfigCategory.OCR,
  },
  {
    key: 'pages',
    title: $localize`Pages`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_OCR_PAGES',
    category: ConfigCategory.OCR,
  },
  {
    key: 'mode',
    title: $localize`Mode`,
    type: ConfigOptionType.Select,
    choices: mapToItems(ModeConfig),
    config_key: 'PAPERLESS_OCR_MODE',
    category: ConfigCategory.OCR,
  },
  {
    key: 'skip_archive_file',
    title: $localize`Skip Archive File`,
    type: ConfigOptionType.Select,
    choices: mapToItems(ArchiveFileConfig),
    config_key: 'PAPERLESS_OCR_SKIP_ARCHIVE_FILE',
    category: ConfigCategory.OCR,
  },
  {
    key: 'image_dpi',
    title: $localize`Image DPI`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_OCR_IMAGE_DPI',
    category: ConfigCategory.OCR,
  },
  {
    key: 'unpaper_clean',
    title: $localize`Clean`,
    type: ConfigOptionType.Select,
    choices: mapToItems(CleanConfig),
    config_key: 'PAPERLESS_OCR_CLEAN',
    category: ConfigCategory.OCR,
  },
  {
    key: 'deskew',
    title: $localize`Deskew`,
    type: ConfigOptionType.Boolean,
    config_key: 'PAPERLESS_OCR_DESKEW',
    category: ConfigCategory.OCR,
  },
  {
    key: 'rotate_pages',
    title: $localize`Rotate Pages`,
    type: ConfigOptionType.Boolean,
    config_key: 'PAPERLESS_OCR_ROTATE_PAGES',
    category: ConfigCategory.OCR,
  },
  {
    key: 'rotate_pages_threshold',
    title: $localize`Rotate Pages Threshold`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_OCR_ROTATE_PAGES_THRESHOLD',
    category: ConfigCategory.OCR,
  },
  {
    key: 'max_image_pixels',
    title: $localize`Max Image Pixels`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_OCR_MAX_IMAGE_PIXELS',
    category: ConfigCategory.OCR,
  },
  {
    key: 'color_conversion_strategy',
    title: $localize`Color Conversion Strategy`,
    type: ConfigOptionType.Select,
    choices: mapToItems(ColorConvertConfig),
    config_key: 'PAPERLESS_OCR_COLOR_CONVERSION_STRATEGY',
    category: ConfigCategory.OCR,
  },
  {
    key: 'user_args',
    title: $localize`OCR Arguments`,
    type: ConfigOptionType.JSON,
    config_key: 'PAPERLESS_OCR_USER_ARGS',
    category: ConfigCategory.OCR,
  },
  {
    key: 'app_logo',
    title: $localize`Application Logo`,
    type: ConfigOptionType.File,
    config_key: 'PAPERLESS_APP_LOGO',
    category: ConfigCategory.General,
  },
  {
    key: 'app_title',
    title: $localize`Application Title`,
    type: ConfigOptionType.String,
    config_key: 'PAPERLESS_APP_TITLE',
    category: ConfigCategory.General,
  },
  {
    key: 'barcodes_enabled',
    title: $localize`Enable Barcodes`,
    type: ConfigOptionType.Boolean,
    config_key: 'PAPERLESS_CONSUMER_ENABLE_BARCODES',
    category: ConfigCategory.Barcode,
  },
  {
    key: 'barcode_enable_tiff_support',
    title: $localize`Enable TIFF Support`,
    type: ConfigOptionType.Boolean,
    config_key: 'PAPERLESS_CONSUMER_BARCODE_TIFF_SUPPORT',
    category: ConfigCategory.Barcode,
  },
  {
    key: 'barcode_string',
    title: $localize`Barcode String`,
    type: ConfigOptionType.String,
    config_key: 'PAPERLESS_CONSUMER_BARCODE_STRING',
    category: ConfigCategory.Barcode,
  },
  {
    key: 'barcode_retain_split_pages',
    title: $localize`Retain Split Pages`,
    type: ConfigOptionType.Boolean,
    config_key: 'PAPERLESS_CONSUMER_BARCODE_RETAIN_SPLIT_PAGES',
    category: ConfigCategory.Barcode,
  },
  {
    key: 'barcode_enable_asn',
    title: $localize`Enable ASN`,
    type: ConfigOptionType.Boolean,
    config_key: 'PAPERLESS_CONSUMER_ENABLE_ASN_BARCODE',
    category: ConfigCategory.Barcode,
  },
  {
    key: 'barcode_asn_prefix',
    title: $localize`ASN Prefix`,
    type: ConfigOptionType.String,
    config_key: 'PAPERLESS_CONSUMER_ASN_BARCODE_PREFIX',
    category: ConfigCategory.Barcode,
  },
  {
    key: 'barcode_upscale',
    title: $localize`Upscale`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_CONSUMER_BARCODE_UPSCALE',
    category: ConfigCategory.Barcode,
  },
  {
    key: 'barcode_dpi',
    title: $localize`DPI`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_CONSUMER_BARCODE_DPI',
    category: ConfigCategory.Barcode,
  },
  {
    key: 'barcode_max_pages',
    title: $localize`Max Pages`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_CONSUMER_BARCODE_MAX_PAGES',
    category: ConfigCategory.Barcode,
  },
  {
    key: 'barcode_enable_tag',
    title: $localize`Enable Tag Detection`,
    type: ConfigOptionType.Boolean,
    config_key: 'PAPERLESS_CONSUMER_ENABLE_TAG_BARCODE',
    category: ConfigCategory.Barcode,
  },
  {
    key: 'barcode_tag_mapping',
    title: $localize`Tag Mapping`,
    type: ConfigOptionType.JSON,
    config_key: 'PAPERLESS_CONSUMER_TAG_BARCODE_MAPPING',
    category: ConfigCategory.Barcode,
  },
  // AI Settings - Global Enable Switch (no header)
  {
    key: 'barcode_tag_split',
    title: $localize`Split on Tag Barcodes`,
    type: ConfigOptionType.Boolean,
    config_key: 'PAPERLESS_CONSUMER_TAG_BARCODE_SPLIT',
    category: ConfigCategory.Barcode,
  },
  {
    key: 'ai_enabled',
    title: $localize`AI Enabled`,
    type: ConfigOptionType.Boolean,
    config_key: 'PAPERLESS_AI_ENABLED',
    category: ConfigCategory.AI,
    note: $localize`Consider privacy implications when enabling AI features, especially if using a remote model.`,
  },
  // LLM Configuration
  {
    key: 'ai_llm_header',
    title: $localize`LLM Configuration`,
    type: ConfigOptionType.Header,
    category: ConfigCategory.AI,
  },
  {
    key: 'ai_system_prompt',
    title: $localize`System Prompt`,
    type: ConfigOptionType.Textarea,
    config_key: 'PAPERLESS_AI_SYSTEM_PROMPT',
    category: ConfigCategory.AI,
  },
  {
    key: 'llm_backend',
    title: $localize`LLM Backend`,
    type: ConfigOptionType.Select,
    choices: mapToItems(LLMBackendConfig),
    config_key: 'PAPERLESS_AI_LLM_BACKEND',
    category: ConfigCategory.AI,
  },
  {
    key: 'llm_endpoint',
    title: $localize`LLM Endpoint`,
    type: ConfigOptionType.String,
    config_key: 'PAPERLESS_AI_LLM_ENDPOINT',
    category: ConfigCategory.AI,
  },
  {
    key: 'llm_api_key',
    title: $localize`LLM API Key`,
    type: ConfigOptionType.Password,
    config_key: 'PAPERLESS_AI_LLM_API_KEY',
    category: ConfigCategory.AI,
  },
  {
    key: 'llm_model',
    title: $localize`LLM Model`,
    type: ConfigOptionType.Select,
    choices: [],
    config_key: 'PAPERLESS_AI_LLM_MODEL',
    category: ConfigCategory.AI,
  },
  {
    key: 'llm_timeout',
    title: $localize`LLM Timeout (seconds)`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_AI_LLM_TIMEOUT',
    category: ConfigCategory.AI,
  },
  // Embedding Configuration
  {
    key: 'ai_embedding_header',
    title: $localize`Embedding Configuration`,
    type: ConfigOptionType.Header,
    category: ConfigCategory.AI,
  },
  {
    key: 'llm_embedding_backend',
    title: $localize`Embedding Backend`,
    type: ConfigOptionType.Select,
    choices: mapToItems(LLMEmbeddingBackendConfig),
    config_key: 'PAPERLESS_AI_LLM_EMBEDDING_BACKEND',
    category: ConfigCategory.AI,
  },
  {
    key: 'llm_embedding_endpoint',
    title: $localize`Embedding Endpoint`,
    type: ConfigOptionType.String,
    config_key: 'PAPERLESS_AI_LLM_EMBEDDING_ENDPOINT',
    category: ConfigCategory.AI,
  },
  {
    key: 'llm_embedding_api_key',
    title: $localize`Embedding API Key`,
    type: ConfigOptionType.Password,
    config_key: 'PAPERLESS_AI_LLM_EMBEDDING_API_KEY',
    category: ConfigCategory.AI,
  },
  {
    key: 'llm_embedding_model',
    title: $localize`Embedding Model`,
    type: ConfigOptionType.Select,
    choices: [],
    config_key: 'PAPERLESS_AI_LLM_EMBEDDING_MODEL',
    category: ConfigCategory.AI,
  },
  // Auto-Enhancement
  {
    key: 'ai_autotag_header',
    title: $localize`Auto-Enhancement`,
    type: ConfigOptionType.Header,
    category: ConfigCategory.AI,
  },
  {
    key: 'enable_auto_ai_enhancement',
    title: $localize`Enable Auto Enhancement`,
    type: ConfigOptionType.Boolean,
    config_key: 'PAPERLESS_AI_AUTO_ASSIGN',
    category: ConfigCategory.AI,
  },
  {
    key: 'confidence_threshold',
    title: $localize`Confidence Threshold`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_AI_CONFIDENCE_THRESHOLD',
    category: ConfigCategory.AI,
  },
  {
    key: 'auto_create_threshold',
    title: $localize`Auto Create Threshold`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_AI_AUTO_CREATE_THRESHOLD',
    category: ConfigCategory.AI,
  },
  {
    key: 'force_ai_update',
    title: $localize`Force AI Update`,
    type: ConfigOptionType.Boolean,
    config_key: 'PAPERLESS_AI_FORCE_UPDATE',
    category: ConfigCategory.AI,
  },
  // Safety & Operations
  {
    key: 'ai_safety_header',
    title: $localize`Safety & Operations`,
    type: ConfigOptionType.Header,
    category: ConfigCategory.AI,
  },
  {
    key: 'rollback_enabled',
    title: $localize`Enable Rollback`,
    type: ConfigOptionType.Boolean,
    config_key: 'ROLLBACK_ENABLED',
    category: ConfigCategory.AI,
  },
  {
    key: 'rollback_retention_days',
    title: $localize`Rollback Retention (Days)`,
    type: ConfigOptionType.Number,
    config_key: 'ROLLBACK_RETENTION_DAYS',
    category: ConfigCategory.AI,
  },
  {
    key: 'graceful_degradation',
    title: $localize`Graceful Degradation`,
    type: ConfigOptionType.Boolean,
    config_key: 'GRACEFUL_DEGRADATION',
    category: ConfigCategory.AI,
  },
  {
    key: 'rate_limit_requests',
    title: $localize`Rate Limit (Requests)`,
    type: ConfigOptionType.Number,
    config_key: 'RATE_LIMIT_REQUESTS',
    category: ConfigCategory.AI,
  },
  {
    key: 'rate_limit_window',
    title: $localize`Rate Limit Window (Seconds)`,
    type: ConfigOptionType.Number,
    config_key: 'RATE_LIMIT_WINDOW',
    category: ConfigCategory.AI,
  },
  {
    key: 'audit_log_level',
    title: $localize`Audit Log Level`,
    type: ConfigOptionType.String,
    config_key: 'AUDIT_LOG_LEVEL',
    category: ConfigCategory.AI,
  },
  // Vector Store Configuration
  {
    key: 'ai_vector_header',
    title: $localize`Vector Store Configuration`,
    type: ConfigOptionType.Header,
    category: ConfigCategory.AI,
  },
  {
    key: 'vector_store_backend',
    title: $localize`Vector Store Backend`,
    type: ConfigOptionType.Select,
    choices: [
      { id: 'auto', name: `Automatic (suggested)` },
      { id: 'faiss', name: `FAISS (local files)` },
      { id: 'postgres', name: `Postgres (PGVector)` },
    ],
    config_key: 'PAPERLESS_AI_VECTOR_STORE',
    category: ConfigCategory.AI,
  },
  {
    key: 'vector_store_name',
    title: $localize`Vector Database Name`,
    type: ConfigOptionType.String,
    config_key: 'PAPERLESS_AI_VECTOR_DB_NAME',
    category: ConfigCategory.AI,
    note: $localize`Defaults to <main-db-name>-vector`,
  },
  {
    key: 'vector_store_host',
    title: $localize`Vector Database Host`,
    type: ConfigOptionType.String,
    config_key: 'PAPERLESS_AI_VECTOR_HOST',
    category: ConfigCategory.AI,
  },
  {
    key: 'vector_store_port',
    title: $localize`Vector Database Port`,
    type: ConfigOptionType.Number,
    config_key: 'PAPERLESS_AI_VECTOR_PORT',
    category: ConfigCategory.AI,
  },
  {
    key: 'vector_store_user',
    title: $localize`Vector Database User`,
    type: ConfigOptionType.String,
    config_key: 'PAPERLESS_AI_VECTOR_USER',
    category: ConfigCategory.AI,
  },
  {
    key: 'vector_store_pass',
    title: $localize`Vector Database Password`,
    type: ConfigOptionType.Password,
    config_key: 'PAPERLESS_AI_VECTOR_PASS',
    category: ConfigCategory.AI,
  },
]

export interface PaperlessConfig extends ObjectWithId {
  output_type: OutputTypeConfig
  pages: number
  language: string
  mode: ModeConfig
  skip_archive_file: ArchiveFileConfig
  image_dpi: number
  unpaper_clean: CleanConfig
  deskew: boolean
  rotate_pages: boolean
  rotate_pages_threshold: number
  max_image_pixels: number
  color_conversion_strategy: ColorConvertConfig
  user_args: object
  app_logo: string
  app_title: string
  barcodes_enabled: boolean
  barcode_enable_tiff_support: boolean
  barcode_string: string
  barcode_retain_split_pages: boolean
  barcode_enable_asn: boolean
  barcode_asn_prefix: string
  barcode_upscale: number
  barcode_dpi: number
  barcode_max_pages: number
  barcode_enable_tag: boolean
  barcode_tag_mapping: object
  barcode_tag_split: boolean
  ai_enabled: boolean
  ai_system_prompt: string
  llm_embedding_backend: string
  llm_embedding_endpoint: string
  llm_embedding_api_key: string
  llm_embedding_model: string
  llm_backend: string
  llm_model: string
  llm_api_key: string
  llm_endpoint: string
  llm_timeout: number
  ocr_engine: string
  ocr_sharpen: boolean
  ocr_sharpen_radius: number
  ocr_sharpen_percent: number
  ocr_sharpen_threshold: number
  ocr_custom_alignment: boolean
  ocr_alignment_threshold: number
  docling_endpoint: string
  docling_language: string
  docling_timeout: number
  docling_force_ocr: boolean
  ollama_endpoint: string
  ollama_model: string
  ollama_timeout: number
  ollama_prompt_template: string
  ollama_ocr_debug_thumbnail: boolean
  enable_auto_ai_enhancement: boolean
  confidence_threshold: number
  auto_create_threshold: number
  rollback_enabled: boolean
  rollback_retention_days: number
  audit_log_level: string
  rate_limit_requests: number
  rate_limit_window: number
  graceful_degradation: boolean
  force_ai_update: boolean
  vector_store_backend: string
  vector_store_name: string
  vector_store_host: string
  vector_store_port: number
  vector_store_user: string
  vector_store_pass: string
}

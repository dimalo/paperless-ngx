import { AsyncPipe } from '@angular/common'
import { HttpClient } from '@angular/common/http'
import { Component, OnDestroy, OnInit, inject } from '@angular/core'
import {
  AbstractControl,
  FormControl,
  FormGroup,
  FormsModule,
  ReactiveFormsModule,
} from '@angular/forms'
import { NgbNavModule } from '@ng-bootstrap/ng-bootstrap'
import { DirtyComponent, dirtyCheck } from '@ngneat/dirty-check-forms'
import { NgxBootstrapIconsModule } from 'ngx-bootstrap-icons'
import {
  BehaviorSubject,
  Observable,
  Subscription,
  first,
  merge,
  of,
  takeUntil,
} from 'rxjs'
import { catchError, debounceTime, switchMap } from 'rxjs/operators'
import {
  ConfigCategory,
  ConfigOption,
  ConfigOptionType,
  PaperlessConfig,
  PaperlessConfigOptions,
} from 'src/app/data/paperless-config'
import { ConfigService } from 'src/app/services/config.service'
import { LLMService } from 'src/app/services/llm.service'
import { OllamaService } from 'src/app/services/ollama.service'
import { SettingsService } from 'src/app/services/settings.service'
import { ToastService } from 'src/app/services/toast.service'
import { FileComponent } from '../../common/input/file/file.component'
import { NumberComponent } from '../../common/input/number/number.component'
import { PasswordComponent } from '../../common/input/password/password.component'
import { SelectComponent } from '../../common/input/select/select.component'
import { SwitchComponent } from '../../common/input/switch/switch.component'
import { TextComponent } from '../../common/input/text/text.component'
import { PageHeaderComponent } from '../../common/page-header/page-header.component'
import { LoadingComponentWithPermissions } from '../../loading-component/loading.component'

@Component({
  selector: 'pngx-config',
  templateUrl: './config.component.html',
  styleUrl: './config.component.scss',
  imports: [
    PageHeaderComponent,
    SelectComponent,
    SwitchComponent,
    TextComponent,
    NumberComponent,
    FileComponent,
    PasswordComponent,
    AsyncPipe,
    NgbNavModule,
    FormsModule,
    ReactiveFormsModule,
    NgxBootstrapIconsModule,
  ],
})
export class ConfigComponent
  extends LoadingComponentWithPermissions
  implements OnInit, OnDestroy, DirtyComponent
{
  private configService = inject(ConfigService)
  private toastService = inject(ToastService)
  private settingsService = inject(SettingsService)
  private ollamaService = inject(OllamaService)
  private llmService = inject(LLMService)
  private http = inject(HttpClient)

  public readonly ConfigOptionType = ConfigOptionType

  // generated dynamically
  public configForm = new FormGroup({})

  public llmTestInProgress = false

  public errors = {}

  get optionCategories(): string[] {
    return Object.values(ConfigCategory)
  }

  getCategoryOptions(category: string): ConfigOption[] {
    return PaperlessConfigOptions.filter((o) => o.category === category)
  }

  initialConfig: PaperlessConfig
  store: BehaviorSubject<any>
  storeSub: Subscription
  isDirty$: Observable<boolean>

  constructor() {
    super()
    this.configForm.addControl('id', new FormControl())
    PaperlessConfigOptions.forEach((option) => {
      if (option.type !== ConfigOptionType.Header) {
        this.configForm.addControl(option.key, new FormControl())
      }
    })
  }

  ngOnInit(): void {
    this.configService
      .getConfig()
      .pipe(takeUntil(this.unsubscribeNotifier))
      .subscribe({
        next: (config) => {
          this.loading = false
          this.initialize(config)
        },
        error: (e) => {
          this.loading = false
          this.toastService.showError($localize`Error retrieving config`, e)
        },
      })

    // validate JSON inputs
    PaperlessConfigOptions.filter(
      (o) => o.type === ConfigOptionType.JSON
    ).forEach((option) => {
      this.configForm
        .get(option.key)
        .addValidators((control: AbstractControl) => {
          if (!control.value || control.value.toString().length === 0)
            return null
          try {
            JSON.parse(control.value)
          } catch (e) {
            return [
              {
                user_args: e,
              },
            ]
          }
          return null
        })
      this.configForm.get(option.key).statusChanges.subscribe((status) => {
        this.errors[option.key] =
          status === 'INVALID' ? $localize`Invalid JSON` : null
      })
      this.configForm.get(option.key).updateValueAndValidity()
    })

    // Interactive Ollama Model Fetching
    merge(
      this.configForm.get('ollama_endpoint')?.valueChanges,
      this.configForm.get('ocr_engine')?.valueChanges
    )
      .pipe(
        takeUntil(this.unsubscribeNotifier),
        debounceTime(500),
        switchMap((): Observable<{ id: string; name: string }[]> => {
          const engine = this.configForm.get('ocr_engine')?.value
          const endpoint = this.configForm.get('ollama_endpoint')?.value
          if (engine === 'ollama' && endpoint) {
            return this.ollamaService.getModels(endpoint).pipe(
              catchError((err) => {
                this.toastService.showError(
                  $localize`Failed to fetch models`,
                  err
                )
                return of([])
              })
            )
          }
          return of([])
        })
      )
      .subscribe({
        next: (models: { id: string; name: string }[]) => {
          const modelOption = PaperlessConfigOptions.find(
            (o) => o.key === 'ollama_model'
          )
          if (modelOption) {
            modelOption.choices = models
            if (models.length > 0) {
              console.info(`Found ${models.length} Ollama models`)
            } else if (
              this.configForm.get('ocr_engine')?.value === 'ollama' &&
              this.configForm.get('ollama_endpoint')?.value
            ) {
              this.toastService.showWarning(
                $localize`No models found at this endpoint`
              )
            }
          }
        },
      })

    // AI Embedding Model Fetching
    merge(
      this.configForm.get('llm_embedding_endpoint')?.valueChanges,
      this.configForm.get('llm_endpoint')?.valueChanges,
      this.configForm.get('ollama_endpoint')?.valueChanges,
      this.configForm.get('llm_embedding_backend')?.valueChanges
    )
      .pipe(
        takeUntil(this.unsubscribeNotifier),
        debounceTime(500),
        switchMap((): Observable<{ id: string; name: string }[]> => {
          const backend = this.configForm.get('llm_embedding_backend')?.value
          const llmEmbedEndpoint = this.configForm.get(
            'llm_embedding_endpoint'
          )?.value
          const llmEndpoint = this.configForm.get('llm_endpoint')?.value
          const ocrEndpoint = this.configForm.get('ollama_endpoint')?.value
          if (backend === 'ollama') {
            const endpoint = llmEmbedEndpoint || llmEndpoint || ocrEndpoint
            if (endpoint) {
              return this.ollamaService.getModels(endpoint).pipe(
                catchError((err) => {
                  console.warn('Failed to fetch embedding models', err)
                  return of([])
                })
              )
            }
          }
          return of([])
        })
      )
      .subscribe({
        next: (models: { id: string; name: string }[]) => {
          const modelOption = PaperlessConfigOptions.find(
            (o) => o.key === 'llm_embedding_model'
          )
          if (modelOption) {
            modelOption.choices = models
          }
        },
      })
  }

  public testLLMConnection() {
    this.llmTestInProgress = true
    const endpoint = this.configForm.get('llm_endpoint')?.value
    const backend = this.configForm.get('llm_backend')?.value
    const apiKey = this.configForm.get('llm_api_key')?.value
    // Use current model or default
    const model = this.configForm.get('llm_model')?.value

    this.llmService
      .testConnection({
        endpoint,
        backend,
        api_key: apiKey,
        model,
      })
      .subscribe({
        next: (result) => {
          this.llmTestInProgress = false
          if (result.success) {
            this.toastService.showInfo(
              $localize`Connection successful! Latency: ${result.latency_ms}ms`
            )
            // Fetch models
            this.llmService.getModels(endpoint, backend).subscribe((models) => {
              const modelOption = PaperlessConfigOptions.find(
                (o) => o.key === 'llm_model'
              )
              if (modelOption) {
                modelOption.choices = models
                if (models.length > 0) {
                  // If current model is not in list, maybe warn or clear?
                  // But we don't want to clear valid config if fetch fails or is partial.
                  console.log(`Fetched ${models.length} models for LLM`)
                }
              }
            })
          } else {
            this.toastService.showError(
              $localize`Connection failed: ${result.error}`
            )
          }
        },
        error: (e) => {
          this.llmTestInProgress = false
          this.toastService.showError($localize`Test connection failed`, e)
        },
      })
  }

  ngOnDestroy(): void {
    this.unsubscribeNotifier.next(true)
    this.unsubscribeNotifier.complete()
  }

  private initialize(config: PaperlessConfig) {
    if (!this.store) {
      this.store = new BehaviorSubject(config)

      this.store
        .asObservable()
        .pipe(takeUntil(this.unsubscribeNotifier))
        .subscribe((state) => {
          this.configForm.patchValue(state, { emitEvent: false })
        })

      this.isDirty$ = dirtyCheck(this.configForm, this.store.asObservable())
    }
    this.initialConfig = config

    // Trigger initial fetch if endpoint exists
    const ocrEndpoint = this.configForm.get('ollama_endpoint')?.value
    if (ocrEndpoint) {
      this.ollamaService
        .getModels(ocrEndpoint)
        .pipe(first())
        .subscribe((models) => {
          const modelOption = PaperlessConfigOptions.find(
            (o) => o.key === 'ollama_model'
          )
          if (modelOption) {
            modelOption.choices = models
          }
        })
    }

    if (this.configForm.get('llm_embedding_backend')?.value === 'ollama') {
      const embedEndpoint =
        this.configForm.get('llm_embedding_endpoint')?.value ||
        this.configForm.get('llm_endpoint')?.value ||
        ocrEndpoint
      if (embedEndpoint) {
        this.ollamaService
          .getModels(embedEndpoint)
          .pipe(first())
          .subscribe((models) => {
            const modelOption = PaperlessConfigOptions.find(
              (o) => o.key === 'llm_embedding_model'
            )
            if (modelOption) {
              modelOption.choices = models
            }
          })
      }
    }

    // Also fetch LLM models if connection settings are already present
    const llmEndpoint = this.configForm.get('llm_endpoint')?.value
    const llmBackend = this.configForm.get('llm_backend')?.value
    if (llmEndpoint && llmBackend) {
      this.llmService
        .getModels(llmEndpoint, llmBackend)
        .pipe(first())
        .subscribe((models) => {
          const modelOption = PaperlessConfigOptions.find(
            (o) => o.key === 'llm_model'
          )
          if (modelOption) {
            modelOption.choices = models
          }
        })
    }
  }

  getDocsUrl(key: string) {
    return `https://docs.paperless-ngx.com/configuration/#${key}`
  }

  public saveConfig() {
    this.loading = true
    this.configService
      .saveConfig(this.configForm.value as PaperlessConfig)
      .pipe(takeUntil(this.unsubscribeNotifier), first())
      .subscribe({
        next: (config) => {
          this.loading = false
          this.initialize(config)
          this.store.next(config)
          this.settingsService.initializeSettings().subscribe()
          this.toastService.showInfo($localize`Configuration updated`)
        },
        error: (e) => {
          this.loading = false
          this.toastService.showError(
            $localize`An error occurred updating configuration`,
            e
          )
        },
      })
  }

  public discardChanges() {
    this.configForm.reset(this.initialConfig)
  }

  public uploadFile(file: File, key: string) {
    this.loading = true
    this.configService
      .uploadFile(file, this.configForm.value['id'], key)
      .pipe(takeUntil(this.unsubscribeNotifier), first())
      .subscribe({
        next: (config) => {
          this.loading = false
          this.initialize(config)
          this.store.next(config)
          this.settingsService.initializeSettings().subscribe()
          this.toastService.showInfo($localize`File successfully updated`)
        },
        error: (e) => {
          this.loading = false
          this.toastService.showError(
            $localize`An error occurred uploading file`,
            e
          )
        },
      })
  }
}

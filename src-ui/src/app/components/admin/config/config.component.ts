import { AsyncPipe, NgIf } from '@angular/common'
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
  combineLatest,
  first,
  takeUntil,
} from 'rxjs'
import { debounceTime } from 'rxjs/operators'
import {
  ConfigCategory,
  ConfigOption,
  ConfigOptionType,
  PaperlessConfig,
  PaperlessConfigOptions,
} from 'src/app/data/paperless-config'
import { PaperlessTaskName } from 'src/app/data/paperless-task'
import { ConfigService } from 'src/app/services/config.service'
import { LLMModel, LLMService } from 'src/app/services/llm.service'
import { OllamaService } from 'src/app/services/ollama.service'
import { SettingsService } from 'src/app/services/settings.service'
import { TasksService } from 'src/app/services/tasks.service'
import { ToastService } from 'src/app/services/toast.service'
import { FileComponent } from '../../common/input/file/file.component'
import { NumberComponent } from '../../common/input/number/number.component'
import { PasswordComponent } from '../../common/input/password/password.component'
import { SelectComponent } from '../../common/input/select/select.component'
import { SwitchComponent } from '../../common/input/switch/switch.component'
import { TextComponent } from '../../common/input/text/text.component'
import { TextAreaComponent } from '../../common/input/textarea/textarea.component'
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
    TextAreaComponent,
    NumberComponent,
    FileComponent,
    PasswordComponent,
    AsyncPipe,
    NgIf,
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
  private tasksService = inject(TasksService)
  private http = inject(HttpClient)

  public readonly ConfigOptionType = ConfigOptionType
  public readonly ConfigCategory = ConfigCategory

  // generated dynamically
  public configForm = new FormGroup({})

  public testInProgress = {
    llm_api_key: false,
    docling_endpoint: false,
  }

  public errors = {}

  public llmModels: LLMModel[] = []
  public embeddingModels: LLMModel[] = []

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

    // Dynamic model discovery for AI features
    combineLatest([
      this.configForm.get('llm_backend').valueChanges,
      this.configForm.get('llm_endpoint').valueChanges,
      this.configForm.get('llm_api_key').valueChanges,
    ])
      .pipe(takeUntil(this.unsubscribeNotifier), debounceTime(500))
      .subscribe(([backend, endpoint, apiKey]) => {
        this.fetchLLMModels(backend, endpoint, apiKey)
      })

    combineLatest([
      this.configForm.get('llm_embedding_backend').valueChanges,
      this.configForm.get('llm_embedding_endpoint').valueChanges,
      this.configForm.get('llm_embedding_api_key').valueChanges,
      this.configForm.get('llm_endpoint').valueChanges,
      this.configForm.get('llm_api_key').valueChanges,
    ])
      .pipe(takeUntil(this.unsubscribeNotifier), debounceTime(500))
      .subscribe(([backend, endpoint, apiKey, mainEndpoint, mainApiKey]) => {
        this.fetchEmbeddingModels(
          backend,
          endpoint || mainEndpoint,
          apiKey || mainApiKey
        )
      })
  }

  private fetchLLMModels(backend: string, endpoint: string, apiKey: string) {
    if (endpoint && backend) {
      this.llmService
        .getModels(endpoint, backend, apiKey)
        .pipe(first())
        .subscribe((models) => {
          this.llmModels = models
        })
    }
  }

  private fetchEmbeddingModels(
    backend: string,
    endpoint: string,
    apiKey: string
  ) {
    if (endpoint && backend) {
      this.llmService
        .getModels(endpoint, backend, apiKey)
        .pipe(first())
        .subscribe((models) => {
          this.embeddingModels = models
        })
    }
  }

  public refreshModels() {
    const val = this.configForm.value as PaperlessConfig
    this.fetchLLMModels(val.llm_backend, val.llm_endpoint, val.llm_api_key)
    this.fetchEmbeddingModels(
      val.llm_embedding_backend,
      val.llm_embedding_endpoint || val.llm_endpoint,
      val.llm_embedding_api_key || val.llm_api_key
    )
  }

  public rebuildIndex() {
    this.tasksService
      .run(PaperlessTaskName.LLMIndexUpdate)
      .pipe(first())
      .subscribe({
        next: () => {
          this.toastService.showInfo($localize`Index rebuild task queued`)
        },
        error: (e) => {
          this.toastService.showError($localize`Error queuing index rebuild`, e)
        },
      })
  }

  public testConnection(key: string) {
    this.testInProgress[key] = true
    const val = this.configForm.value as PaperlessConfig

    let obs: Observable<any>
    if (key === 'llm_api_key') {
      obs = this.llmService.testConnection({
        endpoint: val.llm_endpoint,
        backend: val.llm_backend,
        api_key: val.llm_api_key,
        model: val.llm_model,
      })
    } else if (key === 'docling_endpoint') {
      obs = this.http.get(
        `/api/docling_proxy/?endpoint=${val.docling_endpoint}`
      )
    }

    obs?.pipe(first()).subscribe({
      next: (result) => {
        this.testInProgress[key] = false
        this.toastService.showInfo($localize`Connection successful!`)
        if (key === 'llm_api_key') {
          this.refreshModels()
        }
      },
      error: (e) => {
        this.testInProgress[key] = false
        this.toastService.showError($localize`Connection failed`, e)
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

    // Trigger initial model fetches
    this.refreshModels()
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
    this.refreshModels()
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

import { AsyncPipe } from '@angular/common'
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
  takeUntil,
  merge,
} from 'rxjs'
import {
  ConfigCategory,
  ConfigOption,
  ConfigOptionType,
  PaperlessConfig,
  PaperlessConfigOptions,
} from 'src/app/data/paperless-config'
import { ConfigService } from 'src/app/services/config.service'
import { SettingsService } from 'src/app/services/settings.service'
import { ToastService } from 'src/app/services/toast.service'
import { OllamaService } from 'src/app/services/ollama.service'
import { debounceTime, switchMap } from 'rxjs/operators'
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
  implements OnInit, OnDestroy, DirtyComponent {
  private configService = inject(ConfigService)
  private toastService = inject(ToastService)
  private settingsService = inject(SettingsService)
  private ollamaService = inject(OllamaService)

  public readonly ConfigOptionType = ConfigOptionType

  // generated dynamically
  public configForm = new FormGroup({})

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
    ).pipe(
      takeUntil(this.unsubscribeNotifier),
      debounceTime(500),
      switchMap(() => {
        const engine = this.configForm.get('ocr_engine')?.value
        const endpoint = this.configForm.get('ollama_endpoint')?.value
        if (engine === 'ollama' && endpoint) {
          return this.ollamaService.getModels(endpoint)
        }
        return []
      })
    ).subscribe({
      next: (models) => {
        const modelOption = PaperlessConfigOptions.find(o => o.key === 'ollama_model')
        if (modelOption) {
          modelOption.choices = models
          // Only show toast if we actually returned models (meaning fetch happened)
          // To avoid spamming on every keypress if returning empty array above.
          // Wait, 'models' will be empty array if condition false OR if fetch returned empty.
          // We can distinguish by context or just check length.
          // Ideally we only want to show toast if we *attempted* a fetch.
          // But here we are just returning empty array if no fetch.
          // A better pattern: filter BEFORE switchMap?
          // If I filter, I won't reset the choices if engine changes away from ollama?
          // Actually, if engine changes to Tesseract, we probably don't care about ollama_model choices.
          if (models.length > 0) {
            this.toastService.showInfo($localize`Found ${models.length} Ollama models`)
          } else if (this.configForm.get('ocr_engine')?.value === 'ollama' && this.configForm.get('ollama_endpoint')?.value) {
            // If we really tried and got 0.
            this.toastService.showInfo($localize`No models found at this endpoint`)
          }
        }
      },
      error: (err) => {
        this.toastService.showError($localize`Failed to fetch models`, err)
      }
    })

    // Trigger initial fetch if endpoint exists
    const initialEndpoint = this.configForm.get('ollama_endpoint')?.value
    if (initialEndpoint) {
      this.ollamaService.getModels(initialEndpoint).subscribe(models => {
        const modelOption = PaperlessConfigOptions.find(o => o.key === 'ollama_model')
        if (modelOption) {
          modelOption.choices = models
        }
      })
    }
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
    this.configForm.patchValue(config)

    this.initialConfig = config
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

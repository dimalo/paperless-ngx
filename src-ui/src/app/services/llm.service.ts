import { HttpClient } from '@angular/common/http'
import { Injectable } from '@angular/core'
import { Observable, of } from 'rxjs'
import { catchError, map } from 'rxjs/operators'
import { environment } from 'src/environments/environment'

export interface LLMConnectionConfig {
  backend: string
  endpoint?: string
  api_key?: string
  model?: string
}

export interface LLMConnectionResponse {
  success: boolean
  latency_ms?: number
  model_info?: any
  error?: string
}

@Injectable({
  providedIn: 'root',
})
export class LLMService {
  constructor(protected http: HttpClient) {}

  getModels(
    endpoint: string,
    backend: string = 'ollama'
  ): Observable<{ id: string; name: string }[]> {
    return this.http
      .get<any>(`${environment.apiBaseUrl}llm_proxy/`, {
        params: {
          endpoint: endpoint || '',
          backend: backend,
        },
      })
      .pipe(
        map((response) => {
          if (Array.isArray(response)) {
            return response.map((m) => ({ id: m.id, name: m.name || m.id }))
          } else if (response.models) {
            return (response.models || []).map((m) => ({
              id: m.name,
              name: m.name,
            }))
          }
          return []
        }),
        catchError((e) => {
          console.warn('Failed to fetch LLM models', e)
          return of([])
        })
      )
  }

  testConnection(
    config: LLMConnectionConfig
  ): Observable<LLMConnectionResponse> {
    return this.http
      .post<LLMConnectionResponse>(
        `${environment.apiBaseUrl}llm_proxy/test`,
        config
      )
      .pipe(
        catchError((e) => {
          return of({
            success: false,
            error: e.error?.error || e.message || 'Connection failed',
          })
        })
      )
  }
}

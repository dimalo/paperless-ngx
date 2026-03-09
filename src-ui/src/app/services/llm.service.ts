import { HttpClient } from '@angular/common/http'
import { Injectable, inject } from '@angular/core'
import { Observable, of } from 'rxjs'
import { catchError, map } from 'rxjs/operators'
import { environment } from 'src/environments/environment'

export interface LLMModel {
  id: string
  name: string
}

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
  private http = inject(HttpClient)
  private baseUrl = environment.apiBaseUrl

  getModels(
    endpoint: string,
    backend: string = 'ollama',
    apiKey?: string
  ): Observable<LLMModel[]> {
    if (!endpoint) return of([])
    let params: any = { endpoint, backend }
    if (apiKey) params.api_key = apiKey

    return this.http.get<any>(`${this.baseUrl}llm_proxy/`, { params }).pipe(
      map((response) => {
        if (Array.isArray(response)) {
          return response.map((m) => ({ id: m.id, name: m.name || m.id }))
        } else if (response.data && Array.isArray(response.data)) {
          return response.data.map((m: any) => ({
            id: m.id,
            name: m.name || m.id,
          }))
        } else if (response.models) {
          return (response.models || []).map((m: any) => ({
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
      .post<LLMConnectionResponse>(`${this.baseUrl}llm_proxy/`, {
        ...config,
        path: 'test', // Handle path in body or endpoint logic
      })
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

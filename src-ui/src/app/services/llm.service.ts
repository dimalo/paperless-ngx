import { HttpClient } from '@angular/common/http'
import { Injectable, inject } from '@angular/core'
import { Observable, catchError, of } from 'rxjs'
import { environment } from 'src/environments/environment'

export interface LLMModel {
  id: string
  name: string
}

@Injectable({
  providedIn: 'root',
})
export class LLMService {
  private http = inject(HttpClient)
  private baseUrl = environment.apiBaseUrl

  getModels(
    endpoint: string,
    backend: string,
    apiKey?: string
  ): Observable<LLMModel[]> {
    if (!endpoint) return of([])
    let params: any = { endpoint, backend }
    if (apiKey) params.api_key = apiKey
    return this.http
      .get<LLMModel[]>(`${this.baseUrl}llm_proxy/`, { params })
      .pipe(catchError(() => of([])))
  }

  testConnection(
    endpoint: string
  ): Observable<{ status: string; version?: string; message?: string }> {
    return this.http
      .post<{
        status: string
        version?: string
        message?: string
      }>(`${this.baseUrl}llm_proxy/test/`, { endpoint })
      .pipe(catchError((err) => of({ status: 'error', message: err.message })))
  }
}

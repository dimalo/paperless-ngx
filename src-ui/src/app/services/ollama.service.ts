import { Injectable } from '@angular/core'
import { HttpClient } from '@angular/common/http'
import { Observable, of } from 'rxjs'
import { map, catchError } from 'rxjs/operators'
import { environment } from 'src/environments/environment'

@Injectable({
  providedIn: 'root',
})
export class OllamaService {
  constructor(private http: HttpClient) { }

  getModels(endpoint: string): Observable<{ id: string; name: string }[]> {
    if (!endpoint) return of([])

    // The endpoint is now passed as a query param to our backend proxy
    return this.http.get<any>(`${environment.apiBaseUrl}ollama_proxy/`, { params: { endpoint } }).pipe(
      map((response) => {
        return (response.models || []).map((m) => ({ id: m.name, name: m.name }))
      }),
      catchError((e) => {
        console.warn('Failed to fetch Ollama models via proxy', e)
        throw e // Re-throw to let component handle error (Toast)
      })
    )
  }
}

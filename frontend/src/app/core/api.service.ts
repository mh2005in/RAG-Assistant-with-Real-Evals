import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE } from './api-config';
import {
  AnswerRequest,
  AnswerResponse,
  EvaluateRequest,
  EvaluateResponse,
  ProcessResponse,
  RetrievalRequest,
  RetrievalResponse,
} from './models';

/** Typed client for the RAG backend endpoints (backend/api.py). */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly base = API_BASE;

  /**
   * POST /process — multipart upload. The backend chunks with every strategy
   * and stores them all; the response reports what was stored, not the chunks.
   */
  process(
    file: File,
    name: string,
    accessRole: string,
    chunkSize?: number | null,
    excludePages?: string | null,
  ): Observable<ProcessResponse> {
    const form = new FormData();
    form.append('file', file);
    form.append('name', name);
    form.append('access_role', accessRole);
    if (chunkSize != null) {
      form.append('chunk_size', String(chunkSize));
    }
    if (excludePages) {
      form.append('exclude_pages', excludePages);
    }
    return this.http.post<ProcessResponse>(`${this.base}/process`, form);
  }

  /** POST /evaluate — score a stored document's strategies and keep the best. */
  evaluate(request: EvaluateRequest): Observable<EvaluateResponse> {
    return this.http.post<EvaluateResponse>(`${this.base}/evaluate`, request);
  }

  /** POST /retrieve — similarity search over stored chunks (no generation). */
  retrieve(request: RetrievalRequest): Observable<RetrievalResponse> {
    return this.http.post<RetrievalResponse>(`${this.base}/retrieve`, request);
  }

  /** POST /answer — retrieve context and generate a grounded answer. */
  answer(request: AnswerRequest): Observable<AnswerResponse> {
    return this.http.post<AnswerResponse>(`${this.base}/answer`, request);
  }

  /** Turn an HTTP failure into a message worth showing the user. */
  errorMessage(err: unknown): string {
    if (err instanceof HttpErrorResponse) {
      if (err.status === 0) {
        return 'Cannot reach the API. Is the backend running on :8000?';
      }
      const detail = (err.error as { detail?: unknown } | null)?.detail;
      if (typeof detail === 'string') {
        return detail;
      }
      if (Array.isArray(detail)) {
        // FastAPI 422: a list of {loc, msg} validation errors.
        return detail
          .map((d: { loc?: unknown[]; msg?: string }) => {
            const loc = Array.isArray(d.loc) ? d.loc.join('.') : '';
            return loc ? `${loc}: ${d.msg}` : (d.msg ?? 'invalid');
          })
          .join('; ');
      }
      return `${err.status} ${err.statusText}`.trim() || 'Request failed.';
    }
    return 'Unexpected error.';
  }
}

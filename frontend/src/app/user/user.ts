import { DecimalPipe } from '@angular/common';
import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../core/api.service';
import {
  AnswerResponse,
  CHUNKING_STRATEGIES,
  ChunkingStrategy,
  RetrievalResponse,
} from '../core/models';
import { SessionService } from '../core/session.service';

type Mode = 'answer' | 'retrieve';

/**
 * User tab: ask a question of the stored documents.
 *
 * Two modes over one query box:
 *  - Answer   → POST /answer, a grounded answer plus its sources.
 *  - Retrieve → POST /retrieve, the raw ranked chunks with no generation.
 */
@Component({
  selector: 'app-user',
  imports: [FormsModule, DecimalPipe],
  templateUrl: './user.html',
  styleUrl: './user.css',
})
export class User {
  private readonly api = inject(ApiService);
  readonly session = inject(SessionService);

  readonly strategies = CHUNKING_STRATEGIES;

  mode: Mode = 'answer';
  query = '';
  topK = 5;
  strategy: ChunkingStrategy | '' = '';

  loading = false;
  error = '';
  answer: AnswerResponse | null = null;
  retrieval: RetrievalResponse | null = null;

  setMode(mode: Mode): void {
    if (this.mode === mode) {
      return;
    }
    this.mode = mode;
    this.answer = null;
    this.retrieval = null;
    this.error = '';
  }

  submit(): void {
    const query = this.query.trim();
    const accessRole = this.session.accessRole.trim();
    if (!query) {
      this.error = 'Enter a question to ask.';
      return;
    }
    if (!accessRole) {
      this.error = 'Set an access role in the header first.';
      return;
    }

    this.error = '';
    this.loading = true;
    this.answer = null;
    this.retrieval = null;

    const strategy = this.strategy || null;
    const common = { query, access_role: accessRole, top_k: this.topK };

    if (this.mode === 'answer') {
      this.api.answer({ ...common, chunking_strategy: strategy }).subscribe({
        next: (res) => {
          this.answer = res;
          this.loading = false;
        },
        error: (err) => this.fail(err),
      });
    } else {
      this.api.retrieve({ ...common, chunking_strategy: strategy }).subscribe({
        next: (res) => {
          this.retrieval = res;
          this.loading = false;
        },
        error: (err) => this.fail(err),
      });
    }
  }

  private fail(err: unknown): void {
    this.loading = false;
    this.error = this.api.errorMessage(err);
  }
}

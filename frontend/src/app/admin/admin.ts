import { DecimalPipe, PercentPipe } from '@angular/common';
import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../core/api.service';
import {
  EvaluateResponse,
  ProcessResponse,
  QAPair,
  StructuralChunkingOptions,
} from '../core/models';
import { SessionService } from '../core/session.service';

/**
 * Admin tab: ingest and evaluate documents.
 *
 *  - Upload   → POST /process. Chunks the PDF with every strategy and stores
 *    them all; reports the stored strategies and the new document id.
 *  - Evaluate → POST /evaluate. Scores the stored strategies against labelled
 *    Q&A pairs, keeps the winner, and reports each strategy's score. The upload
 *    result pre-fills the document id so the two steps chain naturally.
 */
@Component({
  selector: 'app-admin',
  imports: [FormsModule, DecimalPipe, PercentPipe],
  templateUrl: './admin.html',
  styleUrl: './admin.css',
})
export class Admin {
  private readonly api = inject(ApiService);
  readonly session = inject(SessionService);

  // --- Upload -------------------------------------------------------------
  file: File | null = null;
  docName = '';
  chunkSize: number | null = null;
  excludePages = '';
  // Structural strategy tuning: one regex per line, plus its section bounds.
  headingPatterns = '';
  minWords: number | null = null;
  maxWords: number | null = null;

  uploading = false;
  uploadError = '';
  processResult: ProcessResponse | null = null;

  // --- Evaluate -----------------------------------------------------------
  documentId: number | null = null;
  evalTopK = 5;
  qaPairs: QAPair[] = [{ question: '', answer: '' }];

  evaluating = false;
  evalError = '';
  evalResult: EvaluateResponse | null = null;

  /**
   * A document is stored under an access role, so uploading needs one set first
   * (in the shared field at the top of the tab / the header).
   */
  get hasRole(): boolean {
    return this.session.accessRole.trim().length > 0;
  }

  /**
   * Evaluation runs against a document produced by Upload in this session, so it
   * is only available once a process call has stored one (and pre-filled its id).
   */
  get canEvaluate(): boolean {
    return this.processResult?.processed === true && this.processResult.document_id != null;
  }

  /**
   * The structural options to send, or null when every one was left blank — the
   * backend then uses the strategy's built-in markers and bounds.
   *
   * The patterns are Python regexes (one per line) and are passed through
   * untouched: JavaScript's regex dialect differs — inline flags like `(?i)` are
   * a syntax error here but valid there — so validating them in the browser
   * would reject patterns the backend accepts. It reports a bad one as a 422.
   */
  private structuralOptions(): StructuralChunkingOptions | null {
    const patterns = this.headingPatterns
      .split(/\r?\n/)
      .map((pattern) => pattern.trim())
      .filter((pattern) => pattern.length > 0);

    const options: StructuralChunkingOptions = {};
    if (patterns.length > 0) {
      options.heading_patterns = patterns;
    }
    if (this.minWords != null) {
      options.min_words = this.minWords;
    }
    if (this.maxWords != null) {
      options.max_words = this.maxWords;
    }
    return Object.keys(options).length > 0 ? options : null;
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.file = input.files?.[0] ?? null;
    if (this.file && !this.docName) {
      // Sensible default: strip the extension off the filename.
      this.docName = this.file.name.replace(/\.[^.]+$/, '');
    }
  }

  upload(): void {
    const accessRole = this.session.accessRole.trim();
    const name = this.docName.trim();
    if (!this.file) {
      this.uploadError = 'Choose a PDF file to upload.';
      return;
    }
    if (!name) {
      this.uploadError = 'Give the document a name.';
      return;
    }
    if (!accessRole) {
      this.uploadError = 'Set an access role in the header first.';
      return;
    }

    this.uploadError = '';
    this.uploading = true;
    this.processResult = null;

    this.api
      .process(
        this.file,
        name,
        accessRole,
        this.chunkSize,
        this.excludePages.trim() || null,
        this.structuralOptions(),
      )
      .subscribe({
        next: (res) => {
          this.processResult = res;
          this.uploading = false;
          // Chain into evaluation: pre-fill the id of what we just stored.
          if (res.document_id != null) {
            this.documentId = res.document_id;
          }
        },
        error: (err) => {
          this.uploading = false;
          this.uploadError = this.api.errorMessage(err);
        },
      });
  }

  addPair(): void {
    this.qaPairs.push({ question: '', answer: '' });
  }

  removePair(index: number): void {
    this.qaPairs.splice(index, 1);
    if (this.qaPairs.length === 0) {
      this.qaPairs.push({ question: '', answer: '' });
    }
  }

  evaluate(): void {
    const accessRole = this.session.accessRole.trim();
    if (!this.canEvaluate || this.documentId == null) {
      this.evalError = 'Upload & process a document first, then evaluate it.';
      return;
    }
    if (!accessRole) {
      this.evalError = 'Set an access role in the header first.';
      return;
    }
    const pairs = this.qaPairs
      .map((p) => ({ question: p.question.trim(), answer: p.answer.trim() }))
      .filter((p) => p.question && p.answer);
    if (pairs.length === 0) {
      this.evalError = 'Add at least one question and its expected answer.';
      return;
    }

    this.evalError = '';
    this.evaluating = true;
    this.evalResult = null;

    this.api
      .evaluate({
        document_id: this.documentId,
        access_role: accessRole,
        qa_pairs: pairs,
        top_k: this.evalTopK,
      })
      .subscribe({
        next: (res) => {
          this.evalResult = res;
          this.evaluating = false;
        },
        error: (err) => {
          this.evaluating = false;
          this.evalError = this.api.errorMessage(err);
        },
      });
  }
}

/**
 * TypeScript mirrors of the backend Pydantic DTOs (see backend/dtos/).
 *
 * These describe the JSON on the wire for /process, /evaluate, /retrieve and
 * /answer. Keep them in sync with the Python DTOs — the field names must match.
 */

/** Chunking strategies under evaluation (backend ChunkingStrategy enum). */
export type ChunkingStrategy = 'fixed' | 'semantic' | 'structural' | 'recursive' | 'llm';

export const CHUNKING_STRATEGIES: ChunkingStrategy[] = [
  'fixed',
  'semantic',
  'structural',
  'recursive',
  'llm',
];

/** Detected document type of an uploaded file. */
export type DocType = 'pdf' | 'unknown';

// --- /process ---------------------------------------------------------------

/**
 * Optional tuning for the structural strategy (backend StructuralChunkingRequest),
 * sent as the JSON `structural` form field. Omitted keys keep the backend's
 * built-in markers and size bounds.
 */
export interface StructuralChunkingOptions {
  heading_patterns?: string[];
  min_words?: number;
  max_words?: number;
}

export interface StoredStrategy {
  strategy: string;
  chunk_count: number;
}

export interface ProcessResponse {
  processed: boolean;
  doc_type: DocType;
  document_id: number | null;
  strategies: StoredStrategy[];
}

// --- /evaluate --------------------------------------------------------------

export interface QAPair {
  question: string;
  answer: string;
}

export interface EvaluateRequest {
  document_id: number;
  access_role: string;
  qa_pairs: QAPair[];
  top_k?: number;
}

export interface StrategyEvaluation {
  strategy: string;
  questions: number;
  answer_similarity: number;
  hit_rate: number;
  selected: boolean;
}

export interface EvaluateResponse {
  document_id: number;
  chunking_strategy: string | null;
  evaluations: StrategyEvaluation[];
}

// --- /retrieve --------------------------------------------------------------

export interface RetrievalRequest {
  query: string;
  access_role: string;
  top_k?: number;
  chunking_strategy?: ChunkingStrategy | null;
}

export interface RetrievedChunk {
  document_id: number;
  document_name: string;
  chunking_strategy: string;
  chunk_index: number;
  page_number: number;
  text: string;
  score: number;
}

export interface RetrievalResponse {
  query: string;
  count: number;
  results: RetrievedChunk[];
}

// --- /answer ----------------------------------------------------------------

export interface AnswerRequest {
  query: string;
  access_role: string;
  top_k?: number;
  chunking_strategy?: ChunkingStrategy | null;
}

export interface AnswerResponse {
  query: string;
  answer: string;
  sources: RetrievedChunk[];
}

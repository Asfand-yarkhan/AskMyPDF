export type Intent = "QA" | "SUMMARY" | "QUIZ" | "FLASHCARDS" | "NOTES" | "EXPLAIN" | "OUT_OF_SCOPE";
export type Difficulty = "easy" | "medium" | "hard";
export type QuestionType = "mcq" | "true_false" | "short";

export interface ChunkConfig {
  strategy: "short" | "notes" | "slides" | "general" | "technical";
  chunk_size: number;
  chunk_overlap: number;
  reason: string;
}

export interface DocumentProfile {
  page_count: number;
  total_words: number;
  avg_words_per_page: number;
  heading_count: number;
  heading_density: number;
  table_count: number;
  table_ratio: number;
  bullet_ratio: number;
  ocr_pages: number;
  is_scanned: boolean;
  technical_score: number;
  doc_type: string;
}

export interface DocumentInfo {
  doc_id: string;
  filename: string;
  size_bytes: number;
  page_count: number;
  chunk_count: number;
  total_chars: number;
  created_at: string;
  chunk_config: ChunkConfig;
  profile: DocumentProfile;
  embedding_id: string;
}

export interface SourceChunk {
  chunk_id: string;
  chunk_index: number;
  page: number;
  page_end: number;
  section: string | null;
  kind: string;
  has_table: boolean;
  text: string;
}

export interface QuizQuestion {
  question: string;
  type: QuestionType;
  options: string[];
  correct_answer: string;
  explanation: string;
  page: number;
}

export interface Quiz {
  title: string;
  difficulty: Difficulty;
  questions: QuizQuestion[];
}

export interface Flashcard {
  front: string;
  back: string;
  page: number;
}

export interface FlashcardDeck {
  title: string;
  cards: Flashcard[];
}

export interface RouterParams {
  num_questions?: number;
  difficulty?: Difficulty;
  topic?: string;
  language?: "english" | "urdu" | "hinglish";
  question_type?: string;
  summary_style?: string;
}

export type ChatEvent =
  | { type: "intent"; intent: Intent; params: RouterParams }
  | { type: "status"; message: string }
  | { type: "sources"; sources: SourceChunk[] }
  | { type: "token"; content: string }
  | { type: "quiz"; quiz: Quiz }
  | { type: "flashcards"; flashcards: FlashcardDeck }
  | { type: "error"; message: string }
  | { type: "done" };

export type UploadStage = "uploading" | "uploaded" | "parsing" | "analyzing" | "chunking" | "embedding" | "done";

export type UploadEvent =
  | { type: "progress"; stage: UploadStage; progress: number; message: string }
  | { type: "complete"; document: DocumentInfo; reused: boolean }
  | { type: "error"; message: string };

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface GradeItem {
  question: string;
  type: QuestionType;
  options: string[];
  correct_answer: string;
  user_answer: string;
  explanation?: string;
  page?: number;
}

export interface GradeResult {
  index: number;
  correct: boolean;
  score: number;
  feedback: string;
}

export interface GradeResponse {
  results: GradeResult[];
  total_score: number;
  max_score: number;
  percentage: number;
}

export interface Health {
  status: "ok";
  llm_provider: string;
  llm_model: string;
  router_model: string;
  embedding_model: string;
  llm_configured: boolean;
  documents: number;
}

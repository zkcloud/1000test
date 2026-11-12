export type Mode = "exam" | "practice";
export type Choice = "A" | "B" | "C" | "D";
export interface Exam {
  id: number;
  number: number;
  title: string;
  duration_minutes: number;
  total: number;
}
export interface QuestionRef {
  id: number;
  number: number;
  part: number;
  passage_id: number | null;
}
export interface AnswerState {
  selection: Choice | null;
  first_selection: Choice | null;
  first_peeked: number;
  revealed_at: number | null;
  marked: number;
}
export interface ResultEntry extends QuestionRef {
  selection: Choice | null;
  answer: Choice;
  correct: boolean;
}
export interface Result {
  total: number;
  correct: number;
  wrong: number;
  blank: number;
  score: number | null;
  independent_total: number;
  independent_correct: number;
  peek_first: number;
  duration_seconds: number;
  entries: ResultEntry[];
}
export interface Attempt {
  id: string;
  exam_id: number;
  mode: Mode;
  scope: number | null;
  created_at: number;
  deadline: number | null;
  finished_at: number | null;
  status: "active" | "finished";
  current_index: number;
  revision: number;
  auto_next: boolean;
  server_time: number;
  paused: boolean;
  duration_seconds: number;
  questions: QuestionRef[];
  responses: Record<string, AnswerState>;
  result?: Result;
}
export interface Passage {
  id: number;
  first_number: number;
  last_number: number;
  instruction: string;
  content: string;
  assets: { id: number; page: number; url: string }[];
}
export interface Question extends QuestionRef {
  stem: string;
  page_start: number;
  page_end: number;
  options: { label: Choice; content: string }[];
  passage: Passage | null;
  answer?: Choice;
  explanation?: string | null;
}
export interface PendingAnswer {
  aid: string;
  qid: number;
  selection: Choice | null;
  revision: number;
}

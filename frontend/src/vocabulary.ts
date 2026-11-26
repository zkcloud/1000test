export type PracticeMode = "choice" | "spelling";

export interface VocabularyMeaning {
  pos: string;
  meaning: string;
}

export interface VocabularySummary {
  id: number;
  word: string;
  meanings: VocabularyMeaning[];
  tests: number[];
}

export interface VocabularySource {
  test_number: number;
  pdf_page: number;
  printed_page: string | null;
}

export interface VocabularySense extends VocabularyMeaning {
  id: number;
  usage: string;
  spelling_prompt?: string | null;
  example: {
    text: string;
    translation: string;
    kind: "original" | "supplemental";
    pdf_page: number | null;
    printed_page: string | null;
  } | null;
  sources: VocabularySource[];
}

export interface VocabularyDetail extends VocabularySummary {
  senses: VocabularySense[];
}

export interface VocabularyList {
  items: VocabularySummary[];
  page: number;
  pages: number;
  total: number;
}

export interface VocabularyQuestion {
  token: string;
  prompt: string;
  pos: string | null;
  options: { id: string; label: string }[];
}

export interface VocabularyRound {
  mode: PracticeMode;
  questions: VocabularyQuestion[];
}

export interface VocabularyAnswer {
  correct: boolean;
  given_answer: string;
  correct_answer: string;
  word_id: number;
  sense: VocabularySense;
}

export function testLabel(test: number) {
  return `Test ${String(test).padStart(2, "0")}`;
}

const pdf =
  "https://github.com/zkcloud/1000test/blob/master/" +
  encodeURIComponent("【2019版新东方】阅读全真模拟1000题.pdf");

export function pdfPageLink(page: number) {
  return `${pdf}#page=${page}`;
}

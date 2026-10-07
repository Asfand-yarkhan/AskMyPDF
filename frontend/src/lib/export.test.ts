import { describe, expect, it } from "vitest";
import type { FlashcardDeck, Quiz } from "@/api/types";
import { escapeHtml, flashcardsToAnki, flashcardsToCsv, quizToHtml } from "@/lib/export";

const deck: FlashcardDeck = {
  title: "Biology",
  cards: [
    { front: "What is ATP?", back: "The cell's\tenergy\ncurrency", page: 2 },
    { front: 'Say "hi"', back: "a, b", page: 3 },
  ],
};

describe("flashcard export", () => {
  it("writes Anki plain-text with headers and no stray tabs/newlines", () => {
    const lines = flashcardsToAnki(deck).split("\n");
    expect(lines.slice(0, 4)).toEqual(["#separator:tab", "#html:true", "#notetype:Basic", "#deck:Biology"]);
    expect(lines[4]).toBe("What is ATP?\tThe cell's energy<br>currency (p. 2)");
    expect(lines[4].split("\t")).toHaveLength(2);
  });

  it("quotes CSV cells", () => {
    expect(flashcardsToCsv(deck).split("\r\n")[2]).toBe('"Say ""hi""","a, b","3"');
  });
});

describe("quiz print", () => {
  it("escapes HTML and includes an answer key with letters", () => {
    const quiz: Quiz = {
      title: "Quiz <1>",
      difficulty: "easy",
      questions: [
        { question: "2 < 3?", type: "mcq", options: ["yes", "no", "maybe", "never"], correct_answer: "yes", explanation: "math", page: 1 },
      ],
    };
    const html = quizToHtml(quiz);
    expect(html).toContain("Quiz &lt;1&gt;");
    expect(html).toContain("2 &lt; 3?");
    expect(html).toContain("A) yes");
    expect(escapeHtml(`<a href="x">'`)).toBe("&lt;a href=&quot;x&quot;&gt;&#39;");
  });
});

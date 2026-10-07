import type { FlashcardDeck, Quiz } from "@/api/types";

const slug = (text: string) =>
  text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "export";

export function downloadText(filename: string, content: string, mime = "text/plain") {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Anki "Notes in Plain Text" import: one card per line, front<TAB>back. */
export function flashcardsToAnki(deck: FlashcardDeck): string {
  const clean = (s: string) => s.replace(/\t/g, " ").replace(/\r?\n/g, "<br>").trim();
  const header = ["#separator:tab", "#html:true", `#notetype:Basic`, `#deck:${clean(deck.title)}`];
  return [...header, ...deck.cards.map((c) => `${clean(c.front)}\t${clean(c.back)} (p. ${c.page})`)].join("\n");
}

export function flashcardsToCsv(deck: FlashcardDeck): string {
  const cell = (s: string | number) => `"${String(s).replace(/"/g, '""')}"`;
  return ["front,back,page", ...deck.cards.map((c) => [cell(c.front), cell(c.back), cell(c.page)].join(","))].join("\r\n");
}

export const exportAnki = (deck: FlashcardDeck) => downloadText(`${slug(deck.title)}-anki.txt`, flashcardsToAnki(deck));
export const exportCsv = (deck: FlashcardDeck) => downloadText(`${slug(deck.title)}.csv`, "﻿" + flashcardsToCsv(deck), "text/csv");

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]!);
}

const PRINT_CSS = `
  body { font-family: Inter, system-ui, sans-serif; color: #111827; max-width: 760px; margin: 32px auto; padding: 0 24px; line-height: 1.5; }
  h1 { font-size: 22px; margin-bottom: 4px; } .meta { color: #6b7280; font-size: 13px; margin-bottom: 24px; }
  ol { padding-left: 20px; } li.q { margin-bottom: 18px; break-inside: avoid; }
  .opts { list-style: upper-alpha; margin: 6px 0 0; } .blank { border-bottom: 1px solid #9ca3af; height: 28px; margin-top: 8px; }
  h2 { font-size: 17px; margin-top: 32px; border-top: 1px solid #e5e7eb; padding-top: 16px; } .ans { margin-bottom: 10px; font-size: 14px; }
  .card { border: 1px solid #d1d5db; border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; break-inside: avoid; }
  .card b { display: block; margin-bottom: 4px; } .page { color: #6b7280; font-size: 12px; }
  @media print { .answers { break-before: page; } }`;

function openPrintWindow(title: string, body: string) {
  const win = window.open("", "_blank");
  if (!win) return false; // popup blocked
  win.document.write(
    `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(title)}</title><style>${PRINT_CSS}</style></head>` +
      `<body>${body}<script>window.onload = () => setTimeout(() => window.print(), 200)</script></body></html>`,
  );
  win.document.close();
  return true;
}

export function quizToHtml(quiz: Quiz): string {
  const questions = quiz.questions
    .map((q) => {
      const options =
        q.type === "short"
          ? `<div class="blank"></div>`
          : `<ol class="opts">${q.options.map((o) => `<li>${escapeHtml(o)}</li>`).join("")}</ol>`;
      return `<li class="q">${escapeHtml(q.question)}${options}</li>`;
    })
    .join("");
  const answers = quiz.questions
    .map((q, i) => {
      const letter = q.type === "mcq" ? `${String.fromCharCode(65 + q.options.indexOf(q.correct_answer))}) ` : "";
      return `<div class="ans"><b>${i + 1}.</b> ${letter}${escapeHtml(q.correct_answer)} <span class="page">(p. ${q.page})</span><br>${escapeHtml(q.explanation)}</div>`;
    })
    .join("");
  return (
    `<h1>${escapeHtml(quiz.title)}</h1><div class="meta">${quiz.questions.length} questions · ${quiz.difficulty}</div>` +
    `<ol>${questions}</ol><section class="answers"><h2>Answer key</h2>${answers}</section>`
  );
}

export function flashcardsToHtml(deck: FlashcardDeck): string {
  const cards = deck.cards
    .map((c) => `<div class="card"><b>${escapeHtml(c.front)}</b>${escapeHtml(c.back)} <span class="page">(p. ${c.page})</span></div>`)
    .join("");
  return `<h1>${escapeHtml(deck.title)}</h1><div class="meta">${deck.cards.length} cards</div>${cards}`;
}

export const printQuiz = (quiz: Quiz) => openPrintWindow(quiz.title, quizToHtml(quiz));
export const printFlashcards = (deck: FlashcardDeck) => openPrintWindow(deck.title, flashcardsToHtml(deck));

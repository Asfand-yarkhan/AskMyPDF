/**
 * Tiny Leitner-style spaced repetition for flashcards.
 *
 * Every card sits in a box 1..5. "Again" sends it back to box 1, "Good" moves it up one box,
 * "Easy" moves it up two. Higher boxes come back later, so you spend time on what you don't know.
 */

export type Grade = "again" | "good" | "easy";

export interface CardState {
  box: number; // 1..5
  due: number; // epoch ms
  reviews: number;
}

const MINUTE = 60_000;
const DAY = 24 * 60 * MINUTE;
export const MAX_BOX = 5;
/** Delay before a card in box N is due again. */
export const BOX_INTERVALS: Record<number, number> = {
  1: 10 * MINUTE,
  2: 1 * DAY,
  3: 3 * DAY,
  4: 7 * DAY,
  5: 16 * DAY,
};

export const newCard = (): CardState => ({ box: 1, due: 0, reviews: 0 });

export function review(card: CardState | undefined, grade: Grade, now = Date.now()): CardState {
  const current = card ?? newCard();
  const box =
    grade === "again" ? 1 : Math.min(MAX_BOX, current.box + (grade === "easy" ? 2 : 1));
  return { box, due: now + BOX_INTERVALS[box], reviews: current.reviews + 1 };
}

export const isDue = (card: CardState | undefined, now = Date.now()): boolean => !card || card.due <= now;

export function dueIndexes(states: (CardState | undefined)[], now = Date.now()): number[] {
  return states.map((s, i) => (isDue(s, now) ? i : -1)).filter((i) => i >= 0);
}

export function formatDue(card: CardState | undefined, now = Date.now()): string {
  if (isDue(card, now)) return "due now";
  const ms = card!.due - now;
  if (ms < 60 * MINUTE) return `in ${Math.max(1, Math.round(ms / MINUTE))} min`;
  if (ms < DAY) return `in ${Math.round(ms / (60 * MINUTE))} h`;
  return `in ${Math.round(ms / DAY)} d`;
}

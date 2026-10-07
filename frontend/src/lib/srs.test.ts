import { describe, expect, it } from "vitest";
import { BOX_INTERVALS, dueIndexes, formatDue, isDue, MAX_BOX, newCard, review } from "@/lib/srs";

const NOW = 1_700_000_000_000;

describe("spaced repetition", () => {
  it("new cards are due", () => {
    expect(isDue(undefined, NOW)).toBe(true);
    expect(isDue(newCard(), NOW)).toBe(true);
  });

  it("good moves up one box, easy two, again resets", () => {
    const good = review(undefined, "good", NOW);
    expect(good.box).toBe(2);
    expect(good.due).toBe(NOW + BOX_INTERVALS[2]);
    expect(review(good, "easy", NOW).box).toBe(4);
    expect(review(good, "again", NOW).box).toBe(1);
    expect(review(good, "good", NOW).reviews).toBe(2);
  });

  it("caps at the last box", () => {
    let card = review(undefined, "easy", NOW);
    for (let i = 0; i < 5; i++) card = review(card, "easy", NOW);
    expect(card.box).toBe(MAX_BOX);
  });

  it("lists due cards and formats wait times", () => {
    const later = review(undefined, "good", NOW); // due in 1 day
    expect(dueIndexes([undefined, later, newCard()], NOW)).toEqual([0, 2]);
    expect(formatDue(later, NOW)).toBe("in 1 d");
    expect(formatDue(review(undefined, "again", NOW), NOW)).toBe("in 10 min");
  });
});

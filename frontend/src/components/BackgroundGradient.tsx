/** Calm, static backdrop: two soft brand-colored glows on a clean base. Purely decorative. */
export function BackgroundGradient() {
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 -z-10 bg-background"
      style={{
        backgroundImage: [
          "radial-gradient(60rem 40rem at 0% 0%, hsl(var(--glow-1) / var(--glow-opacity)), transparent 70%)",
          "radial-gradient(50rem 36rem at 100% 100%, hsl(var(--glow-2) / var(--glow-opacity)), transparent 70%)",
        ].join(", "),
      }}
    />
  );
}

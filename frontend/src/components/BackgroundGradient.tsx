/** Soft animated gradient blobs behind the glass UI. Purely decorative. */
export function BackgroundGradient() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,hsl(var(--primary)/0.10),transparent_60%)]" />
      <div className="absolute -left-32 -top-32 size-[28rem] animate-blob rounded-full bg-violet-400/30 blur-3xl dark:bg-violet-600/20" />
      <div className="absolute -right-24 top-1/3 size-[24rem] animate-blob rounded-full bg-cyan-300/30 blur-3xl [animation-delay:-6s] dark:bg-cyan-500/15" />
      <div className="absolute bottom-[-8rem] left-1/3 size-[26rem] animate-blob rounded-full bg-fuchsia-300/25 blur-3xl [animation-delay:-12s] dark:bg-fuchsia-600/15" />
      <div className="absolute inset-0 bg-[linear-gradient(to_right,hsl(var(--foreground)/0.03)_1px,transparent_1px),linear-gradient(to_bottom,hsl(var(--foreground)/0.03)_1px,transparent_1px)] bg-[size:48px_48px] [mask-image:radial-gradient(ellipse_at_center,black_30%,transparent_75%)]" />
    </div>
  );
}

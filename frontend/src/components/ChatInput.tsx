import { motion } from "framer-motion";
import { ArrowUp, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { CHAT_INPUT_ID } from "@/hooks/useKeyboardShortcuts";
import { cn } from "@/lib/utils";

const MAX_CHARS = 4000;

export function ChatInput({
  onSend,
  onStop,
  streaming,
  disabled,
}: {
  onSend: (text: string) => void;
  onStop: () => void;
  streaming: boolean;
  disabled?: boolean;
}) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const submit = () => {
    if (!value.trim() || streaming || disabled) return;
    onSend(value);
    setValue("");
  };

  return (
    <div className="glass rounded-2xl p-2 transition-shadow focus-within:ring-2 focus-within:ring-primary/40">
      <div className="flex items-end gap-2">
        <label htmlFor={CHAT_INPUT_ID} className="sr-only">
          Ask about the document
        </label>
        <textarea
          id={CHAT_INPUT_ID}
          ref={ref}
          rows={1}
          value={value}
          maxLength={MAX_CHARS}
          disabled={disabled}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Ask anything about your PDF… (English, اردو, Roman Urdu)"
          className="max-h-[200px] min-h-[44px] flex-1 resize-none bg-transparent px-3 py-2.5 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-50"
        />
        {streaming ? (
          <Button size="icon" variant="secondary" onClick={onStop} aria-label="Stop generating" className="mb-0.5 rounded-xl">
            <Square className="fill-current" />
          </Button>
        ) : (
          <motion.div whileTap={{ scale: 0.9 }} className="mb-0.5">
            <Button size="icon" onClick={submit} disabled={!value.trim() || disabled} aria-label="Send message" className="rounded-xl">
              <ArrowUp />
            </Button>
          </motion.div>
        )}
      </div>
      <div className={cn("hidden items-center justify-between px-3 pb-0.5 pt-1 text-[11px] text-muted-foreground sm:flex")}>
        <span className="flex items-center gap-1">
          <Kbd>Enter</Kbd> send · <Kbd>Shift</Kbd>+<Kbd>Enter</Kbd> new line · <Kbd>?</Kbd> shortcuts
        </span>
        {value.length > MAX_CHARS * 0.8 && <span className="tabular-nums">{value.length}/{MAX_CHARS}</span>}
      </div>
    </div>
  );
}

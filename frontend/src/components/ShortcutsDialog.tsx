import { Modal } from "@/components/Modal";
import { Kbd } from "@/components/ui/kbd";
import { SHORTCUTS } from "@/hooks/useKeyboardShortcuts";
import { modKey } from "@/lib/utils";
import { useAppStore } from "@/store/useAppStore";

export function ShortcutsDialog() {
  const open = useAppStore((s) => s.shortcutsOpen);
  const setOpen = useAppStore((s) => s.setShortcutsOpen);
  return (
    <Modal open={open} onClose={() => setOpen(false)} title="Keyboard shortcuts">
      <ul className="divide-y divide-border/60">
        {SHORTCUTS.map((s) => (
          <li key={s.label + s.keys.join()} className="flex items-center justify-between py-2.5 text-sm">
            <span className="text-muted-foreground">{s.label}</span>
            <span className="flex items-center gap-1">
              {s.keys.map((k) => (
                <Kbd key={k}>{k === "Mod" ? modKey : k}</Kbd>
              ))}
            </span>
          </li>
        ))}
      </ul>
    </Modal>
  );
}

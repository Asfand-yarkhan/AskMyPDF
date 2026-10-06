import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "@/api/client";
import type { Health } from "@/api/types";
import { useAppStore } from "@/store/useAppStore";

export function useDocuments() {
  const setDocuments = useAppStore((s) => s.setDocuments);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setDocuments(await api.listDocuments());
      setError(null);
    } catch (err) {
      setError((err as Error).message);
      setDocuments(useAppStore.getState().documents);
    }
  }, [setDocuments]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { refresh, error };
}

export function useDeleteDocument() {
  const removeDocument = useAppStore((s) => s.removeDocument);
  return useCallback(
    async (id: string, name: string) => {
      try {
        await api.deleteDocument(id);
        removeDocument(id);
        toast.success(`Deleted "${name}"`);
      } catch (err) {
        toast.error((err as Error).message);
      }
    },
    [removeDocument],
  );
}

export function useHealth() {
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    let alive = true;
    const check = () =>
      api
        .health()
        .then((h) => alive && (setHealth(h), setOffline(false)))
        .catch(() => alive && setOffline(true));
    void check();
    const timer = window.setInterval(check, 30_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);
  return { health, offline };
}

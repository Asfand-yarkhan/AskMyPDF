import { createContext, useContext } from "react";
import type { SourceChunk } from "@/api/types";

/** What a citation chip needs to know about the answer it sits in. */
export interface CitationScope {
  /** Documents the answer was generated from, in order: [Doc 1, ...]. */
  docIds: string[];
  /** Passages the answer was generated from (for hover previews). */
  sources: SourceChunk[];
}

export const CitationContext = createContext<CitationScope>({ docIds: [], sources: [] });

export const useCitationScope = () => useContext(CitationContext);

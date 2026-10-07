import { memo } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { CitationChip } from "@/components/CitationChip";
import { linkifyCitations, parseCiteHref } from "@/lib/utils";

const urlTransform = (url: string) => (url.startsWith("cite:") ? url : defaultUrlTransform(url));

export const Markdown = memo(function Markdown({ content }: { content: string }) {
  return (
    <div className="prose prose-sm max-w-none break-words dark:prose-invert prose-headings:tracking-tight prose-p:leading-relaxed prose-a:text-primary prose-code:rounded prose-code:bg-muted prose-code:px-1 prose-code:before:content-none prose-code:after:content-none prose-pre:rounded-xl prose-pre:bg-muted prose-pre:text-foreground prose-table:text-xs prose-th:bg-muted/60 prose-th:px-2 prose-td:px-2">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={urlTransform}
        components={{
          a({ href, children }) {
            const cite = href ? parseCiteHref(href) : null;
            if (cite) {
              return <CitationChip page={cite.page} docNumber={cite.doc} label={String(children)} />;
            }
            return (
              <a href={href} target="_blank" rel="noreferrer noopener">
                {children}
              </a>
            );
          },
          table({ children }) {
            return (
              <div className="not-prose my-3 overflow-x-auto rounded-xl border border-border scrollbar-thin">
                <table className="w-full text-left text-xs [&_td]:border-t [&_td]:border-border [&_td]:px-3 [&_td]:py-2 [&_th]:bg-muted/60 [&_th]:px-3 [&_th]:py-2 [&_th]:font-semibold">
                  {children}
                </table>
              </div>
            );
          },
        }}
      >
        {linkifyCitations(content)}
      </ReactMarkdown>
    </div>
  );
});

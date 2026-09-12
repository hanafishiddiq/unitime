"use client";

import React, { useState, createContext, useContext, useMemo } from "react";
import ReactMarkdown, { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import { Copy, Check, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";

export interface AiResponseParserProps {
  content: string;
  isUser?: boolean;
  className?: string;
}

const CodeBlockContext = createContext<boolean>(false);

/**
 * Safely extracts raw plain text from React nodes (used for copying code to clipboard).
 */
function extractText(node: React.ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (!node) return "";
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (React.isValidElement(node)) {
    const props = node.props as { children?: React.ReactNode };
    if (props && props.children) {
      return extractText(props.children);
    }
  }
  return "";
}

/**
 * Fenced code block with header, language indicator, and copy-to-clipboard action.
 */
interface CodeBlockProps {
  children: React.ReactNode;
  language?: string;
  rawCode: string;
  isUser?: boolean;
}

function CodeBlock({ children, language, rawCode, isUser = false }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(rawCode.trimEnd());
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard fallback
    }
  };

  return (
    <div
      className={cn(
        "my-2 rounded-lg border overflow-hidden text-xs",
        isUser
          ? "border-primary-foreground/25 bg-black/20 text-primary-foreground"
          : "border-border/70 bg-muted/70 dark:bg-zinc-950/80 text-foreground"
      )}
    >
      {/* Code Header Bar */}
      <div
        className={cn(
          "flex items-center justify-between px-3 py-1.5 border-b text-[10px] font-mono select-none",
          isUser
            ? "border-primary-foreground/20 bg-primary-foreground/10 text-primary-foreground/90"
            : "border-border/60 bg-muted/90 dark:bg-zinc-900 text-muted-foreground"
        )}
      >
        <span
          className={cn(
            "font-semibold uppercase tracking-wider",
            isUser ? "text-primary-foreground" : "text-emerald-600 dark:text-emerald-400"
          )}
        >
          {language || "code"}
        </span>
        <button
          type="button"
          onClick={handleCopy}
          aria-label={copied ? "Code copied to clipboard" : "Copy code"}
          className={cn(
            "inline-flex items-center gap-1 px-1.5 py-0.5 rounded transition-colors text-[10px]",
            isUser
              ? "hover:bg-primary-foreground/20 text-primary-foreground"
              : "hover:bg-background/80 text-muted-foreground hover:text-foreground"
          )}
        >
          {copied ? (
            <>
              <Check className="h-3 w-3 text-emerald-500" />
              <span className="text-emerald-500 font-medium">Copied!</span>
            </>
          ) : (
            <>
              <Copy className="h-3 w-3" />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Code Content */}
      <div className="p-2.5 overflow-x-auto font-mono text-[11px] leading-relaxed">
        {children}
      </div>
    </div>
  );
}

/**
 * Normalizes raw LLM markdown and WhatsApp-flavored text formatting
 * into clean, standard GitHub Flavored Markdown without leaking stray asterisks
 * or collapsing single line breaks.
 */
export function normalizeMarkdownText(raw: string): string {
  if (!raw || typeof raw !== "string") return "";

  // Step 1: Protect fenced code blocks (```...```) and inline code (`...`)
  const codeBlocks: string[] = [];
  let text = raw.replace(/```[\s\S]*?```/g, (match) => {
    codeBlocks.push(match);
    return `___UNITIME_CODE_BLOCK_${codeBlocks.length - 1}___`;
  });

  const inlineCodes: string[] = [];
  text = text.replace(/`[^`\n]+`/g, (match) => {
    inlineCodes.push(match);
    return `___UNITIME_INLINE_CODE_${inlineCodes.length - 1}___`;
  });

  // Step 2: Normalize unicode bullet points and special bullet characters at line starts
  // e.g. "• ", "● ", "○ ", "■ ", "▪ ", "– " -> "- "
  text = text.replace(/^(\s*)[•●○■▪–]\s+/gm, "$1- ");

  // Normalize arrow bullets "-> " or "=> " at line starts to "- "
  text = text.replace(/^(\s*)(?:->|=>)\s+/gm, "$1- ");

  // Step 3: Convert standard list bullets "* " to "- " at line starts
  // This cleanly disambiguates list bullets from bold asterisks completely!
  text = text.replace(/^(\s*)\*\s+/gm, "$1- ");

  // Step 4: Normalize WhatsApp strikethrough ~text~ to ~~text~~ if not already ~~
  text = text.replace(/(?<!~)\~([^~\n\r]+?)\~(?!~)/g, "~~$1~~");

  // Step 5: Fix lopsided/mismatched asterisks e.g. **text* or *text** -> **text**
  text = text.replace(/\*{2,}([^*\n\r]+?)\*(?!\*)/g, "**$1**");
  text = text.replace(/(?<!\*)\*([^*\n\r]+?)\*{2,}/g, "**$1**");

  // Step 6: Convert WhatsApp bold *text* into standard markdown **text**
  // Opening asterisk is preceded by start of string, whitespace, or punctuation
  // Closing asterisk is preceded by non-space and followed by end of string, whitespace, or punctuation
  // Avoid matching math expressions like "5 * 10 = 50" where asterisk is surrounded by spaces.
  text = text.replace(
    /(^|[\s([{\'".,;:!?~>_])\*([^\s*](?:[^*\r\n]*?[^\s*])?)\*(?=[\s)\]}\'".,;:!?~<_]|$)/gm,
    "$1**$2**"
  );

  // Step 7: Handle unclosed asterisks and stray asterisks on a line-by-line basis
  const lines = text.split("\n");
  const processedLines: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];

    // Remove stray trailing single or double asterisks with space before: e.g. "teks *" -> "teks"
    line = line.replace(/\s+\*+$/, "");

    // Check for unclosed double asterisks e.g. "**Catatan: Ruang penuh"
    const doubleAsteriskMatches = line.match(/\*\*/g) || [];
    if (doubleAsteriskMatches.length % 2 !== 0) {
      line = line.trimEnd() + "**";
    }

    // Check for unclosed single asterisk attached to word at beginning: e.g. "*Heading"
    const singleAttachedStart = /^\s*\*([^\s*][^*\n]*)$/.test(line);
    if (singleAttachedStart) {
      line = line.trimEnd() + "**";
    }

    // List separation check:
    // If current line is a list item and previous line is non-empty, non-list text,
    // insert a blank line before this list item so CommonMark parses it cleanly.
    const isCurrentList = /^\s*(?:[-*+]|\d+[.)])\s+/.test(line);
    const prevLine = i > 0 ? lines[i - 1] : "";
    const isPrevNonListText =
      prevLine.trim().length > 0 &&
      !/^\s*(?:[-*+]|\d+[.)])\s+/.test(prevLine);

    if (isCurrentList && isPrevNonListText) {
      processedLines.push("");
    }

    processedLines.push(line);
  }

  text = processedLines.join("\n");

  // Step 8: Restore protected code blocks and inline code snippets
  text = text.replace(
    /___UNITIME_INLINE_CODE_(\d+)___/g,
    (_, idx) => inlineCodes[Number(idx)] || ""
  );
  text = text.replace(
    /___UNITIME_CODE_BLOCK_(\d+)___/g,
    (_, idx) => codeBlocks[Number(idx)] || ""
  );

  return text;
}

/**
 * AiResponseParser
 * Render rich Markdown responses (bold, lists, tables, inline code, code blocks, headers)
 * with Tailwind styling, dark mode support, anti-slop list bullets, and WhatsApp ergonomics.
 */
export const AiResponseParser = React.memo(function AiResponseParser({
  content,
  isUser = false,
  className,
}: AiResponseParserProps) {
  // Preprocess and normalize text so that raw asterisks or unparsed markers don't leak
  const normalizedContent = useMemo(
    () => normalizeMarkdownText(content),
    [content]
  );

  const components: Components = useMemo(
    () => ({
      // Paragraph
      p: ({ children }) => (
        <p
          className={cn(
            "leading-relaxed mb-2 last:mb-0 break-words",
            isUser ? "text-primary-foreground" : "text-foreground"
          )}
        >
          {children}
        </p>
      ),

      // Text formatting
      strong: ({ children }) => (
        <strong
          className={cn(
            "font-semibold tracking-tight",
            isUser
              ? "text-primary-foreground font-bold"
              : "text-foreground font-semibold dark:text-zinc-100"
          )}
        >
          {children}
        </strong>
      ),
      em: ({ children }) => (
        <em
          className={cn(
            "italic",
            isUser ? "text-primary-foreground/95" : "text-foreground/90 dark:text-zinc-200"
          )}
        >
          {children}
        </em>
      ),
      del: ({ children }) => (
        <del
          className={cn(
            "line-through opacity-75",
            isUser ? "text-primary-foreground/80" : "text-muted-foreground"
          )}
        >
          {children}
        </del>
      ),

      // Headings
      h1: ({ children }) => (
        <h1
          className={cn(
            "text-sm font-bold mt-3 mb-1.5 first:mt-0 tracking-tight flex items-center gap-1.5",
            isUser ? "text-primary-foreground" : "text-foreground"
          )}
        >
          {children}
        </h1>
      ),
      h2: ({ children }) => (
        <h2
          className={cn(
            "text-xs font-bold mt-2.5 mb-1 first:mt-0 tracking-tight",
            isUser ? "text-primary-foreground" : "text-foreground"
          )}
        >
          {children}
        </h2>
      ),
      h3: ({ children }) => (
        <h3
          className={cn(
            "text-xs font-semibold mt-2 mb-1 first:mt-0",
            isUser ? "text-primary-foreground" : "text-foreground"
          )}
        >
          {children}
        </h3>
      ),
      h4: ({ children }) => (
        <h4
          className={cn(
            "text-[11px] font-semibold mt-1.5 mb-0.5 first:mt-0",
            isUser ? "text-primary-foreground" : "text-foreground"
          )}
        >
          {children}
        </h4>
      ),

      // Lists with explicit Tailwind list-style and custom colored markers
      ul: ({ children }) => (
        <ul
          className={cn(
            "list-disc list-outside ml-5 pl-1 my-1.5 space-y-1",
            isUser
              ? "[&>li::marker]:text-primary-foreground/80"
              : "[&>li::marker]:text-emerald-500 dark:[&>li::marker]:text-emerald-400"
          )}
        >
          {children}
        </ul>
      ),
      ol: ({ children }) => (
        <ol
          className={cn(
            "list-decimal list-outside ml-5 pl-1 my-1.5 space-y-1 font-normal",
            isUser
              ? "[&>li::marker]:text-primary-foreground/85 [&>li::marker]:font-semibold"
              : "[&>li::marker]:text-emerald-600 dark:[&>li::marker]:text-emerald-400 [&>li::marker]:font-semibold"
          )}
        >
          {children}
        </ol>
      ),
      li: ({ children }) => (
        <li
          className={cn(
            "leading-relaxed pl-0.5 break-words",
            isUser ? "text-primary-foreground" : "text-foreground"
          )}
        >
          {children}
        </li>
      ),

      // Blockquote
      blockquote: ({ children }) => (
        <blockquote
          className={cn(
            "border-l-[3px] pl-3.5 py-1 my-2 rounded-r text-xs italic",
            isUser
              ? "border-primary-foreground/70 bg-primary-foreground/10 text-primary-foreground"
              : "border-emerald-500/80 dark:border-emerald-400 bg-emerald-500/5 dark:bg-emerald-500/10 text-muted-foreground"
          )}
        >
          {children}
        </blockquote>
      ),

      // Table & Children (GFM)
      table: ({ children }) => (
        <div className="overflow-x-auto my-2 rounded-lg border border-border text-[11px]">
          <table className="w-full text-left border-collapse">{children}</table>
        </div>
      ),
      thead: ({ children }) => (
        <thead
          className={cn(
            "border-b font-semibold",
            isUser
              ? "border-primary-foreground/20 bg-primary-foreground/15 text-primary-foreground"
              : "border-border bg-muted/80 dark:bg-muted/60 text-foreground"
          )}
        >
          {children}
        </thead>
      ),
      tbody: ({ children }) => (
        <tbody
          className={cn(
            "divide-y",
            isUser ? "divide-primary-foreground/15" : "divide-border/40"
          )}
        >
          {children}
        </tbody>
      ),
      tr: ({ children }) => (
        <tr
          className={cn(
            "transition-colors",
            isUser
              ? "hover:bg-primary-foreground/10 odd:bg-transparent even:bg-primary-foreground/5"
              : "hover:bg-muted/40 odd:bg-transparent even:bg-muted/15"
          )}
        >
          {children}
        </tr>
      ),
      th: ({ children }) => (
        <th className="px-3 py-1.5 font-semibold align-middle whitespace-nowrap">
          {children}
        </th>
      ),
      td: ({ children }) => (
        <td className="px-3 py-1.5 align-top leading-normal">
          {children}
        </td>
      ),

      // Pre & Code
      pre: ({ children }) => {
        let language = "";
        if (React.isValidElement(children)) {
          const codeProps = children.props as { className?: string };
          const match = /language-(\w+)/.exec(codeProps.className || "");
          if (match) language = match[1];
        }
        const rawCode = extractText(children);

        return (
          <CodeBlockContext.Provider value={true}>
            <CodeBlock language={language} rawCode={rawCode} isUser={isUser}>
              {children}
            </CodeBlock>
          </CodeBlockContext.Provider>
        );
      },
      code: ({ className, children }) => {
        const isBlock = useContext(CodeBlockContext);

        if (isBlock) {
          return (
            <code className={cn("font-mono text-[11px] whitespace-pre", className)}>
              {children}
            </code>
          );
        }

        return (
          <code
            className={cn(
              "px-1.5 py-0.5 rounded font-mono text-[11px] border break-all",
              isUser
                ? "bg-primary-foreground/20 text-primary-foreground border-primary-foreground/30"
                : "bg-muted/80 text-emerald-600 dark:text-emerald-400 border-border/60",
              className
            )}
          >
            {children}
          </code>
        );
      },

      // Links
      a: ({ href, children }) => (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className={cn(
            "underline underline-offset-2 font-medium transition-colors inline-flex items-center gap-0.5",
            isUser
              ? "text-primary-foreground hover:opacity-85"
              : "text-emerald-600 dark:text-emerald-400 hover:text-emerald-700 dark:hover:text-emerald-300"
          )}
        >
          <span>{children}</span>
          <ExternalLink className="h-2.5 w-2.5 opacity-70 shrink-0 inline-block" />
        </a>
      ),

      // Divider
      hr: () => (
        <hr
          className={cn(
            "my-2",
            isUser ? "border-primary-foreground/25" : "border-border/60"
          )}
        />
      ),
    }),
    [isUser]
  );

  if (!content || !content.trim()) {
    return null;
  }

  return (
    <div className={cn("text-xs leading-relaxed", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks]}
        components={components}
      >
        {normalizedContent}
      </ReactMarkdown>
    </div>
  );
});

export default AiResponseParser;

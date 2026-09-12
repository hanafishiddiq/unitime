"use client";

import React, { useState, useRef, useEffect } from "react";
import {
  Send,
  Paperclip,
  Sparkles,
  Bot,
  User,
  FileText,
  CheckCircle2,
  AlertCircle,
  Clock,
  ArrowUpRight,
  RefreshCw,
  FolderUp,
  Wrench,
  BrainCircuit,
} from "lucide-react";
import { JobStatusResponse } from "@/lib/api";
import { formatBytes } from "@/lib/utils";
import { AiResponseParser } from "@/components/AiResponseParser";

export interface ChatMessage {
  id: string;
  sender: "user" | "assistant" | "system";
  text: string;
  timestamp: string;
  attachment?: {
    name: string;
    size: number;
    type: string;
  };
  tools_used?: string[];
  thought_process?: string[];
}

interface ChatInterfaceProps {
  messages: ChatMessage[];
  onSendMessage: (text: string) => void;
  onUploadFile: (file: File) => void;
  isUploading: boolean;
  isThinking?: boolean;
  jobStatus: JobStatusResponse | null;
  onSelectPrompt: (promptText: string) => void;
}

const QUICK_PROMPTS = [
  "Cek kapasitas ruangan LABTEK V 7601 untuk 70 mahasiswa",
  "Cek apakah ada benturan waktu di jadwal aktif",
  "Cek status server UniTime",
  "Unggah dokumen kurikulum semester ganjil",
];

const ALLOWED_EXTENSIONS = [
  ".pdf",
  ".xlsx",
  ".xlsm",
  ".xls",
  ".csv",
  ".tsv",
  ".txt",
  ".md",
  ".json",
];

export function ChatInterface({
  messages,
  onSendMessage,
  onUploadFile,
  isUploading,
  isThinking = false,
  jobStatus,
  onSelectPrompt,
}: ChatInterfaceProps) {
  const [inputText, setInputText] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isUploading, isThinking]);

  const handleSend = () => {
    if (!inputText.trim() || isUploading) return;
    onSendMessage(inputText.trim());
    setInputText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      onUploadFile(file);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      onUploadFile(file);
    }
  };

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`flex flex-col h-full bg-card rounded-2xl border transition-all duration-200 overflow-hidden relative ${
        isDragging
          ? "border-emerald-500 ring-2 ring-emerald-500/20 bg-emerald-500/5"
          : "border-border shadow-sm"
      }`}
    >
      {/* Hidden File Input */}
      <input
        ref={fileInputRef}
        type="file"
        accept={ALLOWED_EXTENSIONS.join(",")}
        onChange={handleFileChange}
        className="hidden"
      />

      {/* Chat Header */}
      <div className="px-5 py-3.5 border-b border-border bg-muted/20 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
            <Bot className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
              <span>UniTime Ingestion Assistant</span>
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            </h3>
            <p className="text-[11px] text-muted-foreground">
              Autonomous Academic Curriculum Agent
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={isUploading}
          className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-lg border border-border bg-background hover:bg-muted text-foreground transition-colors disabled:opacity-50"
        >
          <FolderUp className="h-3 w-3 text-muted-foreground" />
          <span>Upload File</span>
        </button>
      </div>

      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto p-3.5 space-y-2.5 text-xs">
        {messages.map((msg) => {
          const isUser = msg.sender === "user";
          const hasExtras = Boolean(
            msg.attachment ||
            (msg.tools_used && msg.tools_used.length > 0) ||
            (msg.thought_process && msg.thought_process.length > 0)
          );
          const displayText = msg.text ? msg.text.trimEnd() : "";

          return (
            <div
              key={msg.id}
              className={`flex items-start gap-2 ${
                isUser ? "flex-row-reverse" : "flex-row"
              } animate-in fade-in duration-200`}
            >
              {/* Avatar */}
              <div
                className={`h-7 w-7 rounded-xl flex items-center justify-center shrink-0 text-xs font-bold mt-0.5 shadow-xs ${
                  isUser
                    ? "bg-primary text-primary-foreground"
                    : "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20"
                }`}
              >
                {isUser ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
              </div>

              {/* Chat Bubble */}
              <div
                className={`w-fit min-w-[70px] max-w-[85%] sm:max-w-[80%] rounded-2xl px-3.5 py-2 text-xs shadow-xs transition-all ${
                  isUser
                    ? "bg-primary text-primary-foreground rounded-tr-sm"
                    : "bg-muted/50 dark:bg-muted/30 text-foreground border border-border/80 rounded-tl-sm"
                }`}
              >
                <div className="space-y-1.5">
                  {displayText && (
                    <AiResponseParser content={displayText} isUser={isUser} />
                  )}

                  {/* Attachment Badge */}
                  {msg.attachment && (
                    <div
                      className={`flex items-center gap-2 px-2.5 py-1.5 rounded-xl text-[11px] font-mono ${
                        isUser
                          ? "bg-primary-foreground/15 text-primary-foreground border border-primary-foreground/20"
                          : "bg-background text-foreground border border-border/70"
                      }`}
                    >
                      <FileText
                        className={`h-3.5 w-3.5 shrink-0 ${
                          isUser ? "text-primary-foreground" : "text-emerald-500"
                        }`}
                      />
                      <span className="truncate max-w-[170px] font-medium">
                        {msg.attachment.name}
                      </span>
                      <span className="text-[10px] opacity-75 shrink-0">
                        ({formatBytes(msg.attachment.size)})
                      </span>
                    </div>
                  )}

                  {/* Tools Used Badges */}
                  {msg.tools_used && msg.tools_used.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1 pt-1.5 border-t border-border/40">
                      <span className="text-[10px] text-muted-foreground flex items-center gap-1 font-mono shrink-0">
                        <Wrench className="h-2.5 w-2.5 text-emerald-500" /> Tools:
                      </span>
                      {msg.tools_used.map((tool, idx) => (
                        <span
                          key={idx}
                          className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20"
                        >
                          {tool}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* ReAct Thought Process Collapsible */}
                  {msg.thought_process && msg.thought_process.length > 0 && (
                    <details className="text-[11px] text-muted-foreground bg-muted/40 rounded-lg p-1.5 cursor-pointer border border-border/50">
                      <summary className="font-mono text-[10px] text-emerald-600 dark:text-emerald-400 select-none flex items-center gap-1 hover:underline">
                        <BrainCircuit className="h-3 w-3" /> ReAct Reasoning ({msg.thought_process.length} langkah)
                      </summary>
                      <div className="mt-1.5 space-y-1.5 pl-2 border-l border-emerald-500/30 font-mono text-[10px]">
                        {msg.thought_process.map((t, idx) => (
                          <div key={idx} className="text-muted-foreground/90 leading-relaxed">
                            <AiResponseParser content={t} className="text-[10px]" />
                          </div>
                        ))}
                      </div>
                    </details>
                  )}

                  {/* Timestamp with Clearance */}
                  <div
                    suppressHydrationWarning
                    className={`flex items-center justify-end text-[10px] font-mono select-none leading-none pt-0.5 tracking-tight ${
                      isUser ? "text-primary-foreground/75" : "text-muted-foreground/75"
                    }`}
                  >
                    {msg.timestamp}
                  </div>
                </div>
              </div>
            </div>
          );
        })}

        {/* Uploading indicator */}
        {isUploading && (
          <div className="flex items-center gap-2 text-muted-foreground text-xs py-1 px-2">
            <RefreshCw className="h-3.5 w-3.5 animate-spin text-emerald-500" />
            <span>Analyzing document & initializing pipeline...</span>
          </div>
        )}

        {/* ReAct Thinking indicator */}
        {isThinking && (
          <div className="flex items-start gap-2 flex-row animate-in fade-in duration-200">
            <div className="h-7 w-7 rounded-xl flex items-center justify-center shrink-0 text-xs font-bold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 mt-0.5 shadow-xs">
              <Bot className="h-3.5 w-3.5" />
            </div>
            <div className="w-fit max-w-[85%] sm:max-w-[80%] rounded-2xl rounded-tl-sm px-3.5 py-2 bg-muted/50 dark:bg-muted/30 text-foreground border border-border/80 flex items-center gap-2 text-xs shadow-xs">
              <RefreshCw className="h-3.5 w-3.5 animate-spin text-emerald-500 shrink-0" />
              <span className="text-muted-foreground">ReAct Agent sedang bernalar & mengeksekusi tools...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Quick Prompt Suggestions */}
      <div className="px-4 py-2 border-t border-border/60 bg-muted/10">
        <div className="flex items-center gap-1.5 mb-1.5">
          <Sparkles className="h-3 w-3 text-emerald-500" />
          <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
            Quick Prompts
          </span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {QUICK_PROMPTS.map((prompt, i) => (
            <button
              key={i}
              type="button"
              onClick={() => onSelectPrompt(prompt)}
              disabled={isUploading || isThinking}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-background border border-border/80 hover:border-emerald-500/40 hover:bg-emerald-500/5 text-[11px] text-muted-foreground hover:text-foreground transition-all duration-150 text-left disabled:opacity-50"
            >
              <span>{prompt}</span>
              <ArrowUpRight className="h-2.5 w-2.5 opacity-60" />
            </button>
          ))}
        </div>
      </div>

      {/* Input Bar */}
      <div className="p-3 border-t border-border bg-background flex items-center gap-2">
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={isUploading || isThinking}
          className="p-2 rounded-xl border border-border bg-card hover:bg-muted text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
          title="Attach PDF, Excel, CSV, TXT, or JSON"
        >
          <Paperclip className="h-4 w-4" />
        </button>

        <input
          type="text"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Tanya jadwal, instruksi kurikulum, atau uji ReAct tools..."
          disabled={isUploading || isThinking}
          className="flex-1 text-xs rounded-xl border border-input bg-card px-3.5 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
        />

        <button
          type="button"
          onClick={handleSend}
          disabled={!inputText.trim() || isUploading || isThinking}
          className="p-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white transition-colors disabled:opacity-40"
          title="Send message"
        >
          <Send className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

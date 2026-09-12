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
} from "lucide-react";
import { JobStatusResponse } from "@/lib/api";
import { formatBytes } from "@/lib/utils";

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
}

interface ChatInterfaceProps {
  messages: ChatMessage[];
  onSendMessage: (text: string) => void;
  onUploadFile: (file: File) => void;
  isUploading: boolean;
  jobStatus: JobStatusResponse | null;
  onSelectPrompt: (promptText: string) => void;
}

const QUICK_PROMPTS = [
  "Unggah jadwal Prodi IF Semester Ganjil",
  "Ekstrak silabus RPS & distribusi kelas",
  "Cek status sinkronisasi UniTime",
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
  jobStatus,
  onSelectPrompt,
}: ChatInterfaceProps) {
  const [inputText, setInputText] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isUploading]);

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
      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
        {messages.map((msg) => {
          const isUser = msg.sender === "user";
          return (
            <div
              key={msg.id}
              className={`flex items-start gap-2.5 ${
                isUser ? "flex-row-reverse" : "flex-row"
              } animate-in fade-in duration-200`}
            >
              <div
                className={`h-7 w-7 rounded-lg flex items-center justify-center shrink-0 text-xs font-bold ${
                  isUser
                    ? "bg-primary text-primary-foreground"
                    : "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20"
                }`}
              >
                {isUser ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
              </div>

              <div
                className={`max-w-[85%] rounded-2xl p-3.5 space-y-2 ${
                  isUser
                    ? "bg-primary text-primary-foreground rounded-tr-none"
                    : "bg-muted/40 text-foreground border border-border/80 rounded-tl-none"
                }`}
              >
                {/* Text Content */}
                <p className="leading-relaxed whitespace-pre-wrap">{msg.text}</p>

                {/* Attachment Badge */}
                {msg.attachment && (
                  <div
                    className={`flex items-center gap-2 p-2 rounded-xl text-[11px] font-mono ${
                      isUser
                        ? "bg-primary-foreground/10 text-primary-foreground border border-primary-foreground/20"
                        : "bg-background text-foreground border border-border"
                    }`}
                  >
                    <FileText className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
                    <span className="truncate max-w-[150px]">
                      {msg.attachment.name}
                    </span>
                    <span className="text-[10px] opacity-75">
                      ({formatBytes(msg.attachment.size)})
                    </span>
                  </div>
                )}

                <div
                  className={`text-[9px] text-right font-mono ${
                    isUser ? "text-primary-foreground/70" : "text-muted-foreground"
                  }`}
                >
                  {msg.timestamp}
                </div>
              </div>
            </div>
          );
        })}

        {/* Uploading indicator */}
        {isUploading && (
          <div className="flex items-center gap-2 text-muted-foreground text-xs p-2">
            <RefreshCw className="h-3.5 w-3.5 animate-spin text-emerald-500" />
            <span>Analyzing document & initializing pipeline...</span>
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
              disabled={isUploading}
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
          disabled={isUploading}
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
          placeholder="Ask assistant or type scheduling instructions..."
          disabled={isUploading}
          className="flex-1 text-xs rounded-xl border border-input bg-card px-3.5 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
        />

        <button
          type="button"
          onClick={handleSend}
          disabled={!inputText.trim() || isUploading}
          className="p-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white transition-colors disabled:opacity-40"
          title="Send message"
        >
          <Send className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

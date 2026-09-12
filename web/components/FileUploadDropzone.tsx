"use client";

import React, { useState, useRef, DragEvent, ChangeEvent } from "react";
import {
  UploadCloud,
  FileSpreadsheet,
  FileCode,
  FileText,
  Check,
  AlertCircle,
  X,
  Sliders,
  Sparkles,
} from "lucide-react";
import { UploadOptions } from "@/lib/api";
import { formatBytes } from "@/lib/utils";

const ACCEPTED_EXTENSIONS = [
  ".pdf",
  ".xlsx",
  ".xlsm",
  ".xls",
  ".csv",
  ".tsv",
  ".txt",
  ".md",
  ".json",
  ".log",
];

interface FileUploadDropzoneProps {
  onStartUpload: (file: File, options: UploadOptions) => void;
  isUploading: boolean;
  disabled?: boolean;
}

export function FileUploadDropzone({
  onStartUpload,
  isUploading,
  disabled = false,
}: FileUploadDropzoneProps) {
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Ingestion Options
  const [provider, setProvider] = useState<string>("gemini");
  const [model, setModel] = useState<string>("");
  const [dryRun, setDryRun] = useState<boolean>(true);
  const [strict, setStrict] = useState<boolean>(false);
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const validateAndSetFile = (file: File) => {
    setError(null);
    const suffix = "." + file.name.split(".").pop()?.toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(suffix)) {
      setError(
        `Unsupported file format "${suffix}". Supported: ${ACCEPTED_EXTENSIONS.join(
          ", "
        )}`
      );
      return;
    }
    setSelectedFile(file);
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (disabled || isUploading) return;
    setDragOver(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (disabled || isUploading) return;

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      validateAndSetFile(e.target.files[0]);
    }
  };

  const handleClearFile = () => {
    setSelectedFile(null);
    setError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleUploadSubmit = () => {
    if (!selectedFile || isUploading) return;

    const options: UploadOptions = {
      provider,
      dryRun,
      strict,
    };
    if (model.trim()) {
      options.model = model.trim();
    }

    onStartUpload(selectedFile, options);
  };

  const getFileIcon = (filename: string) => {
    const ext = filename.split(".").pop()?.toLowerCase();
    if (ext === "json") return <FileCode className="h-8 w-8 text-sky-500" />;
    if (["xlsx", "xls", "csv", "tsv"].includes(ext || ""))
      return <FileSpreadsheet className="h-8 w-8 text-emerald-500" />;
    return <FileText className="h-8 w-8 text-amber-500" />;
  };

  return (
    <div className="bg-card border border-border rounded-xl shadow-sm overflow-hidden">
      <div className="p-6 border-b border-border/80 bg-muted/30">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-foreground tracking-tight">
              Curriculum Document Ingestion
            </h2>
            <p className="text-sm text-muted-foreground">
              Drop course schedules, curriculum Excel spreadsheets, syllabus PDFs,
              or canonical JSON.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border transition-colors ${
              showAdvanced
                ? "bg-primary/10 text-primary border-primary/20"
                : "border-border bg-background hover:bg-muted text-muted-foreground"
            }`}
          >
            <Sliders className="h-3.5 w-3.5" />
            <span>Options</span>
          </button>
        </div>

        {/* Ingestion Options Bar */}
        {showAdvanced && (
          <div className="mt-4 pt-4 border-t border-border grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 animate-in fade-in duration-200">
            {/* LLM Provider */}
            <div>
              <label className="block text-xs font-medium text-foreground mb-1">
                LLM Provider
              </label>
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                disabled={isUploading}
                className="w-full text-xs rounded-md border border-input bg-background px-2.5 py-1.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              >
                <option value="gemini">Google Gemini (gemini-flash-latest)</option>
                <option value="antigravity">Antigravity Gateway (VPS Live LLM)</option>
                <option value="openai">OpenAI GPT-4o</option>
                <option value="openrouter">OpenRouter / Anthropic</option>
                <option value="custom">Custom Provider</option>
                <option value="mock">Mock / Test Pipeline</option>
              </select>
            </div>

            {/* Custom Model */}
            <div>
              <label className="block text-xs font-medium text-foreground mb-1">
                Model Override <span className="text-muted-foreground font-normal">(optional)</span>
              </label>
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                disabled={isUploading}
                placeholder="e.g. gemini-flash-latest"
                className="w-full text-xs rounded-md border border-input bg-background px-2.5 py-1.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            {/* Dry Run Toggle */}
            <div className="flex flex-col justify-end">
              <label className="flex items-center gap-2 cursor-pointer select-none text-xs font-medium text-foreground">
                <input
                  type="checkbox"
                  checked={dryRun}
                  onChange={(e) => setDryRun(e.target.checked)}
                  disabled={isUploading}
                  className="rounded border-input text-emerald-600 focus:ring-emerald-500 h-4 w-4"
                />
                <span>Dry Run Mode</span>
              </label>
              <span className="text-[11px] text-muted-foreground mt-0.5">
                Simulate without applying irreversible DB commits
              </span>
            </div>

            {/* Strict Validation Toggle */}
            <div className="flex flex-col justify-end">
              <label className="flex items-center gap-2 cursor-pointer select-none text-xs font-medium text-foreground">
                <input
                  type="checkbox"
                  checked={strict}
                  onChange={(e) => setStrict(e.target.checked)}
                  disabled={isUploading}
                  className="rounded border-input text-emerald-600 focus:ring-emerald-500 h-4 w-4"
                />
                <span>Strict Validation</span>
              </label>
              <span className="text-[11px] text-muted-foreground mt-0.5">
                Enforce strict schema &amp; capacity semantics
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Dropzone Area */}
      <div className="p-6">
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(",")}
          onChange={handleFileChange}
          className="hidden"
          disabled={disabled || isUploading}
        />

        {!selectedFile ? (
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-xl p-8 sm:p-12 text-center cursor-pointer transition-all ${
              dragOver
                ? "border-emerald-500 bg-emerald-500/5 scale-[0.99]"
                : "border-border hover:border-emerald-500/50 hover:bg-muted/40"
            }`}
          >
            <div className="mx-auto w-12 h-12 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center mb-3">
              <UploadCloud className="h-6 w-6" />
            </div>
            <p className="text-sm font-medium text-foreground">
              Click to browse or drag and drop your schedule file
            </p>
            <p className="text-xs text-muted-foreground mt-1.5">
              Supports PDF, Excel (.xlsx, .xls), CSV, JSON, and plain text memos
            </p>

            <div className="mt-4 flex flex-wrap items-center justify-center gap-1.5">
              {["PDF", "XLSX", "CSV", "JSON", "TXT"].map((ext) => (
                <span
                  key={ext}
                  className="text-[10px] font-medium px-2 py-0.5 rounded bg-muted text-muted-foreground border border-border"
                >
                  {ext}
                </span>
              ))}
            </div>
          </div>
        ) : (
          /* File Selected Card */
          <div className="border border-border rounded-xl p-4 sm:p-5 bg-card flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3.5">
              <div className="p-2 rounded-lg bg-muted border border-border">
                {getFileIcon(selectedFile.name)}
              </div>
              <div>
                <p className="text-sm font-medium text-foreground break-all">
                  {selectedFile.name}
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {formatBytes(selectedFile.size)} • Ready for AI Ingestion
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2.5 w-full sm:w-auto">
              <button
                type="button"
                onClick={handleClearFile}
                disabled={isUploading}
                className="p-2 text-muted-foreground hover:text-foreground rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
                title="Remove file"
              >
                <X className="h-4 w-4" />
              </button>

              <button
                type="button"
                onClick={handleUploadSubmit}
                disabled={isUploading}
                className="flex-1 sm:flex-none inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-sm shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isUploading ? (
                  <>
                    <span className="h-4 w-4 rounded-full border-2 border-white/20 border-t-white animate-spin" />
                    <span>Uploading...</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="h-4 w-4" />
                    <span>Start Ingestion</span>
                  </>
                )}
              </button>
            </div>
          </div>
        )}

        {/* Error Alert */}
        {error && (
          <div className="mt-3 flex items-center gap-2 p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-700 dark:text-rose-400 text-xs">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}
      </div>
    </div>
  );
}

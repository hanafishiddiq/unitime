"use client";

import React, { useState, useEffect } from "react";
import {
  FileText,
  Code2,
  Copy,
  Check,
  Download,
  RefreshCw,
  FolderOpen,
  Eye,
} from "lucide-react";
import { getReports, getReportContent, ReportItem, JobStatusResponse } from "@/lib/api";
import { formatDate, formatBytes } from "@/lib/utils";
import { AiResponseParser } from "@/components/AiResponseParser";

interface AuditReportJsonTabProps {
  jobStatus: JobStatusResponse | null;
}

export function AuditReportJsonTab({ jobStatus }: AuditReportJsonTabProps) {
  const [activeSubTab, setActiveSubTab] = useState<"markdown" | "json">("markdown");
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [selectedReportFilename, setSelectedReportFilename] = useState<string | null>(null);
  const [reportMarkdown, setReportMarkdown] = useState<string>("");
  const [isLoading, setIsLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [viewMode, setViewMode] = useState<"preview" | "raw">("preview");

  // Fetch available reports
  const loadReports = async () => {
    setIsLoading(true);
    try {
      const list = await getReports();
      setReports(list);
      if (list.length > 0 && !selectedReportFilename) {
        setSelectedReportFilename(list[0].filename);
      }
    } catch {
      setReports([]);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadReports();
  }, []);

  // Fetch content when selected report changes
  useEffect(() => {
    if (!selectedReportFilename) return;
    setIsLoading(true);
    getReportContent(selectedReportFilename)
      .then((content) => setReportMarkdown(content))
      .catch(() => setReportMarkdown("Failed to load audit report content."))
      .finally(() => setIsLoading(false));
  }, [selectedReportFilename]);

  const jsonPayloadString = JSON.stringify(
    jobStatus?.course_summary || {
      note: "Upload and extract a document to view canonical curriculum JSON payload.",
    },
    null,
    2
  );

  const activeContent =
    activeSubTab === "markdown" ? reportMarkdown : jsonPayloadString;

  const handleCopy = () => {
    if (!activeContent) return;
    navigator.clipboard.writeText(activeContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    if (!activeContent) return;
    const isMd = activeSubTab === "markdown";
    const filename = isMd
      ? selectedReportFilename || "audit_report.md"
      : `curriculum_${jobStatus?.job_id || "payload"}.json`;
    const mimeType = isMd ? "text/markdown" : "application/json";

    const blob = new Blob([activeContent], { type: `${mimeType};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="bg-card border border-border rounded-xl shadow-xs overflow-hidden flex flex-col h-[650px]">
      {/* Top Action Header */}
      <div className="p-3 border-b border-border bg-muted/20 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {/* Sub-tab Switcher */}
          <div className="flex items-center gap-1 p-1 rounded-lg bg-background border border-border">
            <button
              type="button"
              onClick={() => setActiveSubTab("markdown")}
              className={`inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                activeSubTab === "markdown"
                  ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 font-semibold border border-emerald-500/20"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <FileText className="h-3.5 w-3.5" />
              <span>Executive Markdown Report</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveSubTab("json")}
              className={`inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                activeSubTab === "json"
                  ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 font-semibold border border-emerald-500/20"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Code2 className="h-3.5 w-3.5" />
              <span>Canonical JSON Viewer</span>
            </button>
          </div>

          {/* Select Report Dropdown & View Mode if in markdown mode */}
          {activeSubTab === "markdown" && (
            <div className="flex items-center gap-2">
              {reports.length > 0 && (
                <select
                  value={selectedReportFilename || ""}
                  onChange={(e) => setSelectedReportFilename(e.target.value)}
                  className="text-xs rounded-lg border border-input bg-background px-2.5 py-1 text-foreground focus:outline-none focus:ring-1 focus:ring-emerald-500"
                >
                  {reports.map((r) => (
                    <option key={r.filename} value={r.filename}>
                      {r.filename} ({formatBytes(r.size_bytes)})
                    </option>
                  ))}
                </select>
              )}

              <div className="flex items-center gap-1 p-0.5 rounded-lg bg-background border border-border">
                <button
                  type="button"
                  onClick={() => setViewMode("preview")}
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                    viewMode === "preview"
                      ? "bg-muted text-foreground shadow-2xs font-semibold"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Eye className="h-3 w-3" />
                  <span>Preview</span>
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode("raw")}
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                    viewMode === "raw"
                      ? "bg-muted text-foreground shadow-2xs font-semibold"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Code2 className="h-3 w-3" />
                  <span>Raw</span>
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Copy & Download Actions */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-lg border border-border bg-background hover:bg-muted text-foreground transition-colors"
          >
            {copied ? (
              <>
                <Check className="h-3.5 w-3.5 text-emerald-500" />
                <span>Copied</span>
              </>
            ) : (
              <>
                <Copy className="h-3.5 w-3.5" />
                <span>Copy</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={handleDownload}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white transition-colors"
          >
            <Download className="h-3.5 w-3.5" />
            <span>Download</span>
          </button>
        </div>
      </div>

      {/* Content Viewer Body */}
      <div className="flex-1 overflow-y-auto bg-background text-foreground select-text">
        {isLoading ? (
          <div className="flex items-center justify-center h-full text-muted-foreground gap-2">
            <RefreshCw className="h-4 w-4 animate-spin text-emerald-500" />
            <span>Loading content...</span>
          </div>
        ) : activeContent ? (
          activeSubTab === "markdown" ? (
            viewMode === "preview" ? (
              <div className="p-6 max-w-4xl mx-auto">
                <AiResponseParser content={reportMarkdown} className="text-sm" />
              </div>
            ) : (
              <div className="p-5 font-mono text-xs whitespace-pre-wrap leading-relaxed">
                {reportMarkdown}
              </div>
            )
          ) : (
            <div className="p-5 font-mono text-xs whitespace-pre-wrap leading-relaxed">
              {jsonPayloadString}
            </div>
          )
        ) : (
          <div className="text-center text-muted-foreground mt-24">
            No report available. Please run an ingestion pipeline first.
          </div>
        )}
      </div>
    </div>
  );
}

"use client";

import React, { useState, useEffect } from "react";
import {
  X,
  FileText,
  Download,
  Copy,
  Check,
  Calendar,
  HardDrive,
  RefreshCw,
  Eye,
} from "lucide-react";
import { getReports, getReportContent, ReportItem } from "@/lib/api";
import { formatBytes, formatDate } from "@/lib/utils";

interface AuditReportsModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialFilename?: string | null;
}

export function AuditReportsModal({
  isOpen,
  onClose,
  initialFilename,
}: AuditReportsModalProps) {
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [selectedReport, setSelectedReport] = useState<string | null>(null);
  const [reportContent, setReportContent] = useState<string | null>(null);
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [isLoadingContent, setIsLoadingContent] = useState(false);
  const [copied, setCopied] = useState(false);

  // Fetch list of reports
  const fetchList = async () => {
    setIsLoadingList(true);
    try {
      const list = await getReports();
      setReports(list);
      if (initialFilename && list.some((r) => r.filename === initialFilename)) {
        handleSelectReport(initialFilename);
      } else if (list.length > 0 && !selectedReport) {
        handleSelectReport(list[0].filename);
      }
    } catch {
      setReports([]);
    } finally {
      setIsLoadingList(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchList();
    }
  }, [isOpen, initialFilename]);

  const handleSelectReport = async (filename: string) => {
    setSelectedReport(filename);
    setIsLoadingContent(true);
    try {
      const content = await getReportContent(filename);
      setReportContent(content);
    } catch {
      setReportContent("Failed to load audit report content.");
    } finally {
      setIsLoadingContent(false);
    }
  };

  const handleCopy = () => {
    if (!reportContent) return;
    navigator.clipboard.writeText(reportContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    if (!reportContent || !selectedReport) return;
    const blob = new Blob([reportContent], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = selectedReport;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-sm">
      <div className="bg-card border border-border rounded-xl shadow-xl w-full max-w-5xl h-[85vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        {/* Modal Header */}
        <div className="px-6 py-4 border-b border-border flex items-center justify-between bg-muted/30">
          <div className="flex items-center gap-2.5">
            <FileText className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
            <div>
              <h2 className="text-base font-semibold text-foreground">
                Executive Audit Reports
              </h2>
              <p className="text-xs text-muted-foreground">
                Ingestion provenance, conflict resolution log, and canonical payload audit
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={fetchList}
              disabled={isLoadingList}
              className="p-2 text-muted-foreground hover:text-foreground rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
              title="Refresh reports"
            >
              <RefreshCw className={`h-4 w-4 ${isLoadingList ? "animate-spin" : ""}`} />
            </button>
            <button
              onClick={onClose}
              className="p-2 text-muted-foreground hover:text-foreground rounded-lg hover:bg-muted transition-colors"
              title="Close modal"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="flex-1 flex overflow-hidden divide-x divide-border">
          {/* Left Sidebar: Report List */}
          <div className="w-80 flex flex-col bg-muted/10 shrink-0">
            <div className="p-3 border-b border-border text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Available Reports ({reports.length})
            </div>

            <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
              {isLoadingList && reports.length === 0 ? (
                <div className="p-4 text-center text-xs text-muted-foreground">
                  Loading reports...
                </div>
              ) : reports.length === 0 ? (
                <div className="p-6 text-center text-xs text-muted-foreground">
                  No audit reports generated yet.
                </div>
              ) : (
                reports.map((rep) => {
                  const isSelected = selectedReport === rep.filename;
                  return (
                    <button
                      key={rep.filename}
                      onClick={() => handleSelectReport(rep.filename)}
                      className={`w-full text-left p-3 rounded-lg text-xs transition-colors ${
                        isSelected
                          ? "bg-emerald-500/10 border border-emerald-500/30 text-emerald-900 dark:text-emerald-200 font-medium"
                          : "border border-transparent hover:bg-muted text-foreground"
                      }`}
                    >
                      <p className="font-mono truncate">{rep.filename}</p>
                      <div className="flex items-center gap-2 text-[10px] text-muted-foreground mt-1">
                        <span>{formatDate(rep.modified_at)}</span>
                        <span>•</span>
                        <span>{formatBytes(rep.size_bytes)}</span>
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </div>

          {/* Right Main Pane: Content Viewer */}
          <div className="flex-1 flex flex-col overflow-hidden bg-background">
            {selectedReport && (
              <div className="px-6 py-2.5 border-b border-border flex items-center justify-between bg-card text-xs">
                <span className="font-mono font-medium text-foreground truncate">
                  {selectedReport}
                </span>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleCopy}
                    disabled={!reportContent}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-border hover:bg-muted text-xs font-medium transition-colors"
                  >
                    {copied ? (
                      <>
                        <Check className="h-3.5 w-3.5 text-emerald-500" />
                        <span>Copied</span>
                      </>
                    ) : (
                      <>
                        <Copy className="h-3.5 w-3.5" />
                        <span>Copy Markdown</span>
                      </>
                    )}
                  </button>

                  <button
                    type="button"
                    onClick={handleDownload}
                    disabled={!reportContent}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium transition-colors"
                  >
                    <Download className="h-3.5 w-3.5" />
                    <span>Download</span>
                  </button>
                </div>
              </div>
            )}

            <div className="flex-1 overflow-y-auto p-6 font-mono text-xs text-foreground whitespace-pre-wrap leading-relaxed select-text">
              {isLoadingContent ? (
                <div className="flex items-center justify-center h-48 text-muted-foreground gap-2">
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  <span>Loading report content...</span>
                </div>
              ) : reportContent ? (
                reportContent
              ) : (
                <div className="text-center text-muted-foreground mt-12">
                  Select a report from the sidebar to view audit details.
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

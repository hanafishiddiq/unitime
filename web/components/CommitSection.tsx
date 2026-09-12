"use client";

import React, { useState } from "react";
import {
  Upload,
  CheckCircle2,
  AlertOctagon,
  FileText,
  ExternalLink,
  Download,
  Database,
  ArrowRight,
  ShieldCheck,
} from "lucide-react";
import { SubmitResponse } from "@/lib/api";

interface CommitSectionProps {
  jobId: string;
  isReady: boolean;
  onCommit: () => Promise<void>;
  isSubmitting: boolean;
  submitResult: SubmitResponse | null;
  submitError: string | null;
  onOpenReport: () => void;
}

export function CommitSection({
  jobId,
  isReady,
  onCommit,
  isSubmitting,
  submitResult,
  submitError,
  onOpenReport,
}: CommitSectionProps) {
  const [showRawDetails, setShowRawDetails] = useState(false);

  return (
    <div className="bg-card border border-border rounded-xl shadow-sm overflow-hidden p-6 space-y-5">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Database className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
            <h3 className="text-base font-semibold text-foreground">
              UniTime Database Synchronization
            </h3>
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            Publish canonical course offerings, instructional subparts, and class reservations into UniTime.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Audit Report Button */}
          <button
            type="button"
            onClick={onOpenReport}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border border-border bg-background hover:bg-muted text-xs font-semibold text-foreground transition-colors"
          >
            <FileText className="h-4 w-4 text-muted-foreground" />
            <span>Executive Audit Report</span>
          </button>

          {/* Commit Button */}
          <button
            type="button"
            onClick={onCommit}
            disabled={!isReady || isSubmitting || submitResult?.is_success}
            className={`inline-flex items-center justify-center gap-2 px-6 py-2.5 rounded-lg font-semibold text-xs sm:text-sm shadow-sm transition-all ${
              submitResult?.is_success
                ? "bg-emerald-600/20 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30 cursor-default"
                : "bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50 disabled:cursor-not-allowed"
            }`}
          >
            {isSubmitting ? (
              <>
                <span className="h-4 w-4 rounded-full border-2 border-white/20 border-t-white animate-spin" />
                <span>Transmitting to UniTime...</span>
              </>
            ) : submitResult?.is_success ? (
              <>
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                <span>Synchronized with UniTime</span>
              </>
            ) : (
              <>
                <Database className="h-4 w-4" />
                <span>Commit to UniTime Server</span>
                <ArrowRight className="h-4 w-4" />
              </>
            )}
          </button>
        </div>
      </div>

      {/* Success Notification Banner */}
      {submitResult && (
        <div
          className={`p-4 rounded-xl border text-xs animate-in fade-in duration-300 ${
            submitResult.is_success
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-950 dark:text-emerald-100"
              : "bg-rose-500/10 border-rose-500/30 text-rose-950 dark:text-rose-100"
          }`}
        >
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-start sm:items-center gap-2.5">
              {submitResult.is_success ? (
                <CheckCircle2 className="h-5 w-5 text-emerald-600 dark:text-emerald-400 shrink-0" />
              ) : (
                <AlertOctagon className="h-5 w-5 text-rose-600 dark:text-rose-400 shrink-0" />
              )}
              <div>
                <p className="font-semibold text-sm">
                  {submitResult.is_success
                    ? "Successfully Committed to UniTime Server!"
                    : "UniTime Synchronization Encountered an Issue"}
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {submitResult.summary ||
                    `Status: ${submitResult.status} (HTTP ${submitResult.http_status_code})`}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onOpenReport}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-xs transition-colors"
              >
                <FileText className="h-3.5 w-3.5" />
                <span>View Full Audit Report</span>
              </button>

              {submitResult.details && (
                <button
                  type="button"
                  onClick={() => setShowRawDetails(!showRawDetails)}
                  className="px-2.5 py-1.5 rounded-md border border-border bg-background hover:bg-muted text-xs font-medium text-foreground transition-colors"
                >
                  {showRawDetails ? "Hide Response" : "Raw JSON"}
                </button>
              )}
            </div>
          </div>

          {showRawDetails && submitResult.details && (
            <div className="mt-3 pt-3 border-t border-border/50">
              <pre className="font-mono text-[11px] p-3 rounded-lg bg-background/80 overflow-x-auto text-foreground max-h-60">
                {JSON.stringify(submitResult.details, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Error Notification Banner */}
      {submitError && !submitResult && (
        <div className="p-4 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-950 dark:text-rose-100 text-xs flex items-start gap-2.5 animate-in fade-in">
          <AlertOctagon className="h-5 w-5 text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-semibold text-sm">Submission Error</p>
            <p className="mt-0.5 text-rose-700 dark:text-rose-300 font-mono text-[11px] break-all">
              {submitError}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

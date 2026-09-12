"use client";

import React from "react";
import {
  Clock,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  FileCheck,
  Cpu,
  ShieldCheck,
  Users,
  Send,
} from "lucide-react";
import { JobStatusResponse, JobState } from "@/lib/api";

interface ProgressLogStreamProps {
  status: JobStatusResponse;
}

export function ProgressLogStream({ status }: ProgressLogStreamProps) {
  const { state, progress, error, filename, updated_at } = status;
  const percent = Math.min(100, Math.max(0, progress.percent || 0));

  const getStateBadge = (st: JobState) => {
    switch (st) {
      case "queued":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-700 dark:text-slate-300 border border-slate-500/20">
            <Clock className="h-3 w-3" />
            Queued
          </span>
        );
      case "processing":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-sky-500/10 text-sky-700 dark:text-sky-300 border border-sky-500/20 animate-pulse">
            <Loader2 className="h-3 w-3 animate-spin text-sky-500" />
            Processing
          </span>
        );
      case "waiting_disambiguation":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-500/20">
            <AlertTriangle className="h-3 w-3 text-amber-500" />
            Waiting for Input
          </span>
        );
      case "completed":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/20">
            <CheckCircle2 className="h-3 w-3 text-emerald-500" />
            Completed
          </span>
        );
      case "failed":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-700 dark:text-rose-300 border border-rose-500/20">
            <XCircle className="h-3 w-3 text-rose-500" />
            Failed
          </span>
        );
    }
  };

  const steps = [
    { id: "queued", label: "Uploaded", icon: FileCheck, minPct: 10 },
    { id: "chunking", label: "AI Extraction", icon: Cpu, minPct: 30 },
    { id: "validating", label: "Semantic Validation", icon: ShieldCheck, minPct: 60 },
    { id: "disambiguation", label: "Disambiguation", icon: Users, minPct: 80 },
    { id: "completed", label: "Canonical Ready", icon: Send, minPct: 100 },
  ];

  return (
    <div className="bg-card border border-border rounded-xl shadow-sm p-6 space-y-5">
      {/* Header Info */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-border/70">
        <div>
          <div className="flex items-center gap-2.5">
            <h3 className="font-semibold text-foreground text-sm sm:text-base">
              Pipeline Execution: {filename}
            </h3>
            {getStateBadge(state)}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            Job ID: <code className="font-mono text-[11px] bg-muted px-1.5 py-0.5 rounded">{status.job_id}</code>
          </p>
        </div>

        {/* Chunk Badge */}
        {progress.total_chunks > 0 && (
          <div className="inline-flex items-center gap-2 self-start sm:self-auto px-3 py-1 rounded-lg bg-muted text-xs font-medium text-foreground">
            <span>Progress:</span>
            <span className="font-semibold text-emerald-600 dark:text-emerald-400">
              Chunk {progress.current_chunk} of {progress.total_chunks}
            </span>
          </div>
        )}
      </div>

      {/* Progress Bar & Percentage */}
      <div>
        <div className="flex items-center justify-between text-xs mb-1.5 font-medium">
          <span className="text-muted-foreground">
            Stage:{" "}
            <strong className="text-foreground capitalize">
              {progress.stage.replace(/_/g, " ")}
            </strong>
          </span>
          <span className="font-mono font-semibold text-emerald-600 dark:text-emerald-400">
            {percent}%
          </span>
        </div>
        <div className="w-full h-2.5 bg-muted rounded-full overflow-hidden">
          <div
            className={`h-full transition-all duration-500 ease-out rounded-full ${
              state === "failed"
                ? "bg-rose-500"
                : state === "waiting_disambiguation"
                ? "bg-amber-500"
                : "bg-emerald-500"
            }`}
            style={{ width: `${percent}%` }}
          />
        </div>
      </div>

      {/* Progression Steps */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 pt-2">
        {steps.map((step, idx) => {
          const isPassed = percent >= step.minPct || state === "completed";
          const isCurrent =
            (percent < step.minPct &&
              idx > 0 &&
              percent >= steps[idx - 1].minPct) ||
            (idx === 0 && percent < step.minPct);

          const StepIcon = step.icon;
          return (
            <div
              key={step.id}
              className={`p-2.5 rounded-lg border text-xs flex items-center gap-2 transition-colors ${
                isPassed
                  ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-800 dark:text-emerald-300 font-medium"
                  : isCurrent
                  ? "border-sky-500/40 bg-sky-500/5 text-sky-800 dark:text-sky-300 font-medium animate-pulse"
                  : "border-border/60 bg-muted/20 text-muted-foreground"
              }`}
            >
              <StepIcon className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{step.label}</span>
            </div>
          );
        })}
      </div>

      {/* Log Message Box */}
      <div className="p-3.5 rounded-lg bg-muted/50 border border-border flex items-start justify-between gap-3 text-xs">
        <div className="flex items-start gap-2">
          <div className="mt-0.5">
            {state === "failed" ? (
              <XCircle className="h-4 w-4 text-rose-500 shrink-0" />
            ) : state === "waiting_disambiguation" ? (
              <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0" />
            ) : state === "completed" ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
            ) : (
              <Loader2 className="h-4 w-4 text-sky-500 animate-spin shrink-0" />
            )}
          </div>
          <div>
            <p className="font-medium text-foreground">
              {progress.message || "Pipeline is executing..."}
            </p>
            {error && (
              <p className="text-rose-600 dark:text-rose-400 mt-1 font-mono text-[11px] break-all">
                {error}
              </p>
            )}
          </div>
        </div>

        <span
          suppressHydrationWarning
          className="text-[11px] text-muted-foreground whitespace-nowrap"
        >
          {new Date(updated_at).toLocaleTimeString()}
        </span>
      </div>
    </div>
  );
}

"use client";

import React, { useState } from "react";
import {
  FileSearch,
  BookCheck,
  Split,
  HelpCircle,
  ShieldCheck,
  Send,
  CheckCircle2,
  AlertCircle,
  Clock,
  RefreshCw,
  ArrowRight,
  Database,
  ExternalLink,
} from "lucide-react";
import { JobStatusResponse, SubmitResponse } from "@/lib/api";
import { AiResponseParser } from "@/components/AiResponseParser";

interface ReasoningStreamTabProps {
  jobStatus: JobStatusResponse | null;
  onResolveAmbiguities: (resolutions: Record<string, string>) => void;
  isResolving: boolean;
  onCommitToUniTime: () => void;
  isSubmitting: boolean;
  submitResult: SubmitResponse | null;
  submitError: string | null;
  onOpenReport?: () => void;
}

export function ReasoningStreamTab({
  jobStatus,
  onResolveAmbiguities,
  isResolving,
  onCommitToUniTime,
  isSubmitting,
  submitResult,
  submitError,
  onOpenReport,
}: ReasoningStreamTabProps) {
  // Local resolution selections
  const [selectedResolutions, setSelectedResolutions] = useState<
    Record<string, string>
  >({});

  const stage = jobStatus?.progress.stage || "idle";
  const percent = jobStatus?.progress.percent || 0;
  const isWaitingHITL = jobStatus?.state === "waiting_disambiguation";
  const isCompleted = jobStatus?.state === "completed";
  const isFailed = jobStatus?.state === "failed";
  const ambiguities = jobStatus?.ambiguities || [];
  const validation = jobStatus?.validation_result;

  // Step 1: Parsing & Document OCR
  const step1Done =
    isCompleted ||
    isWaitingHITL ||
    ["extracting", "merging", "validating", "reporting"].includes(stage);
  const step1Active = ["queued", "slicing", "parsing"].includes(stage);

  // Step 2: SN-Dikti Normalization
  const step2Done =
    isCompleted ||
    isWaitingHITL ||
    ["merging", "validating", "reporting"].includes(stage);
  const step2Active = stage === "extracting";

  // Step 3: Constraint Deduction
  const step3Done =
    isCompleted ||
    isWaitingHITL ||
    ["validating", "reporting"].includes(stage);
  const step3Active = stage === "merging";

  // Step 4: Disambiguation / HITL
  const step4Done = isCompleted && ambiguities.length === 0;
  const step4Active = isWaitingHITL;

  // Step 5: JSON Schema Validation
  const step5Done = Boolean(validation && validation.is_valid);
  const step5Active = stage === "validating";

  // Step 6: Commit to UniTime
  const step6Done = Boolean(submitResult && submitResult.is_success);
  const step6Ready = isCompleted && !step6Done;

  const handleOptionSelect = (ambId: string, option: string) => {
    setSelectedResolutions((prev) => ({ ...prev, [ambId]: option }));
  };

  const handleSubmitResolutions = () => {
    onResolveAmbiguities(selectedResolutions);
  };

  return (
    <div className="space-y-6">
      {/* Real-time Pipeline Progress Header */}
      {jobStatus && (
        <div className="p-4 rounded-xl bg-card border border-border space-y-3">
          <div className="flex items-center justify-between text-xs">
            <span className="font-semibold text-foreground flex items-center gap-2">
              <RefreshCw
                className={`h-3.5 w-3.5 text-emerald-500 ${
                  !isCompleted && !isFailed ? "animate-spin" : ""
                }`}
              />
              <span>Pipeline Stage: {stage.toUpperCase()}</span>
            </span>
            <span className="font-mono text-emerald-600 dark:text-emerald-400 font-bold">
              {percent}%
            </span>
          </div>

          <div className="w-full h-2 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full transition-all duration-300 ${
                isFailed ? "bg-rose-500" : "bg-emerald-500"
              }`}
              style={{ width: `${percent}%` }}
            />
          </div>

          <p className="text-[11px] text-muted-foreground font-mono">
            {jobStatus.progress.message || "Processing academic schedule..."}
          </p>
        </div>
      )}

      {/* Step-by-Step Reasoning Flow */}
      <div className="space-y-3">
        {/* Step 1: Parsing & Document OCR */}
        <div
          className={`p-4 rounded-xl border transition-colors ${
            step1Done
              ? "bg-card border-border"
              : step1Active
              ? "bg-emerald-500/5 border-emerald-500/30"
              : "bg-muted/10 border-border/60 opacity-60"
          }`}
        >
          <div className="flex items-start gap-3">
            <div
              className={`h-8 w-8 rounded-lg flex items-center justify-center shrink-0 ${
                step1Done
                  ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                  : step1Active
                  ? "bg-primary/10 text-primary"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              {step1Done ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : (
                <FileSearch className="h-4 w-4" />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold text-foreground">
                  Step 1: Parsing & Document OCR
                </h4>
                <span
                  className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${
                    step1Done
                      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                      : step1Active
                      ? "bg-primary/10 text-primary animate-pulse"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {step1Done ? "Extracted" : step1Active ? "In Progress" : "Pending"}
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Tokenizes layout, extracts schedule tables, lecture halls, and departmental blocks.
              </p>
            </div>
          </div>
        </div>

        {/* Step 2: SN-Dikti Normalization */}
        <div
          className={`p-4 rounded-xl border transition-colors ${
            step2Done
              ? "bg-card border-border"
              : step2Active
              ? "bg-emerald-500/5 border-emerald-500/30"
              : "bg-muted/10 border-border/60 opacity-60"
          }`}
        >
          <div className="flex items-start gap-3">
            <div
              className={`h-8 w-8 rounded-lg flex items-center justify-center shrink-0 ${
                step2Done
                  ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                  : step2Active
                  ? "bg-primary/10 text-primary"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              {step2Done ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : (
                <BookCheck className="h-4 w-4" />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold text-foreground">
                  Step 2: SN-Dikti Normalization
                </h4>
                <span
                  className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${
                    step2Done
                      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                      : step2Active
                      ? "bg-primary/10 text-primary animate-pulse"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {step2Done ? "Standardized" : step2Active ? "Normalizing" : "Pending"}
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Maps SKS credit hours to 50 min/credit semester minutes; converts &ldquo;Kuliah&rdquo; to Lecture and &ldquo;Praktikum&rdquo; to Lab.
              </p>
            </div>
          </div>
        </div>

        {/* Step 3: Constraint Deduction */}
        <div
          className={`p-4 rounded-xl border transition-colors ${
            step3Done
              ? "bg-card border-border"
              : step3Active
              ? "bg-emerald-500/5 border-emerald-500/30"
              : "bg-muted/10 border-border/60 opacity-60"
          }`}
        >
          <div className="flex items-start gap-3">
            <div
              className={`h-8 w-8 rounded-lg flex items-center justify-center shrink-0 ${
                step3Done
                  ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                  : step3Active
                  ? "bg-primary/10 text-primary"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              {step3Done ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : (
                <Split className="h-4 w-4" />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold text-foreground">
                  Step 3: Constraint Deduction
                </h4>
                <span
                  className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${
                    step3Done
                      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                      : step3Active
                      ? "bg-primary/10 text-primary animate-pulse"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {step3Done ? "Deductions Complete" : step3Active ? "Reasoning" : "Pending"}
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Deduces instructor unavailabilities, room capacities, and distribution rules (e.g. AtMost12Hours).
              </p>
            </div>
          </div>
        </div>

        {/* Step 4: Disambiguation / HITL */}
        <div
          className={`p-4 rounded-xl border transition-colors ${
            step4Active
              ? "bg-amber-500/10 border-amber-500/30"
              : step4Done
              ? "bg-card border-border"
              : "bg-muted/10 border-border/60 opacity-60"
          }`}
        >
          <div className="flex items-start gap-3">
            <div
              className={`h-8 w-8 rounded-lg flex items-center justify-center shrink-0 ${
                step4Active
                  ? "bg-amber-500/20 text-amber-600 dark:text-amber-400"
                  : step4Done
                  ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              {step4Done ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : (
                <HelpCircle className="h-4 w-4" />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold text-foreground">
                  Step 4: Disambiguation & Human-in-the-Loop
                </h4>
                <span
                  className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${
                    step4Active
                      ? "bg-amber-500/20 text-amber-700 dark:text-amber-300 font-semibold"
                      : step4Done
                      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {step4Active
                    ? `${ambiguities.length} Conflicts Pending Review`
                    : step4Done
                    ? "0 Conflicts"
                    : "Standby"}
                </span>
              </div>

              {/* Interactive HITL Resolution Box */}
              {step4Active && ambiguities.length > 0 && (
                <div className="mt-3 p-3 rounded-lg bg-background border border-amber-500/30 space-y-3 text-xs">
                  <p className="font-medium text-foreground">
                    Action Required: Please choose resolutions for conflicting courses:
                  </p>
                  {ambiguities.map((amb) => {
                    const currentSelection =
                      selectedResolutions[amb.id] || amb.options?.[0] || "Approved";
                    return (
                      <div
                        key={amb.id}
                        className="p-2.5 rounded-md bg-muted/40 border border-border space-y-2"
                      >
                        <div className="text-[11px] font-semibold text-foreground">
                          <AiResponseParser content={amb.question} className="text-[11px]" />
                        </div>
                        {amb.options && (
                          <div className="flex flex-wrap gap-1.5">
                            {amb.options.map((opt) => (
                              <button
                                key={opt}
                                type="button"
                                onClick={() => handleOptionSelect(amb.id, opt)}
                                className={`px-2.5 py-1 rounded-md text-[10px] font-medium border transition-colors ${
                                  currentSelection === opt
                                    ? "bg-amber-500 text-white border-amber-600 font-bold"
                                    : "bg-background border-border text-foreground hover:bg-muted"
                                }`}
                              >
                                {opt}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}

                  <button
                    type="button"
                    onClick={handleSubmitResolutions}
                    disabled={isResolving}
                    className="w-full py-2 px-3 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5"
                  >
                    <Send className="h-3 w-3" />
                    <span>
                      {isResolving ? "Resuming Pipeline..." : "Submit Resolutions & Continue"}
                    </span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Step 5: JSON Schema Validation */}
        <div
          className={`p-4 rounded-xl border transition-colors ${
            step5Done
              ? "bg-card border-border"
              : step5Active
              ? "bg-emerald-500/5 border-emerald-500/30"
              : "bg-muted/10 border-border/60 opacity-60"
          }`}
        >
          <div className="flex items-start gap-3">
            <div
              className={`h-8 w-8 rounded-lg flex items-center justify-center shrink-0 ${
                step5Done
                  ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              <ShieldCheck className="h-4 w-4" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold text-foreground">
                  Step 5: JSON Schema Validation
                </h4>
                <span
                  className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                    step5Done
                      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {step5Done
                    ? "Passed (0 Schema Errors)"
                    : validation && !validation.is_valid
                    ? `${validation.errors_count} Errors Found`
                    : "Awaiting Payload"}
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Enforces strict schema constraints for UniTime Course Offerings, Subparts, and Instructors.
              </p>
            </div>
          </div>
        </div>

        {/* Step 6: Commit to UniTime */}
        <div
          className={`p-4 rounded-xl border transition-colors ${
            step6Done
              ? "bg-emerald-500/10 border-emerald-500/30"
              : step6Ready
              ? "bg-primary/5 border-primary/30"
              : "bg-muted/10 border-border/60 opacity-60"
          }`}
        >
          <div className="flex items-start gap-3">
            <div
              className={`h-8 w-8 rounded-lg flex items-center justify-center shrink-0 ${
                step6Done
                  ? "bg-emerald-600 text-white"
                  : step6Ready
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              <Database className="h-4 w-4" />
            </div>
            <div className="flex-1 min-w-0 space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold text-foreground">
                  Step 6: Commit to UniTime REST Server
                </h4>
                <span
                  className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${
                    step6Done
                      ? "bg-emerald-500/20 text-emerald-800 dark:text-emerald-300 font-bold"
                      : step6Ready
                      ? "bg-primary/10 text-primary font-semibold"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {step6Done ? "Synchronized" : step6Ready ? "Ready to Commit" : "Pending"}
                </span>
              </div>

              <p className="text-[11px] text-muted-foreground">
                Synchronizes the verified academic session, course configurations, and class schedules directly into the UniTime database.
              </p>

              {/* Commit Action Button */}
              {step6Ready && (
                <button
                  type="button"
                  onClick={onCommitToUniTime}
                  disabled={isSubmitting}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold shadow-sm transition-colors disabled:opacity-50"
                >
                  <Database className="h-3.5 w-3.5" />
                  <span>
                    {isSubmitting ? "Transmitting to UniTime..." : "Commit Offerings to UniTime"}
                  </span>
                </button>
              )}

              {/* Submission Result Feedback */}
              {submitResult && (
                <div className="p-3 rounded-lg bg-background border border-emerald-500/30 text-xs space-y-1 font-mono">
                  <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400 font-bold">
                    <CheckCircle2 className="h-4 w-4" />
                    <span>Status: {submitResult.status} (HTTP {submitResult.http_status_code})</span>
                  </div>
                  <p className="text-[11px] text-muted-foreground font-sans">
                    {submitResult.summary}
                  </p>
                </div>
              )}

              {submitError && (
                <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-xs text-rose-700 dark:text-rose-300 flex items-center gap-2">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  <span>{submitError}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

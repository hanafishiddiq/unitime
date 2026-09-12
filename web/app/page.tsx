"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { toast } from "sonner";
import {
  Sparkles,
  RotateCcw,
  ArrowRight,
  ShieldCheck,
  CheckCircle2,
  FileText,
  Clock,
  Layers,
  Info,
} from "lucide-react";

import {
  uploadFile,
  getStatus,
  resolveDisambiguation,
  submitToUniTime,
  JobStatusResponse,
  UploadOptions,
  SubmitResponse,
  ApiError,
} from "@/lib/api";

import { Header } from "@/components/Header";
import { FileUploadDropzone } from "@/components/FileUploadDropzone";
import { ProgressLogStream } from "@/components/ProgressLogStream";
import { DisambiguationCard } from "@/components/DisambiguationCard";
import { CurriculumOfferingsTable } from "@/components/CurriculumOfferingsTable";
import { CommitSection } from "@/components/CommitSection";
import { AuditReportsModal } from "@/components/AuditReportsModal";

export default function DashboardPage() {
  // Primary Job State
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);

  // Interaction loading states
  const [isUploading, setIsUploading] = useState(false);
  const [isResolving, setIsResolving] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Submission Results
  const [submitResult, setSubmitResult] = useState<SubmitResponse | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Modal State
  const [isReportsModalOpen, setIsReportsModalOpen] = useState(false);
  const [activeReportFilename, setActiveReportFilename] = useState<string | null>(
    null
  );

  // Polling ref to prevent concurrent overlapping polls
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  // Stop polling helper
  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  // Poll status implementation
  const pollStatus = useCallback(
    async (id: string) => {
      try {
        const status = await getStatus(id);
        setJobStatus(status);

        if (status.state === "completed") {
          stopPolling();
          toast.success("Extraction and validation completed successfully!");
        } else if (status.state === "failed") {
          stopPolling();
          toast.error(
            `Pipeline failed: ${status.error || "Unknown validation error"}`
          );
        } else if (status.state === "waiting_disambiguation") {
          stopPolling();
          toast.warning(
            `Paused: ${status.ambiguities.length} conflict(s) require administrative review.`
          );
        }
      } catch (err) {
        console.error("Polling error:", err);
      }
    },
    [stopPolling]
  );

  // Start polling interval
  const startPolling = useCallback(
    (id: string) => {
      stopPolling();
      // Immediate first poll
      pollStatus(id);
      pollingRef.current = setInterval(() => {
        pollStatus(id);
      }, 2000);
    },
    [pollStatus, stopPolling]
  );

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      stopPolling();
    };
  }, [stopPolling]);

  // Handle File Upload
  const handleStartUpload = async (file: File, options: UploadOptions) => {
    setIsUploading(true);
    setSubmitResult(null);
    setSubmitError(null);
    setJobStatus(null);

    try {
      toast.info(`Uploading "${file.name}" to AI Ingestion Gateway...`);
      const res = await uploadFile(file, options);
      setJobId(res.job_id);
      toast.success(res.message || "Ingestion pipeline initialized.");

      // Begin polling
      startPolling(res.job_id);
    } catch (err) {
      const msg = err instanceof ApiError ? err.detail : (err as Error).message;
      toast.error(`Upload failed: ${msg}`);
    } finally {
      setIsUploading(false);
    }
  };

  // Handle Human-in-the-Loop Disambiguation
  const handleResolveAmbiguities = async (resolutions: Record<string, string>) => {
    if (!jobId) return;
    setIsResolving(true);

    try {
      toast.info("Submitting disambiguation resolutions...");
      const res = await resolveDisambiguation(jobId, resolutions);
      toast.success(res.message || "Resolutions accepted. Resuming pipeline.");

      // Resume polling
      startPolling(jobId);
    } catch (err) {
      const msg = err instanceof ApiError ? err.detail : (err as Error).message;
      toast.error(`Failed to resolve conflicts: ${msg}`);
    } finally {
      setIsResolving(false);
    }
  };

  // Handle UniTime Database Submission
  const handleCommitToUniTime = async () => {
    if (!jobId) return;
    setIsSubmitting(true);
    setSubmitError(null);

    try {
      toast.info("Transmitting canonical payload to UniTime REST API...");
      const res = await submitToUniTime(jobId);
      setSubmitResult(res);

      if (res.is_success) {
        toast.success(res.summary || "Synchronized with UniTime server!");
      } else {
        toast.error(`UniTime responded with status: ${res.status}`);
      }
    } catch (err) {
      const msg = err instanceof ApiError ? err.detail : (err as Error).message;
      setSubmitError(msg);
      toast.error(`Submission failed: ${msg}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Reset / New Ingestion
  const handleReset = () => {
    stopPolling();
    setJobId(null);
    setJobStatus(null);
    setSubmitResult(null);
    setSubmitError(null);
  };

  const isCompleted = jobStatus?.state === "completed";
  const isWaitingDisambiguation = jobStatus?.state === "waiting_disambiguation";
  const hasCourseSummary = Boolean(
    jobStatus?.course_summary &&
      jobStatus.course_summary.courses &&
      jobStatus.course_summary.courses.length > 0
  );

  return (
    <div className="flex-1 flex flex-col">
      {/* Header */}
      <Header
        onOpenReports={() => {
          setActiveReportFilename(null);
          setIsReportsModalOpen(true);
        }}
      />

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Hero Introduction */}
        {!jobId && (
          <div className="text-center max-w-3xl mx-auto pt-4 pb-2 space-y-3 animate-in fade-in duration-300">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 text-xs font-semibold border border-emerald-500/20">
              <Sparkles className="h-3.5 w-3.5" />
              <span>Multi-Agent Timetabling Pipeline</span>
            </div>
            <h1 className="text-3xl sm:text-4xl font-extrabold text-foreground tracking-tight">
              Autonomous Academic Curriculum Ingestion
            </h1>
            <p className="text-sm sm:text-base text-muted-foreground leading-relaxed">
              Upload unstructured course memos, semester distribution spreadsheets,
              or syllabus PDFs. The agent reasons through instructional constraints,
              solves capacity ambiguities, and synchronizes directly with UniTime.
            </p>
          </div>
        )}

        {/* Section 1: Upload Dropzone */}
        {!jobId ? (
          <FileUploadDropzone
            onStartUpload={handleStartUpload}
            isUploading={isUploading}
          />
        ) : (
          /* Active Job Header with Reset */
          <div className="flex items-center justify-between p-4 rounded-xl bg-card border border-border">
            <div className="flex items-center gap-3">
              <div className="h-9 w-9 rounded-lg bg-primary/10 text-primary flex items-center justify-center font-bold text-sm">
                AI
              </div>
              <div>
                <p className="text-sm font-semibold text-foreground">
                  Active Ingestion: {jobStatus?.filename || "Processing..."}
                </p>
                <p className="text-xs text-muted-foreground">
                  ID: <span className="font-mono">{jobId}</span>
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={handleReset}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border hover:bg-muted text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              <span>New Ingestion</span>
            </button>
          </div>
        )}

        {/* Section 2: Real-time Ingestion Progress & Log Stream */}
        {jobStatus && <ProgressLogStream status={jobStatus} />}

        {/* Section 3: Human-in-the-Loop Disambiguation Component */}
        {isWaitingDisambiguation && jobStatus && jobStatus.ambiguities.length > 0 && (
          <DisambiguationCard
            jobId={jobId!}
            ambiguities={jobStatus.ambiguities}
            onResolve={handleResolveAmbiguities}
            isResolving={isResolving}
          />
        )}

        {/* Section 4: Curriculum Offerings Preview Table */}
        {hasCourseSummary && jobStatus?.course_summary && (
          <CurriculumOfferingsTable
            summary={jobStatus.course_summary}
            validationResult={jobStatus.validation_result}
          />
        )}

        {/* Section 5: One-Click Commit Action */}
        {jobId && (isCompleted || hasCourseSummary) && (
          <CommitSection
            jobId={jobId}
            isReady={isCompleted}
            onCommit={handleCommitToUniTime}
            isSubmitting={isSubmitting}
            submitResult={submitResult}
            submitError={submitError}
            onOpenReport={() => {
              // Try to find report named after job or open report modal
              setActiveReportFilename(null);
              setIsReportsModalOpen(true);
            }}
          />
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-border py-6 mt-12 bg-muted/20 text-xs text-muted-foreground text-center">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-foreground">UniTime</span>
            <span>• Comprehensive Academic Scheduling System</span>
          </div>
          <div>Next.js 14 Web Frontend • Connected to ai-gateway REST Server</div>
        </div>
      </footer>

      {/* Executive Audit Reports Modal */}
      <AuditReportsModal
        isOpen={isReportsModalOpen}
        onClose={() => setIsReportsModalOpen(false)}
        initialFilename={activeReportFilename}
      />
    </div>
  );
}

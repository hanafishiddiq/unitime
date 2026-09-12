"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { toast } from "sonner";
import {
  Sparkles,
  RotateCcw,
  Bot,
  BrainCircuit,
  Calendar,
  FileCode2,
} from "lucide-react";

import {
  uploadFile,
  getStatus,
  resolveDisambiguation,
  submitToUniTime,
  checkAuthStatus,
  sendChatMessage,
  ChatApiMessage,
  JobStatusResponse,
  SubmitResponse,
  ApiError,
} from "@/lib/api";

import { Header } from "@/components/Header";
import { ChatInterface, ChatMessage } from "@/components/ChatInterface";
import { ReasoningStreamTab } from "@/components/ReasoningStreamTab";
import { VisualTimetableTab } from "@/components/VisualTimetableTab";
import { AuditReportJsonTab } from "@/components/AuditReportJsonTab";
import { AdminAccessModal } from "@/components/AdminAccessModal";

type RightPanelTab = "reasoning" | "timetable" | "reports";

export default function DashboardPage() {
  // Authentication State
  const [isAdminModalOpen, setIsAdminModalOpen] = useState(false);
  const [isAuthVerified, setIsAuthVerified] = useState(true);

  // Active Tab in Right Panel
  const [activeTab, setActiveTab] = useState<RightPanelTab>("reasoning");

  // Primary Job State
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);

  // Interaction loading states
  const [isUploading, setIsUploading] = useState(false);
  const [isResolving, setIsResolving] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isThinking, setIsThinking] = useState(false);

  // Submission Results
  const [submitResult, setSubmitResult] = useState<SubmitResponse | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Conversational Chat Messages
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "msg_welcome",
      sender: "assistant",
      text: "Halo! Saya Asisten AI Penjadwalan UniTime. Silakan unggah dokumen jadwal (PDF, Excel, Word, Teks, atau JSON) atau ketik instruksi di bawah untuk memulai.",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ]);

  // Polling ref to prevent concurrent overlapping polls
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  // Verify auth on mount
  useEffect(() => {
    checkAuthStatus()
      .then((res) => {
        if (res.required && !res.authenticated) {
          setIsAuthVerified(false);
          setIsAdminModalOpen(true);
        } else {
          setIsAuthVerified(true);
        }
      })
      .catch(() => {
        // If auth endpoint unreachable, fail open or proceed
        setIsAuthVerified(true);
      });
  }, []);

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
          toast.success("Ekstraksi dan validasi jadwal berhasil!");

          // Auto-switch to visual timetable tab if courses extracted
          const totalCourses = status.course_summary?.total_courses || 0;
          if (totalCourses > 0) {
            setActiveTab("timetable");
          }

          setMessages((prev) => [
            ...prev,
            {
              id: `msg_done_${Date.now()}`,
              sender: "assistant",
              text: `✅ Ekstraksi selesai dan lolos validasi skema (${totalCourses} mata kuliah terdeteksi). Anda dapat melihat jadwal visual di tab **Visual Timetable** atau menekan **Commit to UniTime Server** pada tab Reasoning.`,
              timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
            },
          ]);
        } else if (status.state === "failed") {
          stopPolling();
          toast.error(`Proses gagal: ${status.error || "Terjadi kesalahan pada validasi"}`);
          setMessages((prev) => [
            ...prev,
            {
              id: `msg_err_${Date.now()}`,
              sender: "assistant",
              text: `❌ Ekstraksi gagal: ${status.error || "Gagal memproses dokumen"}. Silakan periksa kembali format dokumen Anda.`,
              timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
            },
          ]);
        } else if (status.state === "waiting_disambiguation") {
          stopPolling();
          setActiveTab("reasoning");
          toast.warning(`Memerlukan keputusan: ${status.ambiguities.length} ambiguitas terdeteksi.`);
          setMessages((prev) => [
            ...prev,
            {
              id: `msg_hitl_${Date.now()}`,
              sender: "assistant",
              text: `⚠️ Ditemukan ${status.ambiguities.length} benturan/ambiguitas jadwal yang membutuhkan keputusan Anda. Silakan pilih opsi resolusi di tab **Reasoning Steps**.`,
              timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
            },
          ]);
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
      pollStatus(id);
      pollingRef.current = setInterval(() => {
        pollStatus(id);
      }, 1500);
    },
    [pollStatus, stopPolling]
  );

  // Clean up polling on unmount
  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  // Handle File Upload
  const handleUploadFile = async (file: File) => {
    setIsUploading(true);
    setSubmitResult(null);
    setSubmitError(null);
    setActiveTab("reasoning");

    // Add user upload message to chat
    setMessages((prev) => [
      ...prev,
      {
        id: `msg_upload_${Date.now()}`,
        sender: "user",
        text: `Mengunggah dokumen jadwal: ${file.name}`,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        attachment: {
          name: file.name,
          size: file.size,
          type: file.type || "document",
        },
      },
      {
        id: `msg_start_${Date.now()}`,
        sender: "assistant",
        text: `Dokumen "${file.name}" diterima. Memulai parsing dokumen dan ekstraksi AI... Perhatikan langkah reasoning di panel samping.`,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      },
    ]);

    try {
      const response = await uploadFile(file, {
        provider: "gemini",
        strict: true,
        dryRun: false,
      });

      setJobId(response.job_id);
      toast.info("Pipeline ekstraksi AI dimulai...");
      startPolling(response.job_id);
    } catch (err) {
      const apiErr = err as ApiError;
      toast.error(`Gagal mengunggah file: ${apiErr.detail || apiErr.message}`);
      setMessages((prev) => [
        ...prev,
        {
          id: `msg_up_err_${Date.now()}`,
          sender: "assistant",
          text: `Gagal mengunggah dokumen: ${apiErr.detail || apiErr.message}`,
          timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
      ]);
    } finally {
      setIsUploading(false);
    }
  };

  // Handle Chat Message Send with Autonomous ReAct AI Agent
  const handleSendMessage = async (text: string) => {
    if (!text.trim() || isThinking || isUploading) return;

    const userMsgId = `msg_user_${Date.now()}`;
    const userMsg: ChatMessage = {
      id: userMsgId,
      sender: "user",
      text: text.trim(),
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsThinking(true);

    try {
      // Map previous messages for context
      const historyPayload: ChatApiMessage[] = messages
        .filter((m) => m.sender === "user" || m.sender === "assistant")
        .slice(-6)
        .map((m) => ({
          role: m.sender as "user" | "assistant",
          content: m.text,
        }));

      const res = await sendChatMessage(text.trim(), historyPayload, jobId);

      const assistantMsg: ChatMessage = {
        id: `msg_ai_${Date.now()}`,
        sender: "assistant",
        text: res.reply,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        tools_used: res.tools_used,
        thought_process: res.thought_process,
      };

      setMessages((prev) => [...prev, assistantMsg]);

      if (res.tools_used && res.tools_used.length > 0) {
        toast.info(`ReAct Agent mengeksekusi: ${res.tools_used.join(", ")}`);
      }
    } catch (err) {
      const apiErr = err as ApiError;
      const errorDetail = apiErr.detail || apiErr.message || "Gagal menghubungi AI Agent";
      toast.error(`ReAct Agent Error: ${errorDetail}`);

      setMessages((prev) => [
        ...prev,
        {
          id: `msg_err_${Date.now()}`,
          sender: "assistant",
          text: `⚠️ Maaf, terjadi kendala saat memproses penalaran AI: ${errorDetail}`,
          timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
      ]);
    } finally {
      setIsThinking(false);
    }
  };

  // Handle HITL Ambiguity Resolution
  const handleResolveAmbiguities = async (resolutions: Record<string, string>) => {
    if (!jobId) return;
    setIsResolving(true);
    try {
      await resolveDisambiguation(jobId, resolutions);
      toast.success("Keputusan administratif tersimpan. Melanjutkan ekstraksi...");
      startPolling(jobId);
    } catch (err) {
      const apiErr = err as ApiError;
      toast.error(`Gagal menyimpan resolusi: ${apiErr.detail || apiErr.message}`);
    } finally {
      setIsResolving(false);
    }
  };

  // Handle Commit to UniTime Server
  const handleCommitToUniTime = async () => {
    if (!jobId) return;
    setIsSubmitting(true);
    setSubmitError(null);
    try {
      const res = await submitToUniTime(jobId);
      setSubmitResult(res);
      if (res.is_success) {
        toast.success("Berhasil di-commit ke UniTime Server!");
        setMessages((prev) => [
          ...prev,
          {
            id: `msg_committed_${Date.now()}`,
            sender: "assistant",
            text: `🎉 Jadwal telah berhasil di-commit secara permanen ke UniTime Tomcat & MySQL Database di Tencent VPS!`,
            timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
          },
        ]);
      } else {
        toast.warning("Transaksi UniTime selesai dengan catatan atau peringatan.");
      }
    } catch (err) {
      const apiErr = err as ApiError;
      const msg = apiErr.detail || apiErr.message;
      setSubmitError(msg);
      toast.error(`Commit gagal: ${msg}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Reset Session
  const handleReset = () => {
    stopPolling();
    setJobId(null);
    setJobStatus(null);
    setSubmitResult(null);
    setSubmitError(null);
    setActiveTab("reasoning");
    setMessages([
      {
        id: "msg_welcome_reset",
        sender: "assistant",
        text: "Sesi telah direset. Silakan unggah file jadwal kurikulum baru untuk memulai proses berikutnya.",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      },
    ]);
    toast.info("Sesi telah direset.");
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col antialiased">
      {/* Top Application Header */}
      <Header
        onOpenReports={() => setActiveTab("reports")}
        isAdminRequired={!isAuthVerified}
        isAuthenticated={isAuthVerified}
        onOpenAdminModal={() => setIsAdminModalOpen(true)}
      />

      {/* Main Split-View Workspace */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 space-y-4">
        {/* Workspace Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-3 pb-1 border-b border-border/60">
          <div>
            <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-emerald-500" />
              Smart Curriculum & Timetable Ingestion
            </h1>
            <p className="text-xs text-muted-foreground">
              Ekstraksi jadwal berbasis AI multimodal dengan verifikasi transparan dan sinkronisasi otomatis ke UniTime 4.9.
            </p>
          </div>

          <div className="flex items-center gap-2">
            {jobId && (
              <button
                type="button"
                onClick={handleReset}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-muted-foreground hover:text-foreground border border-border hover:bg-muted/50 transition-colors"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Reset Sesi
              </button>
            )}
          </div>
        </div>

        {/* Dual-Pane Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* ============================================================ */}
          {/* LEFT PANE: Conversational Chatbot & Document Upload (5 Cols)  */}
          {/* ============================================================ */}
          <div className="lg:col-span-5 h-[720px] flex flex-col">
            <ChatInterface
              messages={messages}
              onSendMessage={handleSendMessage}
              onUploadFile={handleUploadFile}
              isUploading={isUploading}
              isThinking={isThinking}
              jobStatus={jobStatus}
              onSelectPrompt={handleSendMessage}
            />
          </div>

          {/* ============================================================ */}
          {/* RIGHT PANE: Reasoning Steps & Visual Timetable Tabs (7 Cols)  */}
          {/* ============================================================ */}
          <div className="lg:col-span-7 h-[720px] flex flex-col space-y-3">
            {/* Elegant Tab Switcher */}
            <div className="flex items-center justify-between p-1.5 rounded-xl bg-card border border-border shadow-2xs">
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setActiveTab("reasoning")}
                  className={`inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                    activeTab === "reasoning"
                      ? "bg-emerald-500 text-white shadow-xs"
                      : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                  }`}
                >
                  <BrainCircuit className="h-3.5 w-3.5" />
                  Reasoning Steps
                  {jobStatus?.state === "waiting_disambiguation" && (
                    <span className="h-2 w-2 rounded-full bg-amber-400 animate-ping" />
                  )}
                </button>

                <button
                  type="button"
                  onClick={() => setActiveTab("timetable")}
                  className={`inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                    activeTab === "timetable"
                      ? "bg-emerald-500 text-white shadow-xs"
                      : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                  }`}
                >
                  <Calendar className="h-3.5 w-3.5" />
                  Visual Timetable
                  {(jobStatus?.course_summary?.total_courses || 0) > 0 && (
                    <span className="px-1.5 py-0.5 rounded-full text-[10px] bg-background/20 font-bold">
                      {jobStatus?.course_summary?.total_courses}
                    </span>
                  )}
                </button>

                <button
                  type="button"
                  onClick={() => setActiveTab("reports")}
                  className={`inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                    activeTab === "reports"
                      ? "bg-emerald-500 text-white shadow-xs"
                      : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                  }`}
                >
                  <FileCode2 className="h-3.5 w-3.5" />
                  Audit & JSON
                </button>
              </div>
            </div>

            {/* Tab Contents Area */}
            <div className="flex-1 overflow-y-auto pr-1">
              {activeTab === "reasoning" && (
                <ReasoningStreamTab
                  jobStatus={jobStatus}
                  onResolveAmbiguities={handleResolveAmbiguities}
                  isResolving={isResolving}
                  onCommitToUniTime={handleCommitToUniTime}
                  isSubmitting={isSubmitting}
                  submitResult={submitResult}
                  submitError={submitError}
                  onOpenReport={() => setActiveTab("reports")}
                />
              )}

              {activeTab === "timetable" && (
                <VisualTimetableTab
                  summary={jobStatus?.course_summary || null}
                  validationResult={jobStatus?.validation_result}
                />
              )}

              {activeTab === "reports" && (
                <AuditReportJsonTab jobStatus={jobStatus} />
              )}
            </div>
          </div>
        </div>
      </main>

      {/* Admin Access Passcode Modal (BFF Security) */}
      <AdminAccessModal
        isOpen={isAdminModalOpen && !isAuthVerified}
        onSuccess={() => {
          setIsAuthVerified(true);
          setIsAdminModalOpen(false);
          toast.success("Akses Administrator Terverifikasi.");
        }}
      />
    </div>
  );
}

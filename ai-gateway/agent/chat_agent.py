"""UniTime AI Ingestion Gateway - ReAct Chat Agent.

Provides an autonomous ReAct (Reasoning + Acting) conversational agent
specialized in academic curriculum and timetabling management.
Equipped with tools to inspect active schedules, detect time conflicts,
verify room capacity, normalize instructor titles, and check UniTime server health.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from agent.memory import AgentMemory
from agent.nodes import _extract_all_classes
from agent.tools import (
    check_time_conflict,
    inspect_room_capacity,
    resolve_instructor_identity,
)
from core.client import UniTimeClient

logger = logging.getLogger(__name__)

REACT_SYSTEM_PROMPT = """Anda adalah UniTime AI Scheduling Assistant, agen kecerdasan buatan otonom berbasis arsitektur ReAct (Reasoning + Acting) untuk sistem penjadwalan akademik UniTime (Timetabling & Curriculum Ingestion).

Tugas Anda:
1. Membantu staf akademik, dosen, dan administrator dalam memeriksa jadwal, kapasitas kelas, kurikulum mata kuliah, dan status sinkronisasi UniTime.
2. Selalu menggunakan penalaran kritis (Reasoning) dan mengeksekusi alat (Tools) jika pengguna menanyakan data spesifik jadwal, ruangan, dosen, atau benturan jam.
3. Selalu menjawab dengan sopan, terstruktur, ramah, dan profesional dalam Bahasa Indonesia (format Markdown).

Alat (Tools) yang tersedia untuk Anda:
- `get_active_schedule_context`: Mengambil data kurikulum & jadwal dari dokumen yang sedang aktif di dashboard (berdasarkan job_id).
  Parameter JSON: `{"job_id": "<opsional_job_id>", "query": "<kata_kunci_opsional>"}`
- `check_time_conflict`: Memeriksa tumpang tindih waktu, benturan ruangan, atau dosen ganda dari daftar kelas aktif.
  Parameter JSON: `{"job_id": "<opsional_job_id>"}`
- `inspect_room_capacity`: Memverifikasi apakah ruangan tertentu mencukupi kebutuhan kapasitas mahasiswa.
  Parameter JSON: `{"building": "<nama_gedung>", "room_number": "<nomor_ruang>", "required_cap": <jumlah_mahasiswa>}`
- `resolve_instructor_identity`: Melakukan normalisasi dan verifikasi nama dosen serta gelar akademik.
  Parameter JSON: `{"dept": "<kode_departemen>", "raw_name": "<nama_lengkap_dosen>"}`
- `check_unitime_server_health`: Mengecek status koneksi hidup ke server UniTime Tomcat v4.8 dan database MySQL.
  Parameter JSON: `{}`

Format Eksekusi ReAct:
Jika memerlukan tool, Anda HARUS menghasilkan format tepat seperti ini:
Thought: <analisis kebutuhan dan apa yang perlu dilakukan>
Action: <nama_tool>
Action Input: <json_parameter>

Setelah menerima `Observation: <hasil>`, lanjutkan penalaran Anda:
Thought: <analisis terhadap hasil observasi>
... (Ulangi Thought/Action/Action Input/Observation jika butuh alat lain)

Jika sudah memiliki informasi yang cukup, atau jika pertanyaan umum/sapaan tidak memerlukan tool:
Thought: <penalaran akhir>
Final Answer: <jawaban lengkap, rapi, dan solutif untuk pengguna dalam Bahasa Indonesia>

PENTING:
- Jangan mengarang data jadwal atau kapasitas ruangan jika Anda bisa mengeceknya via tools.
- Jangan gunakan formatting code blocks (```) untuk blok Thought/Action/Action Input.
- Berikan format tabel atau poin-poin yang mudah dibaca pada bagian Final Answer jika menampilkan jadwal.
"""


class ChatReActAgent:
    """Conversational ReAct Agent that coordinates LLM reasoning with academic scheduling tools."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        memory: Optional[AgentMemory] = None,
        job_manager_ref: Optional[Any] = None,
    ) -> None:
        raw_base = (
            base_url
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or os.getenv("LLM_ENDPOINT")
            or "http://host.docker.internal:8080/v1"
        ).rstrip("/")

        default_key = (
            "antigravity-gateway"
            if any(h in raw_base for h in ("host.docker.internal", "localhost", "127.0.0.1", "172."))
            else "antigravity"
        )
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY") or default_key
        self.model = (
            model
            or os.getenv("DEFAULT_LLM_MODEL")
            or os.getenv("OPENAI_MODEL")
            or os.getenv("LLM_MODEL")
            or "gemini-flash-latest"
        )

        if raw_base.endswith("/chat/completions"):
            self.endpoint = raw_base
        else:
            self.endpoint = f"{raw_base}/chat/completions"

        self.memory = memory or AgentMemory()
        self.job_manager_ref = job_manager_ref
        self.unitime_client = UniTimeClient(
            base_url=os.getenv("UNITIME_API_URL", "http://unitime-web:8080/api/smart-ingest"),
            username=os.getenv("UNITIME_USERNAME", "admin"),
            password=os.getenv("UNITIME_PASSWORD", "admin"),
        )

        # Register Available Tools
        self.tools: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            "get_active_schedule_context": self._tool_get_schedule_context,
            "check_time_conflict": self._tool_check_time_conflict,
            "inspect_room_capacity": self._tool_inspect_room_capacity,
            "resolve_instructor_identity": self._tool_resolve_instructor,
            "check_unitime_server_health": self._tool_check_server_health,
        }

    # -------------------------------------------------------------------------
    # Tool Implementations
    # -------------------------------------------------------------------------

    def _get_job_payload(self, job_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Helper to resolve active job payload from job_manager or memory."""
        if not self.job_manager_ref:
            return None

        job = None
        if job_id:
            job = self.job_manager_ref.get_job(job_id)

        if not job:
            # Fallback to the latest available job
            all_jobs = self.job_manager_ref.list_jobs()
            if all_jobs:
                job = all_jobs[-1]

        if job and getattr(job, "payload", None):
            return job.payload
        return None

    def _tool_get_schedule_context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch curriculum offerings, classes, and instructors for active job."""
        job_id = args.get("job_id")
        payload = self._get_job_payload(job_id)

        if not payload:
            return {
                "status": "not_found",
                "message": "Belum ada dokumen jadwal yang aktif atau baru selesai diekstrak di sesi ini.",
                "total_courses": 0,
                "courses": [],
            }

        courses_summary: List[Dict[str, Any]] = []
        courses = payload.get("courses", [])
        for c in courses:
            if not isinstance(c, dict):
                continue
            c_num = c.get("courseNumber") or c.get("course_code") or "Unknown"
            c_title = c.get("courseTitle") or c.get("title") or ""
            classes_count = 0
            configs = c.get("configurations", [])
            class_details: List[str] = []

            for cfg in configs:
                if isinstance(cfg, dict):
                    for sp in cfg.get("subparts", []):
                        if isinstance(sp, dict):
                            sp_type = sp.get("instructionalType", "Class")
                            for cls in sp.get("classes", []):
                                if isinstance(cls, dict):
                                    classes_count += 1
                                    sec = cls.get("sectionNumber") or cls.get("classNumber", "1")
                                    time_info = cls.get("timePattern") or cls.get("time", "TBA")
                                    room_info = cls.get("room") or "TBA"
                                    inst_list = cls.get("instructors") or []
                                    inst_names = [
                                        ins.get("name", "") if isinstance(ins, dict) else str(ins)
                                        for ins in inst_list
                                    ]
                                    class_details.append(
                                        f"{sp_type}-{sec}: {time_info} @ {room_info} (Dosen: {', '.join(filter(None, inst_names)) or 'TBA'})"
                                    )

            courses_summary.append({
                "course_number": c_num,
                "course_title": c_title,
                "total_classes": classes_count,
                "classes": class_details[:6],  # limit to top classes to avoid token overflow
            })

        dept = payload.get("department", {}).get("code", "General")
        session = payload.get("academicSession", {}).get("term", "Semester Ganjil")

        return {
            "status": "success",
            "department": dept,
            "session": session,
            "total_courses": len(courses_summary),
            "courses": courses_summary,
        }

    def _tool_check_time_conflict(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Check for scheduling, room, or instructor overlaps in the active timetable."""
        job_id = args.get("job_id")
        payload = self._get_job_payload(job_id)

        if not payload:
            return {
                "has_conflict": False,
                "total_conflicts": 0,
                "message": "Tidak ada data jadwal aktif untuk diperiksa.",
            }

        classes = _extract_all_classes(payload)
        return check_time_conflict(classes)

    def _tool_inspect_room_capacity(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Verify room seating capacity against required enrollment."""
        building = str(args.get("building", "")).strip()
        room_number = str(args.get("room_number", "")).strip()
        required_cap = int(args.get("required_cap", 0))

        return inspect_room_capacity(
            building=building,
            room_number=room_number,
            required_cap=required_cap,
            memory_instance=self.memory,
        )

    def _tool_resolve_instructor(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Disambiguate academic instructor name and credentials."""
        dept = str(args.get("dept", "*")).strip()
        raw_name = str(args.get("raw_name", "")).strip()

        return resolve_instructor_identity(
            dept=dept,
            raw_name=raw_name,
            memory_instance=self.memory,
        )

    def _tool_check_server_health(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Check live UniTime Tomcat connectivity."""
        try:
            details = self.unitime_client.health_check()
            return {
                "connected": True,
                "url": self.unitime_client.base_url,
                "status": "UP",
                "details": details,
            }
        except Exception as exc:
            return {
                "connected": False,
                "url": self.unitime_client.base_url,
                "status": "DOWN",
                "error": str(exc),
            }

    # -------------------------------------------------------------------------
    # LLM Request Handler
    # -------------------------------------------------------------------------

    def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """Issue completion request to Antigravity Gateway / OpenAI compatible endpoint."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }

        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(self.endpoint, headers=headers, json=payload)
                if resp.status_code != 200:
                    logger.error("LLM request failed: HTTP %s - %s", resp.status_code, resp.text)
                    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("Failed to reach LLM endpoint at %s: %s", self.endpoint, exc)
            raise

    # -------------------------------------------------------------------------
    # ReAct Loop Execution
    # -------------------------------------------------------------------------

    def run_chat(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        job_id: Optional[str] = None,
        max_steps: int = 5,
    ) -> Dict[str, Any]:
        """Execute the multi-turn ReAct reasoning loop with tool execution."""
        messages: List[Dict[str, str]] = [{"role": "system", "content": REACT_SYSTEM_PROMPT}]

        # Inject conversation history if available
        if history:
            for item in history[-6:]:  # include up to last 6 turns
                role = item.get("role") or item.get("sender") or "user"
                content = item.get("content") or item.get("text") or ""
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        # Inject current turn context
        user_prompt = message
        if job_id:
            user_prompt += f"\n[Context: Active Job ID is '{job_id}']"

        messages.append({"role": "user", "content": user_prompt})

        thought_steps: List[str] = []
        tools_used: List[str] = []
        final_answer = ""

        # Pattern matching for Thought, Action, Action Input, Final Answer
        action_pattern = re.compile(
            r"Action:\s*([a-zA-Z0-9_]+)\s*\nAction Input:\s*(\{.*?\})",
            re.DOTALL,
        )

        for step in range(max_steps):
            try:
                llm_response = self._call_llm(messages)
            except Exception as exc:
                # Fallback graceful response if LLM gateway is temporarily unreachable
                logger.error("ReAct Chat Agent fallback error: %s", exc)
                return {
                    "reply": (
                        f"Maaf, saya tidak dapat terhubung ke model AI saat ini ({exc}). "
                        "Silakan pastikan Antigravity Gateway berjalan pada port 8080."
                    ),
                    "thought_process": thought_steps,
                    "tools_used": tools_used,
                    "error": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

            # Check for Final Answer
            if "Final Answer:" in llm_response:
                parts = llm_response.split("Final Answer:", 1)
                thought_part = parts[0].strip()
                if thought_part:
                    thought_steps.append(thought_part)
                final_answer = parts[1].strip()
                break

            # Check if Action is invoked
            match = action_pattern.search(llm_response)
            if match:
                action_name = match.group(1).strip()
                action_input_raw = match.group(2).strip()

                # Extract preceding thought
                thought_prefix = llm_response[: match.start()].strip()
                if thought_prefix:
                    thought_steps.append(thought_prefix)

                # Parse JSON arguments safely
                try:
                    action_args = json.loads(action_input_raw)
                except Exception:
                    # Try basic fix for trailing commas or single quotes
                    cleaned = action_input_raw.replace("'", '"')
                    try:
                        action_args = json.loads(cleaned)
                    except Exception:
                        action_args = {}

                # Inject active job_id if omitted
                if job_id and "job_id" not in action_args:
                    action_args["job_id"] = job_id

                tools_used.append(action_name)
                logger.info("ReAct step %d: Invoking tool '%s' with args: %s", step + 1, action_name, action_args)

                # Execute Registered Tool
                tool_func = self.tools.get(action_name)
                if tool_func:
                    try:
                        obs_result = tool_func(action_args)
                        obs_str = json.dumps(obs_result, ensure_ascii=False)
                    except Exception as err:
                        obs_str = json.dumps({"error": f"Tool execution failed: {err}"})
                else:
                    obs_str = json.dumps({"error": f"Tool '{action_name}' is not recognized."})

                # Append assistant message with action and system observation
                messages.append({"role": "assistant", "content": llm_response})
                messages.append({
                    "role": "user",
                    "content": f"Observation: {obs_str}\nLanjutkan penalaran (Thought) dan jika sudah memiliki informasi, berikan 'Final Answer:'.",
                })
            else:
                # No action found and no Final Answer tag; treat whole response as answer
                thought_steps.append("LLM direct completion without tool action.")
                final_answer = llm_response.strip()
                break

        if not final_answer:
            final_answer = "Saya telah memproses permintaan Anda, namun tidak ada respons final yang dapat dirangkum."

        return {
            "reply": final_answer,
            "thought_process": thought_steps,
            "tools_used": tools_used,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

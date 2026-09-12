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
    commit_draft_to_unitime,
    draft_course_offering,
    get_draft_summary,
    inspect_room_capacity,
    record_building_and_rooms,
    record_campus_topology,
    record_scheduling_preference,
    resolve_instructor_identity,
)
from core.client import UniTimeClient

logger = logging.getLogger(__name__)

REACT_SYSTEM_PROMPT = """Anda adalah UniTime AI Scheduling Assistant, agen kecerdasan buatan otonom berbasis arsitektur ReAct (Reasoning + Acting) untuk sistem penjadwalan akademik UniTime (Timetabling & Curriculum Ingestion).

Tugas Anda:
1. Membantu staf akademik, dosen, dan administrator dalam memeriksa jadwal, kapasitas kelas, kurikulum mata kuliah, dan status sinkronisasi UniTime.
2. Membantu merakit data akademik secara bertahap percakapan demi percakapan (Progressive Conversational Data Builder) mencakup wilayah kampus, gedung, ruangan, mata kuliah, kelas, dan preferensi jadwal dosen.
3. Selalu menggunakan penalaran kritis (Reasoning) dan mengeksekusi alat (Tools) yang sesuai ketika pengguna menyebutkan fakta data baru atau menanyakan data spesifik.
4. Selalu menjawab dengan sopan, terstruktur, ramah, dan profesional dalam Bahasa Indonesia (format Markdown). Setelah mengeksekusi aksi pembentukan draft, selalu berikan konfirmasi ringkas dan tanyakan langkah logis selanjutnya (guided dialogue).

Alat (Tools) yang tersedia untuk Anda:
- `record_campus_topology`: Mencatat wilayah kampus (misal Depok, Salemba) dan estimasi transit antarkampus ke draft.
  Parameter JSON: `{"session_id": "<session_id>", "regions": ["Depok", "Salemba"], "travel_times": {"Depok_Salemba": 45}}`
- `record_building_and_rooms`: Mencatat gedung dan daftar ruangan (nama, kapasitas, tipe) ke draft.
  Parameter JSON: `{"session_id": "<session_id>", "building": "Gedung A", "campus_region": "Depok", "rooms": [{"room_number": "101", "capacity": 50}]}`
- `draft_course_offering`: Mencatat penawaran mata kuliah, SKS, kelas paralel, waktu, ruangan, dan dosen ke draft.
  Parameter JSON: `{"session_id": "<session_id>", "subject": "IF", "course_number": "IF2110", "title": "Algoritma", "sks": 3, "classes": [{"section": "01", "time": "Senin 08:00-10:00", "room": "LABTEK V 7601", "instructor": "Dr. Turing"}]}`
- `record_scheduling_preference`: Mencatat aturan/preferensi khusus penjadwalan (dosen, ruangan, waktu dilarang).
  Parameter JSON: `{"session_id": "<session_id>", "entity_type": "instructor", "entity_name": "Dr. Turing", "preference_type": "unavailable_time", "details": "Tidak bisa mengajar hari Jumat"}`
- `get_draft_summary`: Menampilkan rangkuman seluruh entitas draft data akademik sesi saat ini.
  Parameter JSON: `{"session_id": "<session_id>"}`
- `commit_draft_to_unitime`: Memvalidasi dan mengirimkan draft kanonikal ke server UniTime.
  Parameter JSON: `{"session_id": "<session_id>", "dry_run": false}`
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
- Berikan format tabel atau poin-poin yang mudah dibaca pada bagian Final Answer jika menampilkan jadwal atau ringkasan draft.
"""


def _extract_action_and_input(text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract action name, balanced JSON action input, and preceding thought from LLM response."""
    act_match = re.search(r"Action:\s*([a-zA-Z0-9_]+)", text)
    if not act_match:
        return None, None, None

    thought_prefix = text[: act_match.start()].strip()
    action_name = act_match.group(1).strip()

    input_idx = text.find("Action Input:", act_match.end())
    if input_idx == -1:
        return thought_prefix, action_name, "{}"

    remainder = text[input_idx + len("Action Input:") :].strip()
    start_pos = remainder.find("{")
    if start_pos == -1:
        return thought_prefix, action_name, "{}"

    depth = 0
    in_string = False
    escape = False
    end_pos = -1
    for i in range(start_pos, len(remainder)):
        ch = remainder[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end_pos = i + 1
                    break

    raw_input = remainder[start_pos:end_pos] if end_pos != -1 else remainder[start_pos:]
    return thought_prefix, action_name, raw_input


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
        self.tools: Dict[str, Callable[[Dict[str, Any]], Any]] = {
            "get_active_schedule_context": self._tool_get_schedule_context,
            "check_time_conflict": self._tool_check_time_conflict,
            "inspect_room_capacity": self._tool_inspect_room_capacity,
            "resolve_instructor_identity": self._tool_resolve_instructor,
            "check_unitime_server_health": self._tool_check_server_health,
            "record_campus_topology": self._tool_record_campus_topology,
            "record_building_and_rooms": self._tool_record_building_and_rooms,
            "draft_course_offering": self._tool_draft_course_offering,
            "record_scheduling_preference": self._tool_record_scheduling_preference,
            "get_draft_summary": self._tool_get_draft_summary,
            "commit_draft_to_unitime": self._tool_commit_draft_to_unitime,
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

    def _tool_record_campus_topology(self, args: Dict[str, Any]) -> str:
        session_id = args.get("session_id") or "default_session"
        regions = args.get("regions", [])
        travel_times = args.get("travel_times")
        return record_campus_topology(
            session_id=session_id,
            regions=regions,
            travel_times=travel_times,
            memory_instance=self.memory,
        )

    def _tool_record_building_and_rooms(self, args: Dict[str, Any]) -> str:
        session_id = args.get("session_id") or "default_session"
        building = args.get("building", "")
        campus_region = args.get("campus_region", "")
        rooms = args.get("rooms", [])
        return record_building_and_rooms(
            session_id=session_id,
            building=building,
            campus_region=campus_region,
            rooms=rooms,
            memory_instance=self.memory,
        )

    def _tool_draft_course_offering(self, args: Dict[str, Any]) -> str:
        session_id = args.get("session_id") or "default_session"
        subject = args.get("subject", "IF")
        course_number = args.get("course_number", "")
        title = args.get("title", "")
        sks = args.get("sks", 3)
        classes = args.get("classes")
        return draft_course_offering(
            session_id=session_id,
            subject=subject,
            course_number=course_number,
            title=title,
            sks=sks,
            classes=classes,
            memory_instance=self.memory,
        )

    def _tool_record_scheduling_preference(self, args: Dict[str, Any]) -> str:
        session_id = args.get("session_id") or "default_session"
        entity_type = args.get("entity_type", "general")
        entity_name = args.get("entity_name", "")
        preference_type = args.get("preference_type", "constraint")
        details = args.get("details", "")
        return record_scheduling_preference(
            session_id=session_id,
            entity_type=entity_type,
            entity_name=entity_name,
            preference_type=preference_type,
            details=details,
            memory_instance=self.memory,
        )

    def _tool_get_draft_summary(self, args: Dict[str, Any]) -> str:
        session_id = args.get("session_id") or "default_session"
        return get_draft_summary(
            session_id=session_id,
            memory_instance=self.memory,
        )

    def _tool_commit_draft_to_unitime(self, args: Dict[str, Any]) -> str:
        session_id = args.get("session_id") or "default_session"
        dry_run = bool(args.get("dry_run", False))
        return commit_draft_to_unitime(
            session_id=session_id,
            dry_run=dry_run,
            memory_instance=self.memory,
        )

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

    # -------------------------------------------------------------------------
    # ReAct Loop Execution
    # -------------------------------------------------------------------------

    def run_chat(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        job_id: Optional[str] = None,
        session_id: Optional[str] = None,
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
        context_hints = []
        if job_id:
            context_hints.append(f"Active Job ID is '{job_id}'")
        if session_id:
            context_hints.append(f"Active Session ID is '{session_id}'")
        if context_hints:
            user_prompt += f"\n[Context: {'; '.join(context_hints)}]"

        active_session_id = session_id or job_id or "default_session"

        messages.append({"role": "user", "content": user_prompt})

        thought_steps: List[str] = []
        tools_used: List[str] = []
        final_answer = ""

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
            thought_prefix, action_name, action_input_raw = _extract_action_and_input(llm_response)
            if action_name and action_input_raw:
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

                # Inject active session_id if omitted
                if active_session_id and "session_id" not in action_args:
                    action_args["session_id"] = active_session_id

                tools_used.append(action_name)
                logger.info("ReAct step %d: Invoking tool '%s' with args: %s", step + 1, action_name, action_args)

                # Execute Registered Tool
                tool_func = self.tools.get(action_name)
                if tool_func:
                    try:
                        obs_result = tool_func(action_args)
                        if isinstance(obs_result, str):
                            obs_str = obs_result
                        else:
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

# 🗺️ Project Status & Roadmap: UniTime AI Smart Ingestion

Dokumen ini adalah **sumber kebenaran tunggal (*Single Source of Truth*)** mengenai status perkembangan proyek, apa yang telah selesai dicapai, apa yang sedang dikerjakan saat ini, dan tahapan apa saja yang akan kita lakukan selanjutnya.

---

## 📌 Status Terkini Proyek (Executive Summary)

- **Fondasi Inti**: UniTime v4.8 (Java 17, Tomcat 10.1, Hibernate, MySQL 8.3)
- **Lapisan AI**: Python AI Ingestion Gateway (LangGraph ReAct, PyMuPDF, OpenPyXL, SQLite WAL Memory)
- **Status Kode**: **Production-Ready Core Engine** (78/78 Unit & Integration Tests Passing)
- **Target Arsitektur**: **Hybrid Cloud Deployment**
  - **Backend (24/7)**: Host di **Tencent Cloud VPS** (`tencent-vps.hanavy.online`)
  - **Frontend (Web UI)**: Host di **Vercel** (Next.js Dashboard)

---

## ✅ 1. Apa yang SUDAH SELESAI Dilakukan (Completed Milestones)

| Milestone | Ruang Lingkup | Status & Bukti Empiris |
| :--- | :--- | :---: |
| **M1: Spesifikasi Skema & Prompt** | Perancangan JSON Schema kanonikal UniTime (`unitime-smart-ingest-schema.json`), pemetaan standar SN-Dikti Indonesia, dan dokumentasi system prompt AI. | ✅ **100% Selesai** |
| **M2: Slicers & Parser Dokumen** | Modul pemotong file: PDF streaming (PyMuPDF), Excel normalisasi sel gabungan *fill-forward* (OpenPyXL), dan pemotong teks semantik. | ✅ **100% Selesai** |
| **M3: Agen AI LangGraph ReAct** | Ekstraksi terstruktur, *composite-key merger* (`type::suffix::parentSubpartType`), validasi skema ketat, dan memori persisten SQLite WAL untuk *Human-in-the-Loop* (HITL). | ✅ **100% Selesai** |
| **M4: Backend Connector Java** | Implementasi [`SmartIngestConnector.java`](JavaSource/org/unitime/timetable/api/connectors/SmartIngestConnector.java) di endpoint `/api/smart-ingest`. Mengeliminasi benturan transaksi Hibernate, translasi SKS $\rightarrow$ `semesterHours`, dan translasi tipe pengajaran (`Kuliah` $\rightarrow$ `Lec`, `Praktikum` $\rightarrow$ `Lab`, dll.). | ✅ **100% Selesai** |
| **M5: Live End-to-End MySQL Testing** | Pengujian data riil ke container MySQL `timetable`. Berhasil menyimpan penawaran MK, kelas paralel, dosen, dan batasan distribusi secara *idempotent* dan bebas duplikasi. | ✅ **100% Selesai** (Commit `1f29255`) |
| **M6: GitHub Documentation & CI Prep** | Perombakan `README.md` ramah pengguna, migrasi cabang `master` $\rightarrow$ `main`, dan penambahan dukungan Custom LLM Base URL (OpenRouter, Ollama, AI Proxy). | ✅ **100% Selesai** (Commit `c8f188a`) |

---

## 🔄 2. Apa yang SEDANG KITA LAKUKAN Saat Ini (In Progress)

Saat ini kita sedang mempersiapkan **Infrastruktur Backend 24/7 di Tencent Cloud VPS** dan merancang antarmuka untuk **Frontend Vercel**:

1. **Audit & Optimasi Sumber Daya VPS Tencent**:
   - Status terkini: RAM tersedia **1.2 GiB** dan Swap bebas **3.3 GiB** (ruang bernapas sudah aman).
   - Menyiapkan alokasi memori hemat (*Resource Diet*): Tomcat JVM disetel ke `-Xms256m -Xmx768m`, dan MySQL buffer pool disetel ke `128M`.
2. **Merancang REST API Server untuk AI Gateway (FastAPI)**:
   - Menjembatani Vercel dengan engine UniTime di VPS.
   - Menyediakan endpoint upload file agar Vercel tidak terputus limit *serverless* (10 detik).
3. **Persiapan Pipeline Deployment Gambar Docker (CI/CD)**:
   - Menghindari kompilasi Maven berat di VPS (yang berisiko memakan sisa disk 6 GB) dengan memanfaatkan GitHub Actions atau build pra-paket.

---

## 🚀 3. Apa Saja yang AKAN KITA LAKUKAN (Upcoming Roadmap)

Rencana kerja selanjutnya dibagi menjadi 3 fase terstruktur:

```mermaid
flowchart TD
    subgraph FASE1["Fase 1: Backend Deployment 24/7 (Tencent VPS)"]
        F1A["1.1 Buat FastAPI Server (ai-gateway/server.py)"]
        F1B["1.2 Setup Docker Compose Prod (Alokasi RAM Hemat)"]
        F1C["1.3 Deploy UniTime + MySQL + AI Gateway ke Tencent VPS"]
        F1D["1.4 Sambungkan ke Domain Publik via Cloudflare Tunnel"]
    end

    subgraph FASE2["Fase 2: Frontend Dashboard (Vercel)"]
        F2A["2.1 Inisialisasi Proyek Next.js / Tailwind di Vercel"]
        F2B["2.2 Halaman Upload Dokumen (PDF / Excel / Memo)"]
        F2C["2.3 Visualisasi & Peninjauan Hasil Ekstraksi Jadwal"]
        F2D["2.4 Modal Dialog Interaktif Disambiguasi (HITL)"]
        F2E["2.5 Tombol Submit ke UniTime & Unduh Laporan Audit"]
    end

    subgraph FASE3["Fase 3: Verifikasi Produksi & UAT"]
        F3A["3.1 Uji Alur Penuh dari Browser Vercel ke Database VPS"]
        F3B["3.2 Monitoring RAM, Swap, & CPU di Tencent VPS"]
        F3C["3.3 Dokumentasi Final Operasional"]
    end

    FASE1 --> FASE2
    FASE2 --> FASE3
```

---

### 📦 Rincian Langkah-Langkah Kerja:

#### 🔹 Fase 1: Backend Deployment 24/7 di Tencent VPS
- [ ] **1.1 Wrapper REST API FastAPI**:
  Membuat file `ai-gateway/server.py` yang menyediakan endpoint:
  - `POST /api/ingest/upload`: Menerima berkas dari web UI.
  - `GET /api/ingest/status/{job_id}`: Polling status pemrosesan dokumen.
  - `POST /api/ingest/resolve`: Mengirim jawaban admin untuk pertanyaan ambigu.
  - `GET /api/health`: Healthcheck koneksi ke UniTime Tomcat & MySQL.
- [ ] **1.2 Konfigurasi Docker Produksi (`docker-compose.prod.yml`)**:
  Menyusun konfigurasi kontainer dengan limit memori ketat dan restart policy `unless-stopped`.
- [ ] **1.3 Deployment ke Tencent VPS**:
  Menjalankan layanan di VPS Tencent dan memastikan semua service berjalan *healthy* 24/7.
- [ ] **1.4 Ekspos Domain & SSL**:
  Menghubungkan port FastAPI dan UniTime ke Cloudflare Tunnel (`https://unitime-api.hanavy.online`) sehingga frontend Vercel dapat memanggilnya via HTTPS tanpa masalah CORS.

---

#### 🔹 Fase 2: Pembangunan Frontend di Vercel (Next.js)
- [ ] **2.1 Setup Proyek Web**:
  Membuat repo/folder frontend Next.js App Router dengan komponen UI modern (Tailwind + Lucide Icons).
- [ ] **2.2 Komponen Drag & Drop Upload**:
  Area upload berkas yang mendukung multi-file (PDF SK Dekan, Excel roster jadwal, file teks).
- [ ] **2.3 Interactive Curriculum Table**:
  Tabel visual yang menampilkan daftar mata kuliah, dosen, SKS, kuota, dan subpart yang berhasil diekstrak AI sebelum disubmit ke database.
- [ ] **2.4 Human-in-the-Loop Dialog**:
  UI pop-up jika ada dosen ambigu atau aturan jadwal yang butuh klarifikasi pengguna.
- [ ] **2.5 One-Click Live Commit**:
  Tombol pengiriman akhir yang memicu penulisan ke database UniTime dan menampilkan laporan audit status HTTP 200.
- [ ] **2.6 Deployment Vercel**:
  Deploy otomatis ke Vercel dan menghubungkan variabel environment `NEXT_PUBLIC_API_URL=https://unitime-api.hanavy.online`.

---

#### 🔹 Fase 3: User Acceptance Testing (UAT) & Monitoring
- [ ] **3.1 Pengujian End-to-End Realistis**:
  Menguji alur nyata: membuka website di Vercel $\rightarrow$ upload dokumen jadwal Excel $\rightarrow$ review di UI $\rightarrow$ klik Submit $\rightarrow$ cek data di database MySQL Tencent VPS.
- [ ] **3.2 Uji Beban Memori & Stabilitas**:
  Memastikan RAM Tencent VPS tetap stabil di bawah 1.5 GB dan tidak mengganggu proses AdsPower/Node.js lainnya.

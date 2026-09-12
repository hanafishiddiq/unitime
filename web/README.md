# UniTime AI Smart Ingestion Web Frontend

Production-ready Next.js web application for autonomous academic curriculum ingestion, Human-in-the-Loop conflict disambiguation, and UniTime database synchronization.

---

## 🌟 Key Features

1. **Multi-Format Curriculum Ingestion**:
   - Drag-and-drop or file picker for `.pdf`, `.xlsx`, `.xlsm`, `.xls`, `.csv`, `.tsv`, `.txt`, `.md`, `.json`, and `.log`.
   - Ingestion options: LLM Provider selection (Google Gemini 1.5, OpenAI GPT-4o, OpenRouter/Custom, or Mock), Model override, Dry-Run toggle, and Strict Semantic Validation.

2. **Real-time Pipeline Progress & Log Stream**:
   - Live status badges: `Queued`, `Processing`, `Waiting for Input`, `Completed`, `Failed`.
   - Dynamic step progression tracking: File Upload &rarr; AI Extraction &rarr; Semantic Validation &rarr; Disambiguation &rarr; Canonical Ready.
   - Chunk execution metrics (`Chunk X of Y`) and status logs.

3. **Human-in-the-Loop Disambiguation (HITL)**:
   - Activates automatically when the AI agent detects scheduling conflicts or room capacity deficits (`waiting_disambiguation`).
   - Displays clear context (capacity deficit, conflict types, affected courses and sections).
   - One-click choice buttons (e.g. *Allow overflow*, *Reassign to larger hall*, *Split into two sections*) and custom administrative directives.

4. **Curriculum Offerings Preview Table**:
   - Comprehensive overview of extracted academic courses, credits / SKS, instructional types (`Lec`, `Lab`, `Rec`), configurations count, class sections, and assigned instructors.
   - Search & filtering by course code, title, or instructor name.
   - Real-time schema and semantic validation error/warning inspection.

5. **One-Click UniTime Commit Action**:
   - Commits canonical timetable payloads directly to the UniTime REST API endpoint (`/api/smart-ingest`).
   - Detailed response feedback with synchronization counts.
   - Direct link and modal viewer for generated Executive Markdown Audit Reports.

---

## 🚀 Getting Started

### Prerequisites

- Node.js 18.17+ or [Bun](https://bun.sh/) 1.0+
- Running UniTime AI Gateway backend (`ai-gateway/server.py` at `http://localhost:8005` or production URL)

### Installation

```bash
# Navigate to web directory
cd web

# Install dependencies using Bun or npm
bun install
# or
npm install
```

### Environment Configuration

Create a `.env.local` file in `web/`:

```env
# URL of the UniTime AI Ingestion Gateway FastAPI server
NEXT_PUBLIC_API_URL=https://unitime-api.hanavy.online
# Or for local development:
# NEXT_PUBLIC_API_URL=http://localhost:8005
```

### Running Locally

```bash
# Start development server on port 3000
bun run dev
# or
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

### Building for Production

```bash
bun run build
# or
npm run build
```

---

## ☁️ Vercel Deployment Instructions

Deploying the UniTime AI Web Frontend to Vercel is seamless:

### Option 1: Via Vercel CLI

```bash
cd web
npm install -g vercel
vercel login
vercel --prod
```

During prompts:
- **Root Directory**: `web`
- **Framework Preset**: `Next.js`
- **Environment Variables**:
  - Add `NEXT_PUBLIC_API_URL` set to your backend gateway URL (e.g., `https://unitime-api.hanavy.online`).

### Option 2: Via Vercel Web Dashboard

1. Push this repository to GitHub or GitLab.
2. Go to [vercel.com](https://vercel.com) and click **"Add New Project"**.
3. Import your repository (`UniTime Fork`).
4. In the **Configure Project** screen:
   - Set **Root Directory** to `web`.
   - Framework Preset should automatically be detected as **Next.js**.
   - Build Command: `npm run build` or `bun run build`.
   - Output Directory: `.next`.
5. Under **Environment Variables**, add:
   - Key: `NEXT_PUBLIC_API_URL`
   - Value: `https://unitime-api.hanavy.online`
6. Click **Deploy**. Vercel will automatically build and distribute the application globally with edge caching.

---

## 📁 Architecture & File Structure

```
web/
├── app/
│   ├── globals.css              # Modern dark/light styling, accessible tokens
│   ├── layout.tsx               # Root layout, fonts, metadata, Toaster
│   └── page.tsx                 # Central state-driven dashboard page
├── components/
│   ├── AuditReportsModal.tsx    # Modal for previewing and downloading audit reports
│   ├── CommitSection.tsx        # One-click commit to UniTime with response banner
│   ├── CurriculumOfferingsTable.tsx # Course offerings preview table with search & filter
│   ├── DisambiguationCard.tsx   # Human-in-the-Loop conflict resolution component
│   ├── FileUploadDropzone.tsx   # File drag & drop zone with provider & validation options
│   ├── Header.tsx               # Header with UniTime branding and server health status pill
│   └── ProgressLogStream.tsx    # Real-time progress bar, steps, and chunk logs
├── lib/
│   ├── api.ts                   # Fully typed API client for ai-gateway endpoints
│   └── utils.ts                 # Classname merge (clsx + tailwind-merge) & formatters
├── next.config.mjs              # Next.js configuration
├── package.json                 # Dependencies & scripts
├── postcss.config.mjs           # PostCSS Tailwind config
├── tailwind.config.ts           # Tailwind theme configuration
└── tsconfig.json                # TypeScript compiler configuration
```

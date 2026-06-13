# 🌌 Sovereign Nexus Orchestrator (SNO)
> **The Executive Layer for Cognitive Intelligence**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-blue.svg)]()
[![LangGraph Powered](https://img.shields.io/badge/PoweredBy-LangGraph-orange.svg)]()
[![Streamlit UI](https://img.shields.io/badge/UI-Streamlit-FF4B4B.svg)]()

⚠️ **PROJECT STATUS: CONCEPTUAL BLUEPRINT**
*This repository is a conceptual architectural blueprint and functional prototype. It was designed and developed by an AI agent running on **[Arena.ai](https://arena.ai)**. While the provided code is functional as a Proof-of-Concept (PoC), it is intended as a high-level guide for developers to build a production-grade Agentic OS.*

---

## 📖 Visi & Filosofi

**Sovereign Nexus Orchestrator (SNO)** adalah sebuah *Agentic Operating System* yang diimplementasikan sebagai **MCP (Model Context Protocol) Server**. 

SNO lahir dari sebuah observasi kritis: **LLM hebat dalam bernalar (Reasoning), tetapi buruk dalam eksekusi yang presisi (Execution).** 

Dalam sistem tradisional, agen AI mencoba melakukan keduanya secara bersamaan, yang sering menyebabkan "Agent Amnesia", halusinasi alur kerja, dan ketergantungan total pada prompt yang rapuh. SNO memutus siklus ini dengan memisahkan **Kognisi** dari **Eksekusi**.

- **The Brain (Client)**: AI Agent (seperti Hermes) yang fokus pada strategi, refleksi, dan tujuan akhir.
- **The Body (SNO)**: Lapisan eksekusi yang memastikan rencana strategis diubah menjadi tindakan deterministik, terukur, dan tahan gagal.

---

## 🎯 Masalah yang Diselesaikan

| Masalah Tradisional | Solusi SNO | Mekanisme |
| :--- | :--- | :--- |
| **Execution Drift** | Deterministic Playbooks | Menggunakan YAML $\rightarrow$ LangGraph untuk alur kerja yang pasti. |
| **Agent Amnesia** | Sovereign State Sentry | Checkpointing state per-node untuk tugas jangka panjang. |
| **Tool Bloat** | Compound MCP Tools | Membungkus banyak tool kecil menjadi satu "Playbook" besar. |
| **Timeout / Hang** | Async Job Pattern | Eksekusi background dengan pola `Job ID` $\rightarrow$ `Polling`. |
| **Context Loss** | Cognitive Summarization | Meringkas log teknis menjadi poin-poin kognitif untuk LLM. |

---

## 🏗️ Arsitektur Sistem

SNO mengadopsi struktur **Tri-Layer Architecture**:

### 1. Cognitive Layer (Client)
Tempat bersemayamnya model LLM (Hermes Agent). Ia hanya mengirimkan "Niat" (Intent) melalui protokol MCP.

### 2. Executive Layer (SNO Server)
Jantung dari sistem ini yang terdiri dari:
- **Playbook Compiler**: Mengubah definisi YAML menjadi grafik eksekusi `StateGraph`.
- **SNO Engine**: Mengelola eksekusi asinkron via Celery/Redis.
- **State-Sentry**: Menyimpan snapshot setiap langkah di PostgreSQL.

### 3. Resource Layer (The Nexus)
Pintu akses tunggal ke dunia luar:
- **Hybrid Memory**: Integrasi LlamaIndex (Vector) & Neo4j (Graph).
- **MCP Bridge**: Proxy untuk memanggil tool dari server MCP eksternal lainnya.

---

## 🛠️ MCP Tool Registry (v2.0)

SNO Server mengekspos 10 tools MCP untuk dioperasikan oleh AI Agent (seperti Hermes):

| Nama Tool | Deskripsi | Input Utama |
| :--- | :--- | :--- |
| `sno_run_playbook` | Menjalankan playbook YAML secara asinkron di latar belakang. | `pb_id` (ID playbook), `query` (input awal) |
| `sno_poll_status` | Memeriksa status eksekusi job (`pending`, `running`, `success`, `failed`, `cancelled`) dan mengambil hasil akhir. | `job_id` (8-karakter ID) |
| `sno_cancel_job` | Membatalkan pekerjaan yang sedang berjalan di antrean. | `job_id` |
| `sno_list_playbooks` | Menampilkan seluruh daftar playbook YAML yang tersedia di folder `playbooks/`. | (tanpa input) |
| `sno_create_playbook` | Membuat playbook YAML baru secara dinamis menggunakan AI Planner. | `goal` (tujuan alur kerja), `context` (opsional) |
| `sno_hybrid_query` | Melakukan query hibrida (pencarian semantik vektor Qdrant + relasi NetworkX/Neo4j). | `query` (pencarian teks), `top_k` |
| `sno_memory_store` | Menyimpan potongan informasi/dokumen baru ke dalam Knowledge Nexus. | `content` (teks), `entity_name` (opsional), `tags` |
| `sno_health_check` | Memeriksa konektivitas subsistem database, Redis, Qdrant, dan Neo4j. | (tanpa input) |
| `sno_get_metrics` | Mengembalikan snapshot metrik performa eksekusi job (durasi, error, pemanggilan tool). | (tanpa input) |
| `sno_call_external_agent` | Memproksi pemanggilan tool ke agen/server MCP eksternal lainnya. | `server_url`, `tool_name`, `args` |

---

## 💻 SNO Ops Console (UI Interface)

SNO dilengkapi dengan dashboard manajemen berbasis **Streamlit** untuk memberikan observabilitas penuh bagi operator manusia:

- 🚀 **Job Monitor**: Pantau status eksekusi `job_id` secara real-time, lihat progress, dan ambil hasil akhir.
- 📜 **Playbook Manager**: Editor visual untuk mengubah logika YAML Playbook tanpa perlu restart server.
- 🧠 **Nexus Explorer**: Interface untuk memverifikasi data di dalam memori hybrid (Semantic & Relational).
- 📊 **Metrics & Prometheus**: Snapshot metrik kegagalan, volume request, durasi job (p50/p95/p99) yang dapat diintegrasikan dengan Grafana.
- 📋 **System Logs**: Audit trail lengkap untuk debugging eksekusi agen.

---

## 🚀 Panduan Memulai

### Prasyarat
- Python 3.11+
- Redis (untuk antrean tugas)
- Qdrant & Neo4j (opsional - cadangan NetworkX/In-memory aktif otomatis jika mati)

### Instalasi
```bash
git clone https://github.com/your-username/sovereign-nexus-orchestrator.git
cd sovereign-nexus-orchestrator
pip install -r requirements.txt
cp .env.example .env
```

### ⚙️ Konfigurasi `.env`

Lengkapi konfigurasi keamanan, kecerdasan AI, dan pemantauan sistem di berkas `.env` Anda:

```env
# Keamanan (Security)
ENABLE_AUTH=true                     # Aktifkan autentikasi API Key
SNO_API_KEY=rahasia-api-key          # Kunci API bersama untuk client

# AI Planner (LLM)
DEFAULT_LLM_PROVIDER=openai          # 'openai' atau 'anthropic'
DEFAULT_LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-...

# Pemantauan (Metrics)
ENABLE_METRICS=true                  # Aktifkan metrik endpoint /metrics
METRICS_PORT=9090                    # Port server metrik Prometheus

# Subsistem DB & Antrean
DATABASE_URL=sqlite:///./data/sno_state.db
REDIS_URL=redis://localhost:6379/0
```


### Menjalankan Sistem
SNO berjalan dengan dua komponen utama:

1. **Start MCP Server (Backend)**:
   ```bash
   python src/main.py
   ```
   *Kini Hermes Agent dapat terhubung dan memerintah SNO via MCP.*

2. **Start Ops Console (Frontend)**:
   ```bash
   streamlit run src/ui/app.py
   ```
   *Buka browser di `http://localhost:8501` untuk mengelola SNO.*

---

## 💡 Inspirasi & Silsilah Teknologi

SNO adalah sintesis dari beberapa terobosan teknologi:
- **LangGraph**: Mengambil konsep *State Machine* untuk stabilitas alur.
- **MCP (Anthropic)**: Mengadopsi standar interface universal.
- **LlamaIndex & Neo4j**: Menginspirasi pembuatan *Hybrid Memory*.
- **Dual Process Theory**: Memisahkan "Sistem 1" (Eksekusi/SNO) dan "Sistem 2" (Penalaran/Hermes).
- **OS Kernel**: Meniru manajemen sumber daya dan sandboxing sistem operasi.

---

## 📁 Struktur Proyek
```text
├── src/
│   ├── main.py             # Entry point MCP Server
│   ├── core/               # LangGraph Compiler & State Manager
│   ├── mcp/                # MCP Tools & Server Interface
│   ├── memory/             # Hybrid Nexus Logic (Vector + Graph)
│   └── ui/                 # Streamlit Ops Console
├── playbooks/              # Library YAML Playbooks
├── docs/                   # Arsitektur & Spesifikasi
└── tests/                  # Integration & Unit Tests
```

---

## 🙏 Acknowledgements

Proyek ini adalah hasil eksplorasi arsitektural yang didukung oleh:
- **Anthropic**, untuk standar *Model Context Protocol (MCP)*.
- **LangChain**, untuk framework *LangGraph*.
- **LlamaIndex & Neo4j**, untuk standar *Knowledge Retrieval*.
- **Arena.ai**, environment agentic yang memungkinkan proses riset, perancangan, dan pembuatan prototype sistem ini secara otomatis oleh AI.

## 📄 Lisensi
Distributed under the MIT License. See `LICENSE` for more information.

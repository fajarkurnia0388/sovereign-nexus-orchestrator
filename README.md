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

## 💻 SNO Ops Console (UI Interface)

SNO dilengkapi dengan dashboard manajemen berbasis **Streamlit** untuk memberikan observabilitas penuh bagi operator manusia:

- 🚀 **Job Monitor**: Pantau status eksekusi `job_id` secara real-time, lihat progress, dan ambil hasil akhir.
- 📜 **Playbook Manager**: Editor visual untuk mengubah logika YAML Playbook tanpa perlu restart server.
- 🧠 **Nexus Explorer**: Interface untuk memverifikasi data di dalam memori hybrid (Semantic & Relational).
- 📋 **System Logs**: Audit trail lengkap untuk debugging eksekusi agen.

---

## 🚀 Panduan Memulai

### Prasyarat
- Python 3.11+
- Redis (untuk antrean tugas)
- PostgreSQL (untuk persistensi state)
- Qdrant/Neo4j (untuk Knowledge Nexus)

### Instalasi
```bash
git clone https://github.com/fajarkurnia0388/sovereign-nexus-orchestrator.git
cd sovereign-nexus-orchestrator
pip install -r requirements.txt
cp .env.example .env
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

# SNO Repository — Audit & Revision Report

> **Evaluator:** Claude Sonnet 4.6  
> **Date:** June 2026  
> **Scope:** All files in the initial commit

---

## Ringkasan Eksekutif

Repo SNO memiliki arsitektur yang baik dan visi yang jelas, namun ditemukan **3 bug kritis** yang akan mencegah aplikasi berjalan dengan benar, plus sejumlah isu sedang dan kecil. Semua isu telah diperbaiki di file revisi.

---

## Bug Kritis (Aplikasi Akan Gagal)

### 🔴 BUG-1 · `SqliteSaver.from_conn_string()` salah digunakan

**File:** `src/core/engine.py`  
**Dampak:** State checkpointing tidak berfungsi sama sekali — setiap job kehilangan state-nya.

**Penjelasan:**  
Pada LangGraph 1.x, `SqliteSaver.from_conn_string()` adalah **context manager factory** yang mengembalikan `contextlib._GeneratorContextManager`, bukan instance `SqliteSaver`. Kode lama meneruskan context manager ini langsung ke `workflow.compile(checkpointer=...)` — ini akan gagal secara silent atau raise TypeError saat graph mencoba mengakses checkpointer.

```python
# ❌ SALAH (kode lama)
memory = SqliteSaver.from_conn_string(db_path)  # ← ini BUKAN SqliteSaver
return workflow.compile(checkpointer=memory)     # ← silent failure

# ✅ BENAR (kode baru)
import sqlite3
self._conn = sqlite3.connect(db_path, check_same_thread=False)
self._checkpointer = SqliteSaver(self._conn)     # ← instance yang benar
```

---

### 🔴 BUG-2 · `pb_id` parameter diabaikan di MCP server

**File:** `src/mcp/server.py`  
**Dampak:** `sno_run_playbook` selalu menjalankan playbook yang sama terlepas dari input pengguna.

```python
# ❌ SALAH (kode lama)
@mcp.tool()
async def run_playbook(pb_id: str, query: str) -> str:
    yaml_config = DEFAULT_RESEARCH_PB  # pb_id diterima tapi DIABAIKAN
    ...

# ✅ BENAR (kode baru)
def _load_playbook_yaml(pb_id: str) -> str:
    path = PLAYBOOKS_DIR / f"{pb_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(...)
    return path.read_text(encoding="utf-8")
```

---

### 🔴 BUG-3 · Paket kritis tidak ada di `requirements.txt`

**File:** `requirements.txt`  
**Dampak:** Instalasi fresh akan langsung gagal saat menjalankan UI.

| Paket Hilang | Digunakan Di | Keterangan |
|---|---|---|
| `streamlit` | `src/ui/app.py` | Framework UI utama |
| `pandas` | `src/ui/app.py` | Tabel job history |
| `nest-asyncio` | `src/ui/app.py` | Fix async di Streamlit |
| `aiosqlite` | LangGraph async | Required oleh AsyncSqliteSaver |
| `langgraph-checkpoint-sqlite` | `engine.py` | Paket terpisah di LangGraph 1.x |
| `llama-index` → `llama-index-core` | `nexus.py` | Nama paket berubah sejak v0.10 |

---

## Isu Sedang (Perilaku Tidak Terduga)

### 🟡 ISU-4 · Edge logic LangGraph duplikat & fragile

**File:** `src/core/engine.py`

Dua loop terpisah yang menangani edges berpotensi membuat konflik. Diganti dengan satu pass yang clean:

```python
# ✅ Satu loop, tiga kasus tercakup dengan jelas
for i, node in enumerate(pb.nodes):
    is_last = (i == len(pb.nodes) - 1)
    if node.next:
        target = node.next           # (a) explicit next
    elif is_last:
        target = END                 # (b) last node → END
    else:
        target = pb.nodes[i+1].id   # (c) fallthrough linear
    workflow.add_edge(node.id, target)
```

---

### 🟡 ISU-5 · Async pattern Streamlit rusak di Python 3.10+

**File:** `src/ui/app.py`

`asyncio.get_event_loop()` raise `DeprecationWarning` (Python 3.10) atau `RuntimeError` (Python 3.12) ketika tidak ada loop aktif di thread saat ini.

```python
# ❌ SALAH (kode lama)
def run_async(coro):
    try:
        loop = asyncio.get_event_loop()    # DeprecationWarning/RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()    # tapi loop baru tidak punya context
    return loop.run_until_complete(coro)

# ✅ BENAR (kode baru)
import nest_asyncio
nest_asyncio.apply()  # patch once at startup

def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)
```

---

### 🟡 ISU-6 · Pydantic v1 Config style di `config.py`

```python
# ❌ SALAH (Pydantic v1 style)
class Settings(BaseSettings):
    class Config:
        env_file = ".env"

# ✅ BENAR (Pydantic v2)
class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}
```

---

### 🟡 ISU-7 · `nx.Graph()` undirected untuk relasi yang directional

**File:** `src/memory/nexus.py`

Relasi seperti `"Hermes --controls--> SNO"` kehilangan arahnya di undirected graph. Diganti dengan `nx.DiGraph()`.

---

### 🟡 ISU-8 · `import pandas as pd` di dalam if-block

**File:** `src/ui/app.py`

Import di dalam block conditional adalah anti-pattern Python — menyebabkan `NameError` jika jalur lain menyentuh `pd`.

---

## Isu Kecil (Best Practice)

### 🔵 ISU-9 · Tidak ada `__init__.py` di seluruh package `src/`

Python module imports (`from src.core.engine import ...`) memerlukan `__init__.py` di setiap directory package. Tanpa ini, import bisa gagal tergantung cara aplikasi dijalankan.

**File baru dibuat:** `src/__init__.py`, `src/core/__init__.py`, `src/mcp/__init__.py`, `src/memory/__init__.py`, `src/ui/__init__.py`, `src/utils/__init__.py`

---

### 🔵 ISU-10 · Seluruh logging via `print()`, tidak ada logging framework

Semua diagnostic output menggunakan `print()` sehingga tidak bisa di-filter, di-level, atau diarahkan ke file.

**File baru:** `src/utils/logger.py` — centralized logging dengan level, format, dan suppression third-party noise.

---

### 🔵 ISU-11 · MCP tool names tidak ikut konvensi

MCP best practice: `{service}_{action}`. Tool lama (`run_playbook`, `poll_status`) diganti jadi `sno_run_playbook`, `sno_poll_status`, `sno_hybrid_query`, `sno_call_external_agent`.

**Catatan:** Ini breaking change — update Claude/Hermes agent configuration sesuai nama tool baru.

---

### 🔵 ISU-12 · Tidak ada tool annotations & Pydantic input models di MCP server

Tool tanpa `annotations` tidak bisa memberi hint ke agent soal sifat operasi (read-only, destructive, idempotent). Semua tool sekarang memiliki:
- `annotations` lengkap (readOnlyHint, destructiveHint, idempotentHint, openWorldHint)
- Pydantic `BaseModel` dengan `Field(description=...)` untuk setiap parameter
- Docstring komprehensif

---

### 🔵 ISU-13 · Import tidak terpakai di `nexus.py`

`from llama_index.core.memory import ChatMemoryBuffer` diimpor tapi tidak pernah digunakan.

---

### 🔵 ISU-14 · Dockerfile berjalan sebagai root, Streamlit port tidak di-expose

- Tambah `useradd sno` + `USER sno`
- Tambah `EXPOSE 8501` untuk Streamlit

---

### 🔵 ISU-15 · Tidak ada `docker-compose.yml`

README menyebutkan dua service (MCP + Streamlit) tapi tidak ada cara untuk menjalankan keduanya bersama. File `docker-compose.yml` baru mengorkestrasi `sno-mcp`, `sno-ui`, dan `redis`.

---

## Daftar File Revisi

| File | Status | Perubahan Utama |
|---|---|---|
| `requirements.txt` | **Revisi** | Tambah 6 paket hilang, pin versi, perbaiki nama paket |
| `src/__init__.py` | **Baru** | Package marker |
| `src/config.py` | **Revisi** | Pydantic v2 `model_config` |
| `src/core/__init__.py` | **Baru** | Package marker |
| `src/core/engine.py` | **Revisi** | Fix BUG-1 SqliteSaver, fix ISU-4 edge logic, add logging |
| `src/mcp/__init__.py` | **Baru** | Package marker |
| `src/mcp/server.py` | **Revisi** | Fix BUG-2 playbook loading, Pydantic models, MCP naming |
| `src/memory/__init__.py` | **Baru** | Package marker |
| `src/memory/nexus.py` | **Revisi** | DiGraph, remove unused import, graceful degradation |
| `src/ui/__init__.py` | **Baru** | Package marker |
| `src/ui/app.py` | **Revisi** | Fix ISU-5 async, fix ISU-8 imports, better UX |
| `src/utils/__init__.py` | **Baru** | Package marker |
| `src/utils/logger.py` | **Baru** | Centralized logging |
| `src/main.py` | **Revisi** | Call setup_logging() sebelum import MCP server |
| `Dockerfile` | **Revisi** | Non-root user, expose port 8501 |
| `docker-compose.yml` | **Baru** | Orkestrasi semua services |

---

## Rekomendasi Lanjutan (Di Luar Scope Revisi Ini)

1. **Pin versi LangGraph di YAML playbook schema** — tambah `langgraph_version` field agar playbook portabel.
2. **Ganti in-memory job store** (`executor.jobs` dict) dengan Redis untuk multi-instance deployment.
3. **Implementasikan real vector store** — sambungkan `KnowledgeNexus` ke Qdrant dengan dokumen nyata.
4. **Tambah authentication** ke MCP server jika di-expose ke jaringan publik.
5. **Unit tests** — buat `tests/` dengan test untuk `PlaybookCompiler.compile()` dan `SNOExecutor.run_job()`.
6. **Upgrade async execution** — ganti `asyncio.create_task()` dengan Celery worker untuk queue yang tahan restart.

# FileVault ⚡️

A high-performance, multi-core CLI deduplication engine written in Python featuring a 3-tier heuristic pipeline and bounded memory streaming.

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Concurrency](https://img.shields.io/badge/concurrency-multiprocessing-orange.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

---

## 🚀 Key Features

* **⚡ Multi-Core Parallel Processing**: Utilizes `concurrent.futures.ProcessPoolExecutor` to distribute cryptographic hashing across all available CPU cores, bypassing Python's Global Interpreter Lock (GIL).
* **🧠 3-Tier Heuristic Pipeline**:
  * **Tier 1 (Byte-Size Grouping)**: Instantaneous elimination of unique file sizes with zero disk hashing.
  * **Tier 2 (8 KB Head + Tail Quick-Hash)**: Samples the first 4 KB (header) and last 4 KB (footer), eliminating 95%+ of false matches in sub-milliseconds.
  * **Tier 3 (Full Cryptographic Verification)**: Full chunked SHA-256 verification executed only on surviving candidate pairs.
* **🛡️ macOS Safety Shield**: Automatically protects `.app` application bundles, `.git` repositories, `.Trash`, and dependency folders from accidental modification.
* **💾 Memory-Safe Streaming**: 64 KB bounded streaming buffers ensure safe processing of 50 GB+ files with less than 15 MB of system RAM.
* **🎨 Modern Terminal UX**: Colorized tabular reports, status spinners, and space-reclamation statistics powered by `rich`.

---

## 🧠 Pipeline Architecture

```
                       [ All Target Files ]
                                │
            (Tier 1: Byte-Size Grouping + Safety Shield)
                                │
                   [ Size Collision Candidates ]
                                │
            (Tier 2: Parallel 8 KB Head + Tail Quick-Hash)
            [ Core 1 ] [ Core 2 ] [ Core 3 ] ... [ Core N ]
                                │
                 [ High-Probability Candidates ]
                                │
            (Tier 3: Parallel Full Chunked SHA-256)
            [ Core 1 ] [ Core 2 ] [ Core 3 ] ... [ Core N ]
                                │
                   [ 100% Verified Duplicates ]
```

---

## 📦 Installation

```bash
# Clone the repository
git clone https://github.com/your-username/file-vault.git
cd file-vault

# Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## 🛠️ Usage

### 1. Dry Run Scan (Default)

```bash
python vault.py ~/Downloads
```

### 2. Clean Duplicates with Confirmation

```bash
python vault.py ~/Downloads --delete
```

### 3. Override Safety Shield

```bash
python vault.py /path/to/folder --include-protected
```

---

## 📄 License

MIT License

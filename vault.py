import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import os
from pathlib import Path
import sys

# pyrefly: ignore[missing-import]
from rich.console import Console
# pyrefly: ignore[missing-import]
from rich.panel import Panel
# pyrefly: ignore[missing-import]
from rich.prompt import Confirm
# pyrefly: ignore[missing-import]
from rich.table import Table

console = Console()

# Protected system paths and bundle types
PROTECTED_PATTERNS = {".git", ".Trash", "node_modules", ".venv", "__pycache__"}


def is_protected_path(path: Path) -> bool:
    """Checks if a path is inside a macOS .app bundle or protected system directory."""
    for part in path.parts:
        if part.endswith(".app") or part in PROTECTED_PATTERNS:
            return True
    return False


def format_bytes(size: int) -> str:
    """Converts raw bytes to human-readable format (KB, MB, GB)."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:3.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


# =====================================================================
# Top-Level Worker Functions for Multi-Core Parallel Execution
# (Must be top-level functions so Python can serialize them across cores)
# =====================================================================

def get_quick_hash(file_path: Path, sample_size: int = 4096) -> str:
    """8KB Head+Tail Quick Hash."""
    size = file_path.stat().st_size
    if size <= sample_size * 2:
        return get_full_hash(file_path)

    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        hasher.update(f.read(sample_size))
        f.seek(size - sample_size)
        hasher.update(f.read(sample_size))

    return hasher.hexdigest()


def get_full_hash(file_path: Path) -> str:
    """Bounded 64KB chunked SHA-256 hash."""
    hasher = hashlib.sha256()
    chunk_size = 65536

    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)

    return hasher.hexdigest()


def _parallel_quick_worker(path_str: str) -> tuple[str, str | None]:
    """Worker executed in parallel across CPU cores for Tier 2."""
    path = Path(path_str)
    try:
        return path_str, get_quick_hash(path)
    except (PermissionError, FileNotFoundError):
        return path_str, None


def _parallel_full_worker(path_str: str) -> tuple[str, str | None]:
    """Worker executed in parallel across CPU cores for Tier 3."""
    path = Path(path_str)
    try:
        return path_str, get_full_hash(path)
    except (PermissionError, FileNotFoundError):
        return path_str, None


# =====================================================================
# Main Engine Pipeline
# =====================================================================

def find_duplicates(target_path: Path, include_protected: bool = False):
    """
    3-Tier Multi-Core Parallel Deduplication Engine:
    Tier 1: Group by Byte Size (Single-thread traversal)
    Tier 2: Multi-Core 8KB Quick-Hash (ProcessPoolExecutor)
    Tier 3: Multi-Core Full SHA-256 (ProcessPoolExecutor)
    """
    files_by_size = {}
    total_files = 0
    protected_skipped = 0
    cpu_cores = os.cpu_count() or 4

    # TIER 1: Size grouping with Safety Shield
    with console.status("[bold cyan]Tier 1: Scanning files with Safety Shield...", spinner="dots"):
        for file_path in target_path.rglob("*"):
            if file_path.is_file():
                if not include_protected and is_protected_path(file_path):
                    protected_skipped += 1
                    continue

                total_files += 1
                try:
                    size = file_path.stat().st_size
                except (PermissionError, FileNotFoundError):
                    continue

                if size not in files_by_size:
                    files_by_size[size] = []
                files_by_size[size].append(file_path)

    size_candidates = {
        size: paths for size, paths in files_by_size.items() if len(paths) > 1
    }

    # Flatten candidates for parallel processing
    tier2_inputs = [str(p) for paths in size_candidates.values() for p in paths]
    size_map = {str(p): p.stat().st_size for paths in size_candidates.values() for p in paths}

    # TIER 2: Parallel 8KB Quick-Hash across all CPU cores
    quick_hash_groups = {}
    with console.status(
        f"[bold cyan]Tier 2: Multi-core Quick-Hashing across {cpu_cores} cores...", spinner="dots"
    ):
        with ProcessPoolExecutor(max_workers=cpu_cores) as executor:
            results = executor.map(_parallel_quick_worker, tier2_inputs, chunksize=16)
            for path_str, q_hash in results:
                if q_hash is not None:
                    size = size_map[path_str]
                    group_key = (size, q_hash)
                    if group_key not in quick_hash_groups:
                        quick_hash_groups[group_key] = []
                    quick_hash_groups[group_key].append(Path(path_str))

    quick_candidates = {
        k: paths for k, paths in quick_hash_groups.items() if len(paths) > 1
    }

    # Flatten surviving candidates for Tier 3
    tier3_inputs = [str(p) for paths in quick_candidates.values() for p in paths]

    # TIER 3: Parallel Full SHA-256 across all CPU cores
    final_duplicates = {}
    with console.status(
        f"[bold cyan]Tier 3: Multi-core Full SHA-256 across {cpu_cores} cores...", spinner="dots"
    ):
        with ProcessPoolExecutor(max_workers=cpu_cores) as executor:
            results = executor.map(_parallel_full_worker, tier3_inputs, chunksize=8)
            for path_str, full_hash in results:
                if full_hash is not None:
                    if full_hash not in final_duplicates:
                        final_duplicates[full_hash] = []
                    final_duplicates[full_hash].append(Path(path_str))

    duplicate_groups = {
        h: paths for h, paths in final_duplicates.items() if len(paths) > 1
    }
    return (
        total_files,
        protected_skipped,
        len(size_candidates),
        len(quick_candidates),
        duplicate_groups,
        cpu_cores,
    )


def main():
    parser = argparse.ArgumentParser(
        description="FileVault: Multi-Core Parallel Deduplication Engine with Safety Shield."
    )
    parser.add_argument(
        "folder",
        type=Path,
        nargs="?",
        default=Path("sandbox"),
        help="Target folder to scan (default: sandbox)",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete duplicate copies after confirmation.",
    )
    parser.add_argument(
        "--include-protected",
        action="store_true",
        help="Scan inside macOS .app bundles, .git, and dependency directories.",
    )

    args = parser.parse_args()

    if not args.folder.exists():
        console.print(f"[bold red]Error:[/bold red] Folder '{args.folder}' does not exist!")
        sys.exit(1)

    console.print(
        Panel.fit(
            f"[bold yellow]FileVault (Multi-Core Engine)[/bold yellow] | Target: [green]{args.folder.resolve()}[/green]",
            border_style="cyan",
        )
    )

    (
        total_files,
        protected_skipped,
        size_hits,
        quick_hits,
        duplicate_groups,
        cpu_cores,
    ) = find_duplicates(args.folder, include_protected=args.include_protected)

    if not duplicate_groups:
        console.print("\n[bold green]✨ Clean![/bold green] No duplicate files found.")
        if protected_skipped > 0:
            console.print(f"[dim]🛡️  Protected {protected_skipped} application/system file(s) from scan.[/dim]")
        return

    # Calculate duplicate metrics
    total_duplicate_copies = 0
    total_wasted_bytes = 0

    table = Table(
        title="Duplicate Files Analysis (Multi-Core Verified SHA-256)",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Type", style="bold", width=12)
    table.add_column("File Path", style="dim")
    table.add_column("Size", justify="right")
    table.add_column("Verified Hash", style="cyan")

    for f_hash, files in duplicate_groups.items():
        original = files[0]
        extra_copies = files[1:]
        size = original.stat().st_size

        table.add_row("ORIGINAL", str(original), format_bytes(size), f_hash[:10] + "...")

        for copy in extra_copies:
            total_duplicate_copies += 1
            total_wasted_bytes += size
            table.add_row(
                "[red]DUPLICATE[/red]",
                str(copy),
                format_bytes(size),
                f_hash[:10] + "...",
            )

    console.print()
    console.print(table)

    mode_text = "[red]DELETE MODE[/red]" if args.delete else "[yellow]DRY-RUN MODE[/yellow]"
    summary_message = (
        f"• Total user files scanned: [bold]{total_files}[/bold]\n"
        f"• 🛡️ Protected files shielded: [bold green]{protected_skipped}[/bold green]\n"
        f"• ⚡ CPU Cores utilized: [bold green]{cpu_cores} parallel worker cores[/bold green]\n"
        f"• Tier 1 Size collisions: [bold cyan]{size_hits}[/bold cyan]\n"
        f"• Tier 2 Quick-Hash candidate groups: [bold cyan]{quick_hits}[/bold cyan]\n"
        f"• Redundant copies: [bold red]{total_duplicate_copies}[/bold red]\n"
        f"• Reclaimable disk space: [bold green]{format_bytes(total_wasted_bytes)}[/bold green]\n"
        f"• Mode: {mode_text}"
    )
    console.print()
    console.print(Panel(summary_message, title="Performance & Summary", border_style="blue", expand=False))

    # Deletion Flow
    if args.delete:
        if Confirm.ask(
            f"\n[bold red]Permanently delete {total_duplicate_copies} duplicate files?[/bold red]"
        ):
            for files in duplicate_groups.values():
                for copy in files[1:]:
                    copy.unlink()
            console.print(
                f"[bold green]✔ Successfully deleted {total_duplicate_copies} files and reclaimed {format_bytes(total_wasted_bytes)}![/bold green]"
            )
        else:
            console.print("[yellow]Operation cancelled. No files were deleted.[/yellow]")
    else:
        console.print("\n[dim]💡 Tip: Run with [bold]--delete[/bold] to remove duplicate copies after review.[/dim]")


if __name__ == "__main__":
    main()
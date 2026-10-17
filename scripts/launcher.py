"""Guided local setup and launcher for this AURA-Bio checkout.

The launcher is deliberately a thin wrapper around the documented commands. It
never assumes a particular drive, does not upload data, and only installs tools
or dependencies after the user presses the corresponding button.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


DEFAULT_INDEX_ROOT = Path(r"G:\aura_data\AURA-Bio-Index")


@dataclass(frozen=True)
class Check:
    name: str
    state: str
    detail: str
    required: bool = False


def project_root(start: Path) -> Path:
    """Find a checkout from this script, the current directory, or a parent."""
    candidates = [start.resolve(), Path.cwd().resolve()]
    for candidate in candidates:
        for folder in (candidate, *candidate.parents):
            if (
                (folder / "pyproject.toml").is_file()
                and (folder / "aura_bio_system").is_dir()
                and (folder / "corpus_pipeline").is_dir()
                and (folder / "frontend" / "package.json").is_file()
            ):
                return folder
    raise FileNotFoundError(
        "Could not find an AURA-Bio checkout. Run this from the repository or "
        "keep scripts/launcher.py inside it."
    )


def read_dotenv(path: Path) -> dict[str, str]:
    """Read simple KEY=value entries without importing the application stack."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def version_at_least(text: str, minimum: tuple[int, int]) -> bool:
    try:
        major, minor = (int(part) for part in text.split(".")[:2])
        return (major, minor) >= minimum
    except (TypeError, ValueError):
        return False


class AuraEnvironment:
    def __init__(self, root: Path, index_root: Path | None = None) -> None:
        self.root = root
        self.python = Path(sys.executable)
        self.npm = shutil.which("npm.cmd") or shutil.which("npm")
        env_values = read_dotenv(root / ".env")
        configured = os.environ.get("AURA_INDEX_ROOT") or env_values.get("AURA_INDEX_ROOT")
        self.index_root = index_root or (Path(configured) if configured else DEFAULT_INDEX_ROOT)

    def checks(self) -> list[Check]:
        checks: list[Check] = []
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        checks.append(
            Check(
                "Python 3.11+",
                "ready" if sys.version_info >= (3, 11) else "missing",
                python_version,
                required=True,
            )
        )
        modules_ok = subprocess.run(
            [str(self.python), "-c", "import aura_bio, aura_bio_pipeline, aura_corpus"],
            cwd=self.root,
            capture_output=True,
            text=True,
        ).returncode == 0
        checks.append(
            Check(
                "Local Python packages",
                "ready" if modules_ok else "action",
                "installed" if modules_ok else "Use ‘Install Python packages’",
                required=True,
            )
        )
        node = shutil.which("node.exe") or shutil.which("node")
        if node:
            result = subprocess.run([node, "--version"], capture_output=True, text=True)
            node_version = result.stdout.strip().lstrip("v")
            node_ready = result.returncode == 0 and version_at_least(node_version, (22, 13))
            checks.append(
                Check(
                    "Node 22.13+",
                    "ready" if node_ready else "action",
                    node_version or "unreadable version",
                    required=True,
                )
            )
        else:
            checks.append(Check("Node 22.13+", "missing", "Not on PATH", required=True))
        frontend_ready = (self.root / "frontend" / "node_modules").is_dir()
        checks.append(
            Check(
                "Frontend packages",
                "ready" if frontend_ready else "action",
                "installed" if frontend_ready else "Use ‘Install frontend packages’",
                required=True,
            )
        )
        env_present = (self.root / ".env").is_file()
        checks.append(
            Check(
                "Environment file",
                "ready" if env_present else "action",
                ".env found" if env_present else "Copy .env.example to .env to customize local paths",
            )
        )
        index_ok = (self.index_root / "core-sparse.sqlite3").is_file()
        checks.append(
            Check(
                "Retrieval index",
                "ready" if index_ok else "optional",
                str(self.index_root) if index_ok else f"Not found at {self.index_root} (API can still start offline)",
            )
        )
        ollama = shutil.which("ollama.exe") or shutil.which("ollama")
        checks.append(
            Check(
                "Ollama",
                "ready" if ollama else "optional",
                "available" if ollama else "Optional; answers fall back to extractive mode",
            )
        )
        return checks

    def ready_to_launch(self) -> bool:
        required = [check for check in self.checks() if check.required]
        return all(check.state == "ready" for check in required)

    def install_python(self) -> tuple[bool, str]:
        command = [
            str(self.python),
            "-m",
            "pip",
            "install",
            "-e",
            ".",
            "-e",
            str(self.root / "corpus_pipeline"),
            "-e",
            f"{self.root / 'aura_bio_system'}[api,study]",
        ]
        return run_command(command, self.root)

    def install_frontend(self) -> tuple[bool, str]:
        if not self.npm:
            return False, "npm is not available. Install Node 22.13+ first."
        return run_command([self.npm, "install"], self.root / "frontend")

    def install_tool(self, package_id: str) -> tuple[bool, str]:
        winget = shutil.which("winget.exe") or shutil.which("winget")
        if not winget:
            return False, "winget is unavailable. Install the tool manually, then click Refresh."
        return run_command(
            [winget, "install", "--id", package_id, "-e", "--accept-source-agreements", "--accept-package-agreements"],
            self.root,
        )

    def launch(self, api_port: int, web_port: int, open_browser: bool) -> tuple[bool, str]:
        if not self.ready_to_launch():
            return False, "Complete the required checks before launching."
        environment = os.environ.copy()
        environment["AURA_INDEX_ROOT"] = str(self.index_root)
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        try:
            subprocess.Popen(
                [str(self.python), "-m", "aura_bio.api.server", "--port", str(api_port)],
                cwd=self.root,
                env=environment,
                creationflags=creationflags,
            )
            subprocess.Popen(
                [self.npm or "npm", "run", "dev", "--", "--port", str(web_port)],
                cwd=self.root / "frontend",
                env=environment,
                creationflags=creationflags,
            )
        except OSError as exc:
            return False, f"Could not start AURA-Bio: {exc}"
        if open_browser:
            threading.Thread(target=open_when_ready, args=(web_port,), daemon=True).start()
        return True, f"Started API on http://127.0.0.1:{api_port} and web UI on http://127.0.0.1:{web_port}."


def run_command(command: list[str], cwd: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    except OSError as exc:
        return False, str(exc)
    output = (result.stdout + "\n" + result.stderr).strip()
    if len(output) > 3500:
        output = "…" + output[-3500:]
    return result.returncode == 0, output or "Command completed."


def open_when_ready(web_port: int) -> None:
    time.sleep(4)
    webbrowser.open(f"http://127.0.0.1:{web_port}")


def render_headless(environment: AuraEnvironment) -> int:
    print(f"AURA-Bio checkout: {environment.root}")
    for check in environment.checks():
        print(f"[{check.state.upper():8}] {check.name}: {check.detail}")
    return 0 if environment.ready_to_launch() else 1


def launch_gui(environment: AuraEnvironment, api_port: int, web_port: int, open_browser: bool) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class Launcher(ttk.Frame):
        def __init__(self, master: tk.Tk) -> None:
            super().__init__(master, padding=20)
            self.master = master
            self.status = tk.StringVar(value="Checking local setup…")
            self.index_value = tk.StringVar(value=str(environment.index_root))
            self.grid(sticky="nsew")
            master.title("AURA-Bio Launcher")
            master.minsize(820, 570)
            master.columnconfigure(0, weight=1)
            master.rowconfigure(0, weight=1)
            self.columnconfigure(0, weight=1)
            self.rowconfigure(2, weight=1)

            ttk.Label(self, text="AURA-Bio", font=("Segoe UI", 22, "bold")).grid(row=0, column=0, sticky="w")
            ttk.Label(self, text="Local readiness, setup, and launch — using this checkout’s real paths.").grid(row=1, column=0, sticky="w", pady=(0, 14))
            self.table = ttk.Treeview(self, columns=("state", "detail"), show="headings", height=7)
            self.table.heading("state", text="Status")
            self.table.heading("detail", text="Details")
            self.table.column("state", width=100, anchor="center")
            self.table.column("detail", width=650)
            self.table.grid(row=2, column=0, sticky="nsew")

            index_frame = ttk.LabelFrame(self, text="Retrieval index (optional)", padding=10)
            index_frame.grid(row=3, column=0, sticky="ew", pady=(14, 0))
            index_frame.columnconfigure(0, weight=1)
            ttk.Entry(index_frame, textvariable=self.index_value).grid(row=0, column=0, sticky="ew", padx=(0, 8))
            ttk.Button(index_frame, text="Choose…", command=self.choose_index).grid(row=0, column=1)

            buttons = ttk.Frame(self)
            buttons.grid(row=4, column=0, sticky="ew", pady=14)
            for column in range(5):
                buttons.columnconfigure(column, weight=1)
            ttk.Button(buttons, text="Refresh", command=self.refresh).grid(row=0, column=0, padx=3, sticky="ew")
            ttk.Button(buttons, text="Install Python packages", command=lambda: self.background("Python dependency install", environment.install_python)).grid(row=0, column=1, padx=3, sticky="ew")
            ttk.Button(buttons, text="Install frontend packages", command=lambda: self.background("Frontend dependency install", environment.install_frontend)).grid(row=0, column=2, padx=3, sticky="ew")
            ttk.Button(buttons, text="Install Node", command=lambda: self.background("Node installation", lambda: environment.install_tool("OpenJS.NodeJS.LTS"))).grid(row=0, column=3, padx=3, sticky="ew")
            self.start_button = ttk.Button(buttons, text="Launch AURA-Bio", command=self.start)
            self.start_button.grid(row=0, column=4, padx=3, sticky="ew")
            ttk.Label(self, textvariable=self.status, wraplength=770).grid(row=5, column=0, sticky="w")
            self.refresh()

        def choose_index(self) -> None:
            selected = filedialog.askdirectory(initialdir=self.index_value.get() or str(environment.root))
            if selected:
                self.index_value.set(selected)
                self.refresh()

        def refresh(self) -> None:
            environment.index_root = Path(self.index_value.get()).expanduser()
            for item in self.table.get_children():
                self.table.delete(item)
            for check in environment.checks():
                self.table.insert("", "end", values=(check.state.upper(), f"{check.name} — {check.detail}"))
            ready = environment.ready_to_launch()
            self.start_button.configure(state="normal" if ready else "disabled")
            self.status.set("Ready to launch." if ready else "Complete the required items; optional services can be added later.")

        def background(self, label: str, action: Callable[[], tuple[bool, str]]) -> None:
            self.status.set(f"{label} is running…")
            def worker() -> None:
                ok, output = action()
                self.after(0, lambda: self.finished(label, ok, output))
            threading.Thread(target=worker, daemon=True).start()

        def finished(self, label: str, ok: bool, output: str) -> None:
            self.status.set(f"{label}: {'complete' if ok else 'failed'}. Refreshing checks.")
            messagebox.showinfo(label if ok else f"{label} failed", output)
            self.refresh()

        def start(self) -> None:
            environment.index_root = Path(self.index_value.get()).expanduser()
            ok, message = environment.launch(api_port, web_port, open_browser)
            self.status.set(message)
            if not ok:
                messagebox.showerror("AURA-Bio", message)

    root = tk.Tk()
    Launcher(root)
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guided setup and local launch for AURA-Bio.")
    parser.add_argument("--headless-check", action="store_true", help="print readiness checks without opening the GUI")
    parser.add_argument("--index-root", type=Path, help="override the retrieval-index directory")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=5173)
    parser.add_argument("--no-browser", action="store_true", help="do not open the frontend after launch")
    args = parser.parse_args(argv)
    try:
        root = project_root(Path(__file__).parent)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2
    environment = AuraEnvironment(root, args.index_root)
    if args.headless_check:
        return render_headless(environment)
    return launch_gui(environment, args.api_port, args.web_port, not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())

"""Build the isolated spellfix POC against the pinned SQLite extension headers."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--target", choices=("native", "linux-arm64", "windows-x64"), default="native")
target_name = parser.parse_args().target
root = Path(__file__).resolve().parents[1]
header = root / "vendor/sqlite/sqlite3.h"
if not header.is_file() or "#define SQLITE_VERSION_NUMBER 3045001" not in header.read_text(errors="replace"):
    raise SystemExit("Missing pinned SQLite 3.45.1 sqlite3.h")
out = root / ".poc-build"
out.mkdir(exist_ok=True)
targets = {
    "linux-arm64": ("aarch64-linux-gnu-gcc", "spellfix-aarch64.so", ["-fPIC", "-shared"]),
    "windows-x64": ("x86_64-w64-mingw32-gcc", "spellfix-win64.dll", ["-shared"]),
}
if target_name == "native":
    if sys.platform == "linux":
        compiler, filename, flags = "cc", "spellfix.so", ["-fPIC", "-shared"]
    elif sys.platform == "darwin":
        compiler, filename, flags = "cc", "spellfix.dylib", ["-fPIC", "-dynamiclib", "-mmacosx-version-min=11.0"]
    elif sys.platform == "win32":
        compiler, filename, flags = os.environ.get("PHONETICSEARCH_CC", r"C:\msys64\mingw64\bin\gcc.exe"), "spellfix.dll", ["-shared"]
    else:
        raise SystemExit(f"Unsupported native build platform: {sys.platform}")
else:
    if sys.platform != "linux":
        raise SystemExit("Cross builds require a Linux host")
    compiler, filename, flags = targets[target_name]
target = out / filename
cmd = [compiler, "-O2", *flags, "-I", str(root / "vendor/sqlite"),
       str(root / "vendor/sqlite/spellfix.c"), "-o", str(target)]
print(" ".join(cmd), flush=True)
subprocess.run(cmd, check=True)
print(target)

"""Swift-утилиты из swift/ собираются в bin/ сами, если исходник новее бинарника."""
import subprocess
import sys

from copilot.paths import ROOT


def build(name):
    """swift/<name>.swift + <name>.plist → bin/<name>. Возвращает путь к бинарнику."""
    binary, source, plist = ROOT / "bin" / name, ROOT / "swift" / f"{name}.swift", ROOT / "swift" / f"{name}.plist"
    if not binary.exists() or binary.stat().st_mtime < max(source.stat().st_mtime, plist.stat().st_mtime):
        print(f"собираю bin/{name}…", file=sys.stderr)
        binary.parent.mkdir(exist_ok=True)
        subprocess.run(["swiftc", "-O", "-swift-version", "5", str(source), "-o", str(binary),
                        "-Xlinker", "-sectcreate", "-Xlinker", "__TEXT", "-Xlinker", "__info_plist",
                        "-Xlinker", str(plist)], check=True)
    return binary

"""P8 subprocess 起 shell + 出网：进程 + socket，模拟「沙箱里跑 curl」。"""
import subprocess
import sys

r = subprocess.run(
    [sys.executable, "-c", "import urllib.request; urllib.request.urlopen('https://example.com', timeout=15)"],
    capture_output=True,
)
print("exitcode =", r.returncode)
raise SystemExit(0 if r.returncode == 0 else 1)

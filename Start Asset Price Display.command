#!/bin/zsh
# Double-click launcher. Opens the page in the default browser.
# Moli stays external (~/.local/bin/moli); this only starts the Python server.
cd "$(dirname "$0")" || exit 1
export PATH="${HOME}/.local/bin:${PATH}"
PORT="${APD_PORT:-8000}"
exec python3 - "$PORT" <<'PY'
import errno, socket, subprocess, sys, time, webbrowser

want = int(sys.argv[1])
port = want
for p in range(want, min(want + 8, 65536)):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", p))
        s.close()
        port = p
        break
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            raise
else:
    sys.exit("no free port near %s" % want)

proc = subprocess.Popen([sys.executable, "server.py", str(port)])
time.sleep(0.9)
webbrowser.open("http://127.0.0.1:%s/" % port)
try:
    raise SystemExit(proc.wait())
except KeyboardInterrupt:
    proc.terminate()
    raise SystemExit(130)
PY

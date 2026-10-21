"""Exercise network, timeout, and process limits using reviewed probes only."""

import json
from pathlib import Path

from issue2proof.execution import SandboxExecutor

executor = SandboxExecutor()
probes = {
    "network": "import json,socket,pathlib; print(json.dumps({'interfaces':[p.name for p in pathlib.Path('/sys/class/net').iterdir()]})); s=socket.socket();s.settimeout(2); result=s.connect_ex(('1.1.1.1',443));print(json.dumps({'connect_result':result}));raise SystemExit(0 if result!=0 else 1)",
    "server_timeout": "import time; time.sleep(15)",
}
reports = {}
try:
    for name, code in probes.items():
        reports[name] = executor.run(
            code, timeout=2 if name == "server_timeout" else 10
        )
finally:
    executor.close()
reports["passed"] = (
    reports["network"]["network_disabled"]
    and reports["network"]["exit_code"] == 0
    and reports["server_timeout"]["exit_code"] != 0
    and all(
        r["disposable"] and r["result_image"] is None
        for r in [reports["network"], reports["server_timeout"]]
    )
)
Path("artifacts/sandbox-controls.json").write_text(json.dumps(reports, indent=2) + "\n")
print(json.dumps(reports, indent=2))

import os
from pathlib import Path
import socket


if os.getuid() == 0:
    raise SystemExit("Container is running as root.")
if {name for _, name in socket.if_nameindex()} != {"lo"}:
    raise SystemExit("Container has an interface other than loopback.")
if "VULTR_INFERENCE_API_KEY" in os.environ or Path("/var/run/docker.sock").exists():
    raise SystemExit("Container can access a control-plane credential or socket.")
if not os.statvfs("/").f_flag & os.ST_RDONLY:
    raise SystemExit("Container root filesystem is writable.")

print("Verified non-root execution, loopback-only networking, and read-only root.", flush=True)
print("Vultr key and Docker socket are absent. Starting the timeout test.", flush=True)
while True:
    pass

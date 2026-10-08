import os
import tarfile
import paramiko
import sys

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
archive_path = os.path.join(_BASE_DIR, "blackfox.tar.gz")

print("[*] Creating blackfox.tar.gz archive...")

EXCLUDE_DIRS = {".git", ".venv", "__pycache__", "logs", "scratch", ".idea", ".vscode", "node_modules"}
EXCLUDE_EXTS = {".db", ".tar.gz", ".pyc", ".log"}

def should_exclude(path):
    rel = os.path.relpath(path, _BASE_DIR)
    parts = rel.split(os.sep)
    for part in parts:
        if part in EXCLUDE_DIRS:
            return True
    if any(rel.endswith(ext) for ext in EXCLUDE_EXTS):
        # Allow keeping assets
        if "assets" in rel:
            return False
        return True
    return False

with tarfile.open(archive_path, "w:gz") as tar:
    for root, dirs, files in os.walk(_BASE_DIR):
        # Filter dirs in-place
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            full_path = os.path.join(root, f)
            if should_exclude(full_path):
                continue
            arcname = os.path.relpath(full_path, _BASE_DIR)
            tar.add(full_path, arcname=arcname)

print(f"[+] Archive created successfully: {os.path.getsize(archive_path)} bytes")

HOST = os.environ.get("VPS_HOST", "31.76.101.210")
USER = os.environ.get("VPS_USER", "root")
PORT = int(os.environ.get("VPS_PORT", "22"))
PASS = os.environ.get("VPS_PASS", "ooM*@#9381JEneq")

print(f"[*] Connecting to {USER}@{HOST}:{PORT} via SSH...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=15)
    print("[+] SSH connection established successfully!")
except Exception as e:
    print(f"[-] Connection failed: {e}")
    sys.exit(1)

print("[*] Uploading project archive (blackfox.tar.gz)...")
sftp = ssh.open_sftp()
sftp.put(archive_path, "/root/blackfox.tar.gz")
sftp.close()
print("[+] Archive uploaded successfully!")

commands = [
    "mkdir -p /root/BlackFoxBot",
    "tar -xzf /root/blackfox.tar.gz -C /root/BlackFoxBot/",
    "systemctl stop blackfox-worker 2>/dev/null || true",
    "systemctl disable blackfox-worker 2>/dev/null || true",
    "systemctl restart blackfox-admin",
    "systemctl is-active blackfox-admin"
]

full_cmd = " && ".join(commands)
print("[*] Executing deployment and service restarts on remote server...")
stdin, stdout, stderr = ssh.exec_command(full_cmd, get_pty=True)

for line in iter(stdout.readline, ""):
    try:
        sys.stdout.buffer.write(line.encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()
    except Exception:
        pass

ssh.close()
print("\n[+] Remote deployment completed successfully!")

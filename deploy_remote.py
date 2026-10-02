import os
import sys
import paramiko

HOST = os.environ.get("VPS_HOST", "31.76.101.210")
USER = os.environ.get("VPS_USER", "root")
PORT = int(os.environ.get("VPS_PORT", "22"))
PASS = os.environ.get("VPS_PASS", "")

def main():
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
    local_archive = os.path.abspath("blackfox.tar.gz")
    remote_archive = "/root/blackfox.tar.gz"
    
    sftp.put(local_archive, remote_archive)
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
    print("\n[+] Remote deployment completed!")

if __name__ == "__main__":
    main()

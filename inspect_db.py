import sys
import paramiko

HOST = "31.76.101.210"
USER = "root"
PORT = 22
PASS = "ooM*@#9381JEneq"

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=15)

    cmd = """
cd /root/BlackFoxBot && .venv/bin/python -c '
import sqlite3
conn = sqlite3.connect("data/fleet.db")
conn.row_factory = sqlite3.Row
print("--- TOKENS ---")
for t in conn.execute("SELECT * FROM tokens").fetchall():
    print(dict(t))
print("--- USERS ---")
for u in conn.execute("SELECT * FROM users").fetchall():
    print(dict(u))
print("--- SETTINGS ---")
for s in conn.execute("SELECT * FROM settings").fetchall():
    print(dict(s))
'
"""
    stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
    for line in iter(stdout.readline, ""):
        sys.stdout.write(line)
    ssh.close()

if __name__ == "__main__":
    main()

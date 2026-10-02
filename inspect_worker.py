import paramiko

HOST = "31.76.101.210"
USER = "root"
PORT = 22
PASS = "ooM*@#9381JEneq"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=15)

cmd = "ps aux | grep worker; cat /etc/systemd/system/blackfox-worker.service; cat /root/BlackFoxBot/.env"
stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
for line in iter(stdout.readline, ""):
    print(line, end="")
ssh.close()

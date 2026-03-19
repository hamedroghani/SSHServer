import os
import errno
import json
import socket
import threading
import traceback
import subprocess
import time
from pathlib import Path

import paramiko
from paramiko import RSAKey, ServerInterface, AUTH_SUCCESSFUL, OPEN_SUCCEEDED
from paramiko import SFTPAttributes, SFTPHandle, SFTPServerInterface
from paramiko.sftp_server import SFTPServer


CONFIG_FILE = "server_config.json"


def load_config(path: str) -> dict:
    defaults = {
        "host": "0.0.0.0",
        "port": 2222,
        "host_key_file": "host_rsa.key",
        "sftp_root": "C:/",
    }

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"No existe {path}. Crea ese archivo con tu configuración privada."
        )

    with config_path.open("r", encoding="utf-8") as f:
        loaded = json.load(f)

    config = {**defaults, **loaded}

    required_keys = ("username", "password")
    missing = [k for k in required_keys if not config.get(k)]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(
            f"Faltan claves obligatorias en {path}: {missing_text}"
        )

    return config


CONFIG = load_config(CONFIG_FILE)
HOST = CONFIG["host"]
PORT = int(CONFIG["port"])
USERNAME = CONFIG["username"]
PASSWORD = CONFIG["password"]
HOST_KEY_FILE = CONFIG["host_key_file"]
SFTP_ROOT = Path(CONFIG["sftp_root"]).resolve()


def ensure_host_key(path: str) -> RSAKey:
    p = Path(path)
    if not p.exists():
        key = RSAKey.generate(2048)
        key.write_private_key_file(str(p))
        return key
    return RSAKey(filename=str(p))


HOST_KEY = ensure_host_key(HOST_KEY_FILE)


class SSHServer(ServerInterface):
    def __init__(self):
        self.event = threading.Event()
        self.exec_command = None

    def check_auth_password(self, username, password):
        if username == USERNAME and password == PASSWORD:
            return AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_shell_request(self, channel):
        self.event.set()
        return True

    def check_channel_pty_request(
        self, channel, term, width, height, pixelwidth, pixelheight, modes
    ):
        return True

    def check_channel_exec_request(self, channel, command):
        if isinstance(command, bytes):
            command = command.decode("utf-8", errors="replace")
        self.exec_command = command
        self.event.set()
        return True


class WindowsSFTPServer(SFTPServerInterface):
    def __init__(self, server, *largs, **kwargs):
        root = kwargs.pop("root", SFTP_ROOT)
        # Paramiko 4.x forwards extra args to object.__init__ in SFTPServerInterface,
        # so this subclass must avoid passing custom kwargs upstream.
        super().__init__(server)
        self.root = Path(root).resolve()

    def _to_local_path(self, path: str) -> Path:
        if not path:
            return self.root

        raw = path.replace("\\", "/")
        if raw.startswith("/"):
            raw = raw[1:]

        # Permite rutas tipo /C:/Users y también rutas relativas bajo SFTP_ROOT.
        if len(raw) >= 2 and raw[1] == ":":
            if len(raw) == 2:
                raw = raw + "/"
            target = Path(raw)
        else:
            target = self.root / raw

        return target.resolve(strict=False)

    def _to_sftp_attr(self, local_path: Path) -> SFTPAttributes:
        attrs = SFTPAttributes.from_stat(local_path.stat())
        attrs.filename = local_path.name
        return attrs

    def canonicalize(self, path):
        local = self._to_local_path(path)
        local_str = str(local).replace("\\", "/")
        if len(local_str) >= 2 and local_str[1] == ":":
            return f"/{local_str}"
        return local_str

    def list_folder(self, path):
        try:
            local = self._to_local_path(path)
            entries = []
            for name in os.listdir(local):
                child = local / name
                attrs = self._to_sftp_attr(child)
                attrs.filename = name
                entries.append(attrs)
            return entries
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    def stat(self, path):
        try:
            return SFTPAttributes.from_stat(self._to_local_path(path).stat())
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    def lstat(self, path):
        try:
            return SFTPAttributes.from_stat(self._to_local_path(path).lstat())
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    def open(self, path, flags, attr):
        local = self._to_local_path(path)
        try:
            binary_flag = getattr(os, "O_BINARY", 0)
            flags |= binary_flag

            mode = getattr(attr, "st_mode", None)
            if mode is None:
                mode = 0o666

            fd = os.open(str(local), flags, mode)

            if flags & os.O_WRONLY:
                file_mode = "ab" if (flags & os.O_APPEND) else "wb"
            elif flags & os.O_RDWR:
                file_mode = "a+b" if (flags & os.O_APPEND) else "r+b"
            else:
                file_mode = "rb"

            file_obj = os.fdopen(fd, file_mode)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

        handle = SFTPHandle(flags)
        handle.filename = str(local)
        handle.readfile = file_obj
        handle.writefile = file_obj
        return handle

    def remove(self, path):
        try:
            os.remove(self._to_local_path(path))
            return paramiko.SFTP_OK
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    def rename(self, oldpath, newpath):
        try:
            os.replace(self._to_local_path(oldpath), self._to_local_path(newpath))
            return paramiko.SFTP_OK
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    def mkdir(self, path, attr):
        local = self._to_local_path(path)
        try:
            if local.exists():
                return SFTPServer.convert_errno(errno.EEXIST)

            mode = getattr(attr, "st_mode", None)
            if mode is None:
                mode = 0o777

            os.mkdir(local, mode=mode)
            return paramiko.SFTP_OK
        except TypeError as e:
            print(f"[-] SFTP mkdir TypeError en {local}: {e}")
            return paramiko.SFTP_FAILURE
        except OSError as e:
            print(f"[-] SFTP mkdir OSError en {local}: {e}")
            return SFTPServer.convert_errno(e.errno)

    def rmdir(self, path):
        try:
            os.rmdir(self._to_local_path(path))
            return paramiko.SFTP_OK
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    def chattr(self, path, attr):
        local = self._to_local_path(path)
        if attr is None:
            return paramiko.SFTP_OK

        try:
            if attr.st_mode is not None:
                os.chmod(local, attr.st_mode)
            if attr.st_uid is not None and attr.st_gid is not None:
                os.chown(local, attr.st_uid, attr.st_gid)
            if attr.st_atime is not None and attr.st_mtime is not None:
                os.utime(local, (attr.st_atime, attr.st_mtime))
            return paramiko.SFTP_OK
        except (AttributeError, NotImplementedError):
            return paramiko.SFTP_OK
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)


def run_powershell(command: str):
    proc = subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-Command",
            command,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    out, err = proc.communicate()
    return proc.returncode, out, err


def interactive_shell(chan):
    banner = (
        "\r\n"
        "Servidor SSH Python en Windows 11\r\n"
        "Escribe comandos de PowerShell.\r\n"
        "Comandos especiales: exit, quit\r\n\r\n"
    )
    chan.send(banner)

    buffer = ""
    prompt = "PS> "
    chan.send(prompt)

    while True:
        try:
            data = chan.recv(1024)
            if not data:
                break

            text = data.decode("utf-8", errors="replace")

            for ch in text:
                if ch in ("\r", "\n"):
                    cmd = buffer.strip()
                    chan.send("\r\n")
                    buffer = ""

                    if not cmd:
                        chan.send(prompt)
                        continue

                    if cmd.lower() in ("exit", "quit"):
                        chan.send("Bye\r\n")
                        return

                    code, out, err = run_powershell(cmd)

                    if out:
                        chan.send(out.replace("\n", "\r\n"))
                    if err:
                        chan.send(err.replace("\n", "\r\n"))

                    chan.send(f"\r\n[exitcode={code}]\r\n")
                    chan.send(prompt)

                elif ch == "\x03":
                    chan.send("^C\r\n")
                    buffer = ""
                    chan.send(prompt)

                elif ch in ("\x08", "\x7f"):  # backspace
                    if buffer:
                        buffer = buffer[:-1]
                        chan.send("\b \b")

                else:
                    buffer += ch
                    chan.send(ch)

        except Exception:
            break


def handle_connection(client, addr):
    transport = None
    chan = None
    try:
        print(f"[+] Conexión desde {addr}")

        transport = paramiko.Transport(client)
        transport.add_server_key(HOST_KEY)
        transport.set_subsystem_handler("sftp", SFTPServer, WindowsSFTPServer, root=SFTP_ROOT)

        server = SSHServer()
        transport.start_server(server=server)

        chan = transport.accept(20)
        if chan is None:
            print("[-] No se abrió canal")
            return

        if not server.event.wait(10):
            # WinSCP usa subsistema SFTP y no siempre dispara shell/exec.
            print("[>] Sesión sin shell/exec (posible SFTP)")
            while transport.is_active():
                time.sleep(0.2)
            return

        if server.exec_command:
            print(f"[>] EXEC: {server.exec_command}")
            code, out, err = run_powershell(server.exec_command)

            if out:
                chan.send(out.replace("\n", "\r\n"))
            if err:
                chan.send_stderr(err.replace("\n", "\r\n"))

            try:
                chan.send_exit_status(code)
            except Exception:
                pass
        else:
            print("[>] Shell interactiva")
            interactive_shell(chan)

    except Exception as e:
        print(f"[-] Error con {addr}: {e}")
        traceback.print_exc()
    finally:
        try:
            if chan is not None:
                chan.close()
        except Exception:
            pass
        try:
            if transport is not None:
                transport.close()
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass
        print(f"[*] Desconectado {addr}")


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, PORT))
    sock.listen(100)

    print(f"[+] SSH escuchando en {HOST}:{PORT}")
    print(f"[+] Usuario: {USERNAME}")
    print("[+] Ctrl+C para detener")

    while True:
        client, addr = sock.accept()
        t = threading.Thread(target=handle_connection, args=(client, addr), daemon=True)
        t.start()


if __name__ == "__main__":
    main()
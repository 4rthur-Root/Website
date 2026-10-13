"""
admin_logic.py
--------------
Opérations SSH/Paramiko pour l'administration.
Sécurité : toutes les valeurs utilisateur passent par shlex.quote()
           avant d'être insérées dans des commandes shell.
"""

import os
import re
import json
import shlex
import datetime
import paramiko
from contextlib import contextmanager
from pathlib import Path

SSH_HOST     = os.getenv("SSH_HOST",     "10.0.1.10")
SSH_USER     = os.getenv("SSH_USER",     "vagrant")
SSH_PASSWORD = os.getenv("SSH_PASSWORD", "vagrant")
SSH_PORT     = int(os.getenv("SSH_PORT", "22"))
SSH_TIMEOUT  = 8

# Journal d'audit local (sur la machine hôte Flask)
AUDIT_LOG = Path(__file__).parent / "audit.log"

# Groupes valides -- liste fermée, jamais depuis l'input utilisateur
VALID_GROUPS = {"direction", "comptabilite", "rh", "technique"}

# Comptes protégés -- impossibles à supprimer/modifier via l'interface
PROTECTED_ACCOUNTS = {"root", "vboxuser", "admin", "samba", "nobody", "daemon"}


# Sudo sécurisé
def _sudo(cmd: str) -> str:
    """
    Préfixe une commande avec sudo -S en injectant le mot de passe
    via shlex.quote() -- protège contre les caractères spéciaux dans le mdp.
    """
    pwd_safe = shlex.quote(SSH_PASSWORD)
    return f"echo {pwd_safe} | sudo -S {cmd}"


# Connexion SSH
@contextmanager
def _ssh():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            SSH_HOST, port=SSH_PORT,
            username=SSH_USER, password=SSH_PASSWORD,
            timeout=SSH_TIMEOUT, allow_agent=False, look_for_keys=False,
        )
        yield client
    finally:
        client.close()


def _run(client, cmd: str) -> str:
    _, stdout, stderr = client.exec_command(cmd, timeout=15)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return out if out else err


# Journal d'audit 
def audit(actor: str, action: str, target: str, detail: str = "") -> None:
    """
    Enregistre une action sensible dans audit.log.
    Format : timestamp | actor | action | target | detail
    """
    ts    = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{ts} | {actor} | {action:<15} | {target:<20} | {detail}\n"
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass  # Ne jamais crasher Flask à cause du log


def get_audit_log(n: int = 50) -> list:
    """Retourne les n dernières entrées du journal d'audit."""
    try:
        if not AUDIT_LOG.exists():
            return []
        lines = AUDIT_LOG.read_text(encoding="utf-8").splitlines()
        return lines[-n:][::-1]  # Plus récent en premier
    except Exception:
        return []


# Dashboard principal 
def get_dashboard_data() -> dict:
    try:
        with _ssh() as ssh:
            smbd  = _run(ssh, "systemctl is-active smbd")
            nmbd  = _run(ssh, "systemctl is-active nmbd")
            sshd  = _run(ssh, "systemctl is-active ssh")
            uptime    = _run(ssh, "uptime -p")
            load_raw  = _run(ssh, "cat /proc/loadavg")
            load_1m   = load_raw.split()[0] if load_raw else "?"
            load_5m   = load_raw.split()[1] if load_raw else "?"
            cpu_count = _run(ssh, "nproc")
            mem_raw   = _run(ssh, "free -m")
            mem       = _parse_memory(mem_raw)
            disk_raw  = _run(ssh, "df -h /srv/samba")
            disk      = _parse_disk(disk_raw)

            shares_disk = {}
            for share in ["direction", "comptabilite", "rh", "technique", "commun"]:
                count = _run(ssh, f"find /srv/samba/{share} -maxdepth 1 -type f 2>/dev/null | wc -l")
                size  = _run(ssh, f"du -sh /srv/samba/{share} 2>/dev/null | cut -f1")
                shares_disk[share] = {"count": count.strip() or "0", "size": size.strip() or "?"}

            smb_count    = _run(ssh, f"{_sudo('smbstatus -b 2>/dev/null')} | grep -c '[0-9]' || echo '0'")
            smb_sessions = _run(ssh, f"{_sudo('smbstatus -b 2>/dev/null')} | tail -20")

            f2b_raw  = _run(ssh, f"{_sudo('fail2ban-client status samba 2>/dev/null || echo UNAVAILABLE')}")
            fail2ban = _parse_fail2ban_full(f2b_raw, ssh)

            f2b_log    = _run(ssh, f"{_sudo('grep -E Ban.Unban.Found /var/log/fail2ban.log 2>/dev/null | tail -30')}")
            samba_auth = _run(ssh, f"{_sudo('grep -rh Authentication /var/log/samba/ 2>/dev/null | tail -40')}")
            samba_raw  = _run(ssh, f"{_sudo('tail -30 /var/log/samba/log.smbd 2>/dev/null')}")
            user_stats = _parse_user_stats(samba_auth)
            samba_users   = _get_samba_users(ssh)
            samba_version = _run(ssh, "samba --version 2>/dev/null | head -1")

            return {
                "ok": True,
                "smbd": smbd, "nmbd": nmbd, "sshd": sshd,
                "uptime": uptime,
                "load_1m": load_1m, "load_5m": load_5m, "cpu_count": cpu_count,
                "memory": mem, "disk": disk, "shares_disk": shares_disk,
                "smb_count": smb_count.strip(), "smb_sessions": smb_sessions,
                "fail2ban": fail2ban, "fail2ban_log": f2b_log,
                "samba_auth": samba_auth, "samba_raw": samba_raw,
                "user_stats": user_stats, "samba_users": samba_users,
                "samba_version": samba_version,
                "audit_log": get_audit_log(30),
            }

    except paramiko.AuthenticationException:
        return {"ok": False, "error": "Authentification SSH refusée — vérifiez SSH_USER/SSH_PASSWORD dans .env"}
    except (paramiko.NoValidConnectionsError, OSError):
        return {"ok": False, "error": f"Impossible de joindre {SSH_HOST}:{SSH_PORT} — VM éteinte ?"}
    except TimeoutError:
        return {"ok": False, "error": f"Timeout SSH ({SSH_TIMEOUT}s)"}
    except Exception as e:
        return {"ok": False, "error": f"Erreur SSH : {str(e)}"}


# Parseurs
def _parse_memory(raw: str) -> dict:
    result = {"total": 0, "used": 0, "free": 0, "percent": 0,
              "total_str": "?", "used_str": "?", "raw": raw}
    for line in raw.splitlines():
        if line.startswith("Mem:"):
            parts = line.split()
            try:
                total = int(parts[1]); used = int(parts[2])
                result.update({
                    "total": total, "used": used, "free": total - used,
                    "percent": round(used / total * 100) if total else 0,
                    "total_str": f"{total} Mo", "used_str": f"{used} Mo",
                })
            except (ValueError, IndexError):
                pass
    return result


def _parse_disk(raw: str) -> dict:
    result = {"size": "?", "used": "?", "avail": "?", "percent": 0, "raw": raw}
    for line in raw.splitlines():
        if line.startswith("Filesystem"):
            continue
        parts = line.split()
        if len(parts) >= 5:
            try:
                result.update({
                    "size": parts[1], "used": parts[2],
                    "avail": parts[3], "percent": int(parts[4].replace("%", "")),
                })
            except (ValueError, IndexError):
                pass
    return result


def _parse_fail2ban_full(raw: str, ssh) -> dict:
    if "UNAVAILABLE" in raw or not raw.strip():
        return {"available": False, "total_failed": "0", "total_banned": "0",
                "current_banned": [], "banned_details": [], "raw": raw}

    result = {"available": True, "raw": raw, "total_failed": "0",
              "total_banned": "0", "current_banned": [], "banned_details": []}

    for line in raw.splitlines():
        line = line.strip()
        if "Total failed:"  in line: result["total_failed"] = line.split(":")[-1].strip()
        elif "Total banned:" in line: result["total_banned"] = line.split(":")[-1].strip()
        elif "Banned IP list:" in line:
            ips = line.split(":", 1)[-1].strip()
            result["current_banned"] = [ip.strip() for ip in ips.split() if ip.strip()]

    for ip in result["current_banned"]:
        ip_safe  = shlex.quote(ip)
        count    = _run(ssh, f"{_sudo(f'grep -c {ip_safe} /var/log/fail2ban.log 2>/dev/null || echo ?')}")
        ban_time = _run(ssh, f"{_sudo(f'grep Ban.{ip_safe} /var/log/fail2ban.log 2>/dev/null | tail -1 | cut -d\" \" -f1,2')}")
        result["banned_details"].append({
            "ip": ip, "attempts": count.strip(), "ban_time": ban_time.strip() or "?"
        })
    return result


def _parse_user_stats(auth_log: str) -> list:
    stats = {}
    for line in auth_log.splitlines():
        user_match = re.search(r'Account-Name:\s*(\S+)', line)
        if not user_match:
            user_match = re.search(r'user\s+(\w+)\s+', line, re.IGNORECASE)
        if not user_match:
            continue
        user = user_match.group(1).lower()
        if user in ("", "nobody", "guest"):
            continue
        if user not in stats:
            stats[user] = {"user": user, "ok": 0, "fail": 0}
        if "NT_STATUS_OK" in line or "succeeded" in line.lower():
            stats[user]["ok"] += 1
        elif "NT_STATUS" in line or "failed" in line.lower():
            stats[user]["fail"] += 1
    return sorted(stats.values(), key=lambda x: x["ok"] + x["fail"], reverse=True)


def _get_samba_users(ssh) -> list:
    users = []
    seen  = set()
    for group in VALID_GROUPS:
        raw = _run(ssh, f"getent group {shlex.quote(group)} 2>/dev/null")
        if ":" in raw:
            parts = raw.split(":")
            if len(parts) >= 4 and parts[3].strip():
                for u in parts[3].strip().split(","):
                    u = u.strip()
                    if u and u not in seen:
                        seen.add(u)
                        smb_check = _run(ssh, f"{_sudo(f'pdbedit -L 2>/dev/null')} | grep -c '^{shlex.quote(u)}:'")
                        users.append({
                            "username": u,
                            "group":    group,
                            "enabled":  smb_check.strip() == "1",
                        })
    return sorted(users, key=lambda x: (x["group"], x["username"]))


# Fail2ban : débannissement 
def unban_ip(ip: str, actor: str = "admin") -> dict:
    if not re.match(r'^[\d\.]+$', ip):
        return {"ok": False, "error": "Format d'IP invalide"}
    try:
        with _ssh() as ssh:
            ip_safe = shlex.quote(ip)
            out = _run(ssh, _sudo(f"fail2ban-client set samba unbanip {ip_safe} 2>&1"))
            if "1" in out or "OK" in out.upper():
                audit(actor, "UNBAN_IP", ip)
                return {"ok": True}
            return {"ok": False, "error": f"Réponse inattendue : {out}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# Gestion utilisateurs 
def _validate_username(username: str) -> str | None:
    """Retourne None si valide, sinon le message d'erreur."""
    if not re.match(r'^[a-z][a-z0-9_]{2,19}$', username):
        return "Nom invalide (3-20 car., minuscules, chiffres, underscore)"
    return None


def add_user(username: str, group: str, password: str,
             actor: str = "admin") -> dict:
    err = _validate_username(username)
    if err:
        return {"ok": False, "error": err}
    if group not in VALID_GROUPS:
        return {"ok": False, "error": f"Groupe invalide. Acceptés : {', '.join(VALID_GROUPS)}"}
    if len(password) < 8:
        return {"ok": False, "error": "Mot de passe trop court (min 8 caractères)"}

    # Échappement de TOUTES les valeurs externes
    user_safe  = shlex.quote(username)
    group_safe = shlex.quote(group)
    pwd_safe   = shlex.quote(password)

    steps = []
    try:
        with _ssh() as ssh:
            exists = _run(ssh, f"id {user_safe} 2>/dev/null")
            if exists and "uid=" in exists:
                return {"ok": False, "error": f"L'utilisateur '{username}' existe déjà"}

            # 1. Créer l'utilisateur Linux
            out = _run(ssh, _sudo(f"useradd -m -G {group_safe} -s /bin/bash {user_safe} 2>&1"))
            steps.append({"cmd": f"useradd -m -G {group} {username}", "out": out or "OK"})

            # 2. Définir le mot de passe Linux
            out = _run(ssh, f"echo {shlex.quote(f'{username}:{password}')} | {_sudo('chpasswd 2>&1')}")
            steps.append({"cmd": "chpasswd", "out": out or "OK"})

            # 3. Créer le compte Samba
            out = _run(ssh, f"(echo {pwd_safe}; echo {pwd_safe}) | {_sudo(f'smbpasswd -a {user_safe} 2>&1')}")
            steps.append({"cmd": f"smbpasswd -a {username}", "out": out or "OK"})

            # 4. Activer le compte Samba
            out = _run(ssh, _sudo(f"smbpasswd -e {user_safe} 2>&1"))
            steps.append({"cmd": f"smbpasswd -e {username}", "out": out or "OK"})

            audit(actor, "ADD_USER", username, f"groupe={group}")
            return {"ok": True, "steps": steps, "username": username, "group": group}

    except Exception as e:
        return {"ok": False, "error": str(e), "steps": steps}


def delete_user(username: str, actor: str = "admin") -> dict:
    if username in PROTECTED_ACCOUNTS:
        return {"ok": False, "error": f"Compte protégé '{username}' -- suppression interdite"}
    err = _validate_username(username)
    if err:
        return {"ok": False, "error": err}

    user_safe = shlex.quote(username)
    steps = []
    try:
        with _ssh() as ssh:
            exists = _run(ssh, f"id {user_safe} 2>/dev/null")
            if not exists or "uid=" not in exists:
                return {"ok": False, "error": f"Utilisateur '{username}' introuvable"}

            out = _run(ssh, _sudo(f"smbpasswd -x {user_safe} 2>&1"))
            steps.append({"cmd": f"smbpasswd -x {username}", "out": out or "OK"})

            # Sans -r : home préservé -- les fichiers du partage restent intacts
            out = _run(ssh, _sudo(f"userdel {user_safe} 2>&1"))
            steps.append({"cmd": f"userdel {username}", "out": out or "OK"})

            audit(actor, "DELETE_USER", username)
            return {"ok": True, "steps": steps, "username": username}

    except Exception as e:
        return {"ok": False, "error": str(e), "steps": steps}


def change_user_password(username: str, new_password: str,
                         actor: str = "admin") -> dict:
    """
    Changement de mot de passe par l'admin pour n'importe quel utilisateur.
    Modifie à la fois le mot de passe Linux (chpasswd) et Samba (smbpasswd).
    """
    if username in PROTECTED_ACCOUNTS:
        return {"ok": False, "error": f"Compte protégé '{username}'"}
    err = _validate_username(username)
    if err:
        return {"ok": False, "error": err}
    if len(new_password) < 8:
        return {"ok": False, "error": "Mot de passe trop court (min 8 caractères)"}

    user_safe = shlex.quote(username)
    pwd_safe  = shlex.quote(new_password)

    steps = []
    try:
        with _ssh() as ssh:
            exists = _run(ssh, f"id {user_safe} 2>/dev/null")
            if not exists or "uid=" not in exists:
                return {"ok": False, "error": f"Utilisateur '{username}' introuvable"}

            # 1. Changer le mot de passe Linux
            out = _run(ssh, f"echo {shlex.quote(f'{username}:{new_password}')} | {_sudo('chpasswd 2>&1')}")
            steps.append({"cmd": "chpasswd (Linux)", "out": out or "OK"})

            # 2. Changer le mot de passe Samba
            out = _run(ssh, f"(echo {pwd_safe}; echo {pwd_safe}) | {_sudo(f'smbpasswd {user_safe} 2>&1')}")
            steps.append({"cmd": f"smbpasswd {username}", "out": out or "OK"})

            audit(actor, "CHANGE_PASSWORD", username, f"par {actor}")
            return {"ok": True, "steps": steps}

    except Exception as e:
        return {"ok": False, "error": str(e), "steps": steps}


def change_own_password(username: str, current_password: str,
                        new_password: str) -> dict:
    """
    Changement de mot de passe par l'employé lui-même.
    Vérifie d'abord l'ancien mot de passe via une vraie authentification SMB.
    """
    if len(new_password) < 8:
        return {"ok": False, "error": "Nouveau mot de passe trop court (min 8 caractères)"}

    # Vérification de l'ancien mot de passe via SMB (authentification réelle)
    import samba_client as smb
    auth = smb.test_auth(username, current_password)
    if not auth["ok"]:
        return {"ok": False, "error": "Mot de passe actuel incorrect"}

    user_safe = shlex.quote(username)
    pwd_safe  = shlex.quote(new_password)

    steps = []
    try:
        with _ssh() as ssh:
            # 1. Changer Linux
            out = _run(ssh, f"echo {shlex.quote(f'{username}:{new_password}')} | {_sudo('chpasswd 2>&1')}")
            steps.append({"cmd": "chpasswd", "out": out or "OK"})

            # 2. Changer Samba
            out = _run(ssh, f"(echo {pwd_safe}; echo {pwd_safe}) | {_sudo(f'smbpasswd {user_safe} 2>&1')}")
            steps.append({"cmd": f"smbpasswd {username}", "out": out or "OK"})

            audit(username, "CHANGE_OWN_PWD", username, "auto-changement")
            return {"ok": True, "steps": steps}

    except Exception as e:
        return {"ok": False, "error": str(e), "steps": steps}


# Logs par utilisateur 
def get_user_logs(username: str) -> dict:
    err = _validate_username(username)
    if err:
        return {"ok": False, "error": err}
    try:
        with _ssh() as ssh:
            user_safe = shlex.quote(username)
            logs = _run(ssh,
                f"{_sudo(f'grep -rh {user_safe} /var/log/samba/ 2>/dev/null | tail -50')}"
                f" || echo 'Aucun log pour {username}'"
            )
            return {"ok": True, "logs": logs, "username": username}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# Fail2ban unban
# (déjà défini plus haut)


# Sauvegardes
def get_backup_status() -> dict:
    try:
        with _ssh() as ssh:
            log  = _run(ssh, _sudo("tail -30 /var/log/samba/backup.log 2>/dev/null || echo 'Journal non accessible'"))
            last = _run(ssh, "ls -lt /srv/backup/ 2>/dev/null | head -5 || echo 'Dossier backup non accessible'")
            return {"ok": True, "log": log, "last_files": last}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_backup_now(actor: str = "admin") -> dict:
    try:
        with _ssh() as ssh:
            out = _run(ssh, _sudo("/usr/local/bin/backup_samba.sh 2>&1 && echo __BACKUP_OK__"))
            if "__BACKUP_OK__" in out:
                audit(actor, "BACKUP_MANUAL", "backup_samba.sh")
                return {"ok": True, "output": out}
            return {"ok": False, "error": out or "Script introuvable ou erreur"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# Test SSH (login admin) 
def test_ssh_auth() -> dict:
    try:
        with _ssh() as ssh:
            whoami = _run(ssh, "whoami")
            return {"ok": True, "user": whoami}
    except paramiko.AuthenticationException:
        return {"ok": False, "error": "Mot de passe SSH incorrect"}
    except Exception as e:
        return {"ok": False, "error": f"Connexion SSH impossible : {str(e)}"}
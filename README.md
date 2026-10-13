# SambaPME

**A web portal for a Samba file server.** Employees sign in and browse the shared
folders of their department; administrators get a dashboard to manage Samba accounts,
watch fail2ban, run backups and audit activity — all from the browser.

> Portfolio project (application for a developer internship). Focus on the
> front-end (HTML/CSS/JS, with a React login page as a bonus), backed by a *real*
> Samba / SSH infrastructure — nothing is mocked.

---

## Context

SambaPME simulates the internal file-sharing portal of a small company (a *PME*).
A Linux server runs **Samba 4** (SMB2/3 with **encryption required**) and exposes one
share per department (`direction`, `comptabilite`, `rh`, `technique`) plus a shared
one (`commun`). The web portal gives employees a clean interface to **list, upload,
download, preview and delete** files, and gives IT a dashboard that operates the
**real server over SSH** (`smbstatus`, `pdbedit`, `fail2ban-client`, `systemctl`,
backup script…).

The infrastructure is intentional and realistic:

- **Samba, fail2ban, backups and logs run as systemd services on the VM** (the real server).
- **Only the web app is containerized** (Docker) — it talks to Samba over SMB and to
  the host over SSH.

## Architecture

```
                         ┌─────────────────────────────┐
                         │           Browser           │
                         │   employee  /  administrator │
                         └───────────────┬─────────────┘
                                         │  HTTP :5000
                                         ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  Ubuntu 24.04 virtual machine  ·  10.0.1.10                               │
│                                                                           │
│   ┌────────────────────────────────────────────────┐                      │
│   │  Docker container : web                        │                      │
│   │  Flask — routes, RBAC, sessions, audit log     │                      │
│   └───────┬──────────────────────────────┬─────────┘                      │
│           │ SMB2/3  :445                 │ SSH  :22                        │
│           ▼                              ▼                                │
│   ┌───────────────────────┐      ┌────────────────────────┐               │
│   │  smbd  /  nmbd        │      │  sshd                  │               │
│   │  5 shares, encrypted  │      │  admin commands        │               │
│   └───────────────────────┘      └────────────────────────┘               │
│                                                                           │
│   systemd (host):  fail2ban  ·  rsyslog  ·  cron (nightly backup)         │
│   /srv/samba (shares)  ·  /srv/backup  ·  /var/log/samba                  │
└───────────────────────────────────────────────────────────────────────────┘
```

### How the pieces communicate

| Flow | Path | What happens |
|------|------|--------------|
| **Employee** | browser → `web:5000` → SMB `10.0.1.10:445` | Login is validated against Samba; list / upload / download / preview / delete are SMB operations on the department share. |
| **Administrator** | browser → `web:5000` → SSH `10.0.1.10:22` | The dashboard runs real commands on the host: service status, `smbstatus`, Samba users, fail2ban, backup, audit. |
| **Security** | fail2ban (host) ⟷ Samba logs | fail2ban bans abusive IPs at the OS level; the dashboard reads the ban list and can unban an address. |
| **Persistence** | `web` container | Server-side sessions, and an `audit.log` of every admin action. |

Why the web app reaches Samba/SSH through `10.0.1.10` and not `127.0.0.1`: inside a
container, `127.0.0.1` is the container itself, not the VM. The services live on the host,
so the portal uses the VM's IP.

## Stack

| Layer | Technology |
|-------|------------|
| Web backend | Python · **Flask** · Flask-Session (server-side filesystem sessions) |
| File access | **smbprotocol** (SMB2/3, encryption required) |
| Server administration | **Paramiko** (SSH) → `systemctl`, `smbstatus`, `pdbedit`, `fail2ban-client`… |
| Frontend | Jinja2 templates · vanilla **JavaScript** · hand-written **CSS** · **React** (Vite) login page *(bonus)* |
| Virtualization | **Vagrant** + libvirt · Ubuntu 24.04 |
| Server services | **Samba 4** (smbd/nmbd) · fail2ban · rsyslog · cron · sshd — all **systemd** |
| Packaging | **Docker** + Docker Compose (web only) · **uv** for Python dependencies |
| Host tooling | **Makefile** + bash scripts (Fedora host) |

## Repository layout

```
backend/           Flask application
  app.py             routes, RBAC, sessions, error handlers
  samba_client.py    SMB operations (list, upload, stream, preview, delete)
  admin_logic.py     SSH/Paramiko administration + audit log
  ueba_hook.py       UEBA pipeline (out of scope, not wired in)
frontend/          Jinja templates + static assets (css / js)
infra/             Vagrantfile (VM + Docker) and setup_samba.sh (provisions Samba)
Dockerfile         builds the web image
docker-compose.yml single `web` service
main.py            entry point (Flask, port 5000)
Makefile, tools.sh host tooling (provision libvirt/vagrant/uv)
pyproject.toml, uv.lock   Python dependencies
roadmap.md         working plan / status
```

## Quickstart

**Prerequisites:** a host with libvirt + Vagrant + uv (`make tools` installs them on Fedora).

```bash
# 1. Host tooling (libvirt, Vagrant, uv)
make tools

# 2. Boot the VM (10.0.1.10) with Docker installed
make machine

# 3. Provision Samba, fail2ban and the backup cron on the VM
make infra

# 4. Start the web container (on the VM, from the synced repo)
cd /home/vagrant/samba
cp .env.example .env
docker compose up -d --build

# 5. Open the portal
#    http://10.0.1.10:5000
```

**Without Vagrant** (any Ubuntu server): copy the repo over, run
`./infra/setup_samba.sh` on the host, then `cp .env.example .env && docker compose up -d --build`.

All configuration lives in `.env` (see `.env.example`): VM IP, Samba server, SSH
credentials, Flask secret key.

## Demo accounts

| Role | Username | Password |
|------|----------|----------|
| Direction | `direction1` · `direction2` | `Samba2026!` |
| Accounting | `compta1` · `compta2` | `Samba2026!` |
| Human Resources | `rh1` · `rh2` | `Samba2026!` |
| Technical | `tech1` · `tech2` | `Samba2026!` |
| Administrator | `admin` | *authenticated against the VM over SSH (credentials from `.env`)* |

Employees only see the shares allowed to their group, plus the shared `commun` space.

## Security highlights

- **SMBv1 disabled**, SMB2 minimum, **SMB3 encryption required** (`smb encrypt = required`).
- **fail2ban** watches the Samba logs and bans brute-force IPs — active on the host, not simulated.
- Every external value is passed through **`shlex.quote()`** before reaching a shell command.
- **Server-side sessions**, signed, with a configurable secret key.
- An **audit log** records administrative actions.
- Nightly **backups** to `/srv/backup` (full on Sunday, incremental otherwise).

## Production notes

- For the demo the web app is served by the **built-in Flask server** (with threading) —
  no extra WSGI layer, to keep the footprint minimal. A production deployment would sit
  behind a reverse proxy (e.g. nginx) — mind the `client_max_body_size` limit
  (default 1 MB vs. uploads up to 500 MB here).
- Uploads are currently read fully into memory (bounded by `MAX_CONTENT_LENGTH`, 500 MB);
  a streaming upload path would be the next step.

## Screenshots

*(to be added — login dark/light, portal file list, admin dashboard: overview, users, fail2ban)*

## Status & roadmap

See [`roadmap.md`](./roadmap.md) for the detailed, file-by-file plan and current progress.
The project is being finalized: getting the stack fully launchable, cleaning the
repository, then polishing the README with screenshots.

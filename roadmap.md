# Roadmap — SambaPME

> Refonte « portfolio » d'un portail web pour serveur Samba, pour une demande de stage dev.
> But : **repo GitHub public, propre et lançable** (VM Samba en systemd + web dockerisé) + README vendeur.
>
> Lecture **fichier par fichier**. Légende : `[FAIT]` · `[BLOQUANT]` (empêche de lancer) · `[À FAIRE]` · `[OPTION]`.

---

## Décisions verrouillées

- **Samba reste en systemd sur la VM** (pas de conteneur) → admin, fail2ban, backups réels.
- **Seul le web (Flask) est dockerisé** → service unique `docker-compose`.
- **Pas de gunicorn** : on garde le **serveur Flask intégré** (`python main.py`). Pour la concurrence (upload / streaming par chunks), activer `threaded=True`.
- **Pas de nginx** (documenté au README comme upgrade prod).
- **React** : uniquement la **page de login** (bonus, sautable).
- **UI en anglais** (cible recruteur).
- VM `10.0.1.10`, creds SSH `vagrant/vagrant`, mot de passe Samba démo **`Samba2026!`**.

## Architecture cible

```
        Navigateur (employé / admin)
                 │  HTTP :5000
                 ▼
┌───────────────────────────────────────────────────────────┐
│  VM Ubuntu 24.04 — 10.0.1.10                              │
│                                                           │
│  ┌───────────────────────────┐                            │
│  │ Docker : web (Flask)      │                            │
│  │  routes · sessions · audit│                            │
│  └───────┬───────────┬───────┘                            │
│          │ SMB :445   │ SSH :22                           │
│          ▼            ▼                                   │
│     smbd/nmbd       sshd          ← systemd (hôte)        │
│                                                           │
│  fail2ban · rsyslog · cron (backup) · /srv/samba          │
└───────────────────────────────────────────────────────────┘
```

---

## État git (au moment de l'analyse)

- Commits existants : `cc43fdc First commit`, `12a9abb Start cleaning`, `de3f1ed cleaning v1 ok`.
- **Non commités** : `Dockerfile`, `docker-compose.yml`, `backend/app.py`, `backend/samba_client.py`, `backend/admin_logic.py`, `.gitignore`, `.dockerignore`, `infra/Vagrantfile`, `infra/setup_samba.sh`, `main.py`.
- **Untracked à committer** : `pyproject.toml`, `uv.lock`, `Makefile`, `tools.sh` → **sinon `git clone` + `docker build` casse** (le Dockerfile les copie).
- Déjà réglé : `test` et `backend/__pycache__/*.pyc` retirés de l'index ✔.

## Bloquants (dans l'ordre)

1. `docker-compose.yml` : syntaxe `volumes` invalide + pas d'`env_file` → l'admin ne reçoit pas ses identifiants.
2. `.env.example` : **vide (0 octet)**.
3. `Dockerfile` : `USER appuser` + volumes root → sessions & audit inécrivables.
4. `pyproject.toml` : `[project.scripts]` pointe sur un module inexistant.
5. `pyproject.toml` / `uv.lock` / `Makefile` / `tools.sh` non commités.

---

## Fichier par fichier

### `docker-compose.yml` — `[BLOQUANT]`
- `[FAIT]` `environment` en mapping, `depends_on` fantôme retiré.
- `[ ]` Corriger les volumes (la forme `- clé: /chemin` est un **mapping YAML invalide**, il faut `clé:/chemin` sans espace) :
  ```yaml
      volumes:
        - admin-audit:/app/backend/audit.log
        - sessions:/tmp/flask_sessions_samba
  ```
- `[ ]` Ajouter `env_file: [.env]` → sinon seuls `SAMBA_SERVER`/`SSH_HOST` arrivent dans le conteneur ; **`SSH_USER`/`SSH_PASSWORD`/`SSH_PORT`/`SAMBA_DOMAIN`/`FLASK_SECRET_KEY` manquent → login admin KO**.
- `[OPTION]` `healthcheck` (GET `/`).

### `.env.example` — `[BLOQUANT]`
- Le `.env` réel est **correct** (9 clés présentes, gitignoré) ✔. Il faut le **mirror** dans `.env.example` :
  ```ini
  VM_IP=10.0.1.10
  SAMBA_SERVER=10.0.1.10
  SAMBA_DOMAIN=WORKGROUP
  SSH_HOST=10.0.1.10
  SSH_USER=vagrant
  SSH_PASSWORD=vagrant
  SSH_PORT=22
  FLASK_SECRET_KEY=change_me
  FLASK_DEBUG=False
  ```

### `Dockerfile` — `[BLOQUANT]`
- `[FAIT]` base `python:3.14-slim` alignée sur `requires-python >=3.14` ; install via `uv` + lockfile.
- `[ ]` **Permissions** : `USER appuser` + volumes nommés (créés `root:root`) →
  - Flask-Session ne peut pas écrire `/tmp/flask_sessions_samba` → **sessions mortes (login en boucle)** ;
  - le volume monté sur `/app/backend/audit.log` crée un **dossier** (le fichier n'existe pas dans l'image) → **audit KO**.
  - **Option rapide (démo)** : retirer `USER appuser` (tourner en root).
  - **Option propre** : entrypoint qui `chown` les chemins montés + monter l'audit sur un **dossier** (`/app/backend/audit`) et adapter `AUDIT_LOG` dans `admin_logic.py`.
- `[ ]` `CMD` : lancer directement le python du venv pour éviter le resync `uv` au runtime → `CMD ["/app/.venv/bin/python", "main.py"]`.
- `[OPTION]` `HEALTHCHECK` ; retirer `AS builder` (pas de 2ᵉ stage).

### `main.py`
- `[FAIT]` point d'entrée ; lit l'environnement.
- `[ ]` `app.run(..., threaded=True)` → indispensable pour ne pas bloquer upload/streaming **sans gunicorn**.
- `[ ]` défaut `SAMBA_SERVER` l.15 : `192.168.0.119` → `10.0.1.10`.
- `[OPTION]` envelopper `app.run()` dans `if __name__ == "__main__":`.

### `backend/app.py`
- `[FAIT]` chemins `template_folder`/`static_folder` corrigés ; imports relatifs ; UEBA commenté ; majeurité des flashs en anglais.
- `[ ]` défauts `192.168.0.119` → `10.0.1.10` (l. 161, 301, 422).
- `[ ]` Résidus FR / typos :
  - l.105 `f"depuis {request.remote_addr}"` → `f"from ..."` ;
  - l.245 `"Preview impossible :"` → `"Preview failed: "` ;
  - l.348 `"created ins '{group}'"` → `"created in '{group}'"` ;
  - l.379 `"Les mots de passe ne correspondent pas."` → EN.
- `[OPTION]` supprimer le bloc commenté l.418-428.

### `backend/samba_client.py`
- `[ ]` défaut l.20 `SAMBA_SERVER = "192.168.0.119"` → `"10.0.1.10"`.
- `[ ]` messages FR → EN : l.160, l.305, l.344.

### `backend/admin_logic.py`
- `[FAIT]` `SSH_HOST` par défaut = `10.0.1.10` ✔.
- `[ ]` messages FR → EN : l.144, 146, 148, 267, 286, 288, 300, 327, 361, 366, 400, 480, 482.
- `[ ]` **Quirk sécurité** : `test_ssh_auth()` (l.474) ignore le mot de passe saisi → le champ « password » du login admin est cosmétique (l'auth utilise `SSH_USER/SSH_PASSWORD`). À corriger ou assumer/documenter.
- `[OPTION]` retirer `vboxuser` de `PROTECTED_ACCOUNTS` (l.31).

### `backend/ueba_hook.py`
- `[FAIT]` hors périmètre, non importé. On le garde (traçabilité).

### `frontend/templates/admin.html`
- `[ ]` 4 libellés FR → EN : « Vue d'ensemble » → *Overview* ; « IPS ACTUELLEMENT BANNIES » → *CURRENTLY BANNED IPs* ; « Authentifications Samba » → *Samba authentications* ; « Comptes Samba actifs » → *Active Samba accounts*.

### `frontend/static/js/*` + `portal.html` / `preview_text.html` / `login.html`
- `[FAIT]` `TITLES` de `admin.js` déjà en anglais ; pas d'accents FR résiduels.
- Relecture rapide : seul `admin.html` portait du FR.

### `.gitignore`
- `[FAIT]` `.env`, `audit.log`, `__pycache__/`, `.python-version`, `.venv`, `test`.
- `[OPTION]` ajouter `*.pyc`, `.ruff_cache/`, `.vagrant/`, `node_modules/`, `frontend-react/dist/`.
- Note : `.python-version` ignoré = OK (la version est aussi pinnée par `pyproject.toml`).

### `.dockerignore`
- `[ ]` `ueba_hook.py` → **`backend/ueba_hook.py`** (chemin actuel faux).
- `[ ]` ajouter `.env`, `.git/`, `.venv/`, `infra/`, `roadmap.md`, `Makefile`, `tools.sh`.

### `pyproject.toml`
- `[FAIT]` description, deps, `requires-python >=3.14`.
- `[ ]` `[project.scripts] website = "website:main"` → **module inexistant** : supprimer le bloc.

### `requirements.txt`
- `[ ]` redondant avec `pyproject.toml`/`uv.lock` (le Dockerfile utilise `uv`) → supprimer.

### `Makefile`
- `[FAIT]` `VAGRANT_CWD=infra` ; cibles `machine`/`destroy`/`ssh`/`status`/`infra`.
- `[ ]` `.PHONY` liste des cibles inexistantes (`start/recreate/new/clean/help`) ; `help` vide.
- `[OPTION]` cible `env` (`cp .env.example .env`) et `up` (`docker compose up -d --build` via `vagrant ssh`).

### `tools.sh` (hôte Fedora)
- `[FAIT]` libvirt, vagrant, uv, repo HashiCorp.
- `[ ]` ajouter **`sshpass`** (requis par `setup_samba.sh`, absent côté Fedora).
- `[ ]` `vagrant-libvirt` n'est **pas** un paquet dnf → `vagrant plugin install vagrant-libvirt`.

### `infra/Vagrantfile`
- `[FAIT]` VM `10.0.1.10` ; Docker + compose installés ; `usermod -aG docker vagrant`.
- `[ ]` `source: ".."` (l.21) copie **tout le repo** (`.venv`, `.git`…) → cibler un `source` propre ou exclure.
- `[ ]` **Samba n'est pas provisionné** par Vagrant → il faut lancer `setup_samba.sh` (documenté dans le README, cible `make infra`).
- `[ ]` Vérifier l'accès hôte→VM (`libvirt__forward_mode: "none"` + DHCP off = réseau host-only).
- `[OPTION]` `lv.default_prefix = ""` à confirmer.

### `infra/setup_samba.sh`
- `[FAIT]` `SERVER_IP=10.0.1.10` ; typo `nologin` corrigée ; étapes rsyslog/scp fantômes retirées.
- `[ ]` l.44-47 : `sudo apt-get install sshpass` s'exécute sur l'**hôte Fedora** → échoue ; installer `sshpass` via `tools.sh` (dnf) ou rendre l'étape tolérante.
- Note : `SAMBA_PASSWORD=Samba2026!` (l.25) → aligné avec les comptes démo.

### `README.md`
- `[FAIT]` v1 : contexte, stack, diagramme, flux, structure, comptes démo, sécurité.
- `[ ]` Finaliser le quickstart (une fois docker/env réglés).
- `[ ]` Insérer les **screenshots** (login dark/light, portal, admin) en fin.

### React (bonus) — non commencé
- `[ ]` `frontend-react/` (Vite) : login + endpoints `/api/login` · `/api/session` · `/api/logout`.
- `[ ]` Login Jinja conservé en fallback ; Dockerfile multi-stage (Node → dist).

---

## Ordre d'exécution conseillé

1. **Rendre lançable** : `.env.example` → `docker-compose.yml` → `Dockerfile` (permissions/CMD) → `pyproject.toml`.
2. **Cohérence** : défauts IP + FR/typos (backend + `admin.html`).
3. **Commit** : `pyproject.toml`, `uv.lock`, `Makefile`, `tools.sh` + le reste.
4. **Infra** : `tools.sh` (`sshpass`), `Vagrantfile` (`source`), puis `make machine && make infra`.
5. **README** finalisé + screenshots.
6. **React** si le temps.

## Points de coupe (du plus sacrifiable au socle)

1. **React** → login Jinja conservé.
2. **Persistance** sessions/audit (volumes) → accepter la perte au rebuild (démo).
3. Cible Makefile `up` + polish responsive.

> Socle non négociable : **corrections `[BLOQUANT]` + `docker compose up` + README + push GitHub**.

# Roadmap — SambaPME (refonte pour demande de stage)

> Objectif : livrer en **4 jours** un repo GitHub public, reproductible (docker-compose),
> avec une UI soignée, une page de login en React (bonus), et un README vendeur.

---

## 1. Contexte

Le projet est un portail web (« SambaPME v7 ») qui proxifie un serveur de fichiers
**Samba** : Flask en front, `smbprotocol` pour les opérations fichiers, `paramiko` (SSH)
pour l'administration, `audit.log` pour la traçabilité.

La base est **fonctionnelle et déjà bien sécurisée** (SMBv1 désactivé, `smb encrypt = required`,
fail2ban, `shlex.quote` sur toutes les valeurs externes, sessions server-side).
On ne réécrit **rien** : on corrige, on stabilise, on conteneurise le web et on rend le tout démontrable.

**Hors périmètre :** le pipeline UEBA (`ueba_hook.py`, `model/ueba/daemon.py`) est **laissé tel
quel, zéro budget**. Il ne gêne pas et renforce le fil rouge sécurité.

---

## 2. Décisions verrouillées

1. **Samba reste en service systemd sur la VM** — aucun conteneur Samba.
   Le code actuel fonctionne **tel quel** : `systemctl`, `fail2ban`, `smbstatus`, `pdbedit`,
   statistiques hôte… rien à adapter. Le fil rouge sécurité reste **réel** (vraies IP, vraies bans).
2. **Seul le web (Flask) est dockerisé** — service unique `docker-compose`, servi par **gunicorn seul**.
3. **nginx non implémenté** pour la démo (upgrade production documenté au README).
4. **React** : seule la **page de login** est refaite (Vite + endpoint JSON) — bonus contrôlé, sautable.
5. **Vagrant conservé** : la VM provisionne Docker ; `setup_samba.sh` se lance depuis l'hôte
   (ou manuellement), IP fixe connue = pas de souci de découverte.
6. **Langue de l'UI** : anglais (cible recruteur). On harmonise les messages FR/EN.

---

## 3. Architecture cible

```
VM Ubuntu 24.04  (IP fixe ex. 10.0.1.10 — définie par Vagrant)
│
├── systemd (hôte) :
│     smbd · nmbd · fail2ban · rsyslog · sshd · cron (backup)
│     └── /srv/samba (partages) · /var/log/samba · /srv/backup
│
└── docker compose (repo cloné dans la VM)
      └── web : Flask + gunicorn → port 5000 publié
            ├── SAMBA_SERVER=10.0.1.10 :445   (SMB  → systemd)
            └── SSH_HOST=10.0.1.10     :22    (admin → systemd)
```

- **Flux employés** : navigateur → `web:5000` → SMB (`SAMBA_SERVER:445`).
- **Flux admin** : navigateur → `web:5000` → SSH (`SSH_HOST:22`) → commandes sur l'hôte.
- `systemctl`, fail2ban, stats : toutes les commandes admin s'exécutent **sur la vraie VM**
  → rien n'est faussé ni à adapter.

---

## 4. Incohérences à corriger (inventaire de départ)

### 4.1 Bug bloquant — direction des templates
- `backend/app.py:23`
  `Flask(__name__, template_folder="website/templates", static_folder="website/static")`
- Le dossier réel est `frontend/`, et le root de l'app est `backend/`.
- Correctif : `template_folder="../frontend/templates"`, `static_folder="../frontend/static"`.

### 4.2 IP / identifiants incohérents
- `backend/samba_client.py:20` : défaut `SAMBA_SERVER = "192.168.0.119"`.
- `backend/admin_logic.py:18-20` : défauts `SSH_HOST="192.168.1.120"`, `SSH_USER="vboxuser"`.
- `infra/Vagrantfile:11-17` : VM sur `10.0.1.10`, creds `vagrant/vagrant`.
- Correctif : tous ces défauts deviennent des var d'env, défauts cohérents avec la VM
  (`10.0.1.10`, `vagrant`) — plus aucun IP en dur contradictoire.

### 4.3 Fichiers manquants
- **`requirements.txt`** (backend) : pinner les versions qui tournent déjà
  (`flask`, `flask-session`, `paramiko`, `smbprotocol`, `python-dotenv`, `gunicorn`).
- **`.env.example`** (root) : modèle pour `.env` (voir §7).
- **`.gitignore`** (root) : `.env`, `venv/`, `__pycache__/`, `*.pyc`, `node_modules/`,
  `frontend-react/dist/`, `.DS_Store`, `backend/audit.log`, `.vagrant/`.
- **`infra/setup_samba.sh`** référence des fichiers **jamais livrés** :
  - ligne ~63 : `scp 1* rsyslog.conf smb.conf ...` → `1*` (norme sécu) + `rsyslog.conf` + `smb.conf` absents ;
  - lignes ~238-240 : `cp ... 10-samba-audit.conf /etc/rsyslog.d/` et `cp rsyslog.conf /etc/`.
  - Décision : soit **générer ces fichiers** dans `infra/`, soit **retirer ces étapes**
    (le `smb.conf` est de toute façon écrit inline plus bas par heredoc).

### 4.4 UI FR/EN mélangée → uniformiser en anglais
- `frontend/templates/admin.html` : « Vue d'ensemble », « Authentifications Samba »,
  « IPS ACTUELLEMENT BANNIES », « Comptes Samba actifs », etc.
- `frontend/static/js/admin.js` : `TITLES` anglais → couper/interdire le FR mixte.
- `backend/app.py` : flashs français (« supprimé », « Prévisualisation impossible »,
  « Les mots de passe ne correspondent pas »…) → tous en anglais.
- `frontend/templates/portal.html` + `preview_text.html` : flashs/chaînes FR à passer en anglais.

### 4.5 Git
- Le seul commit initial ne contient que `README.md` (1 ligne) ; **tout le code est untracked**.
- Correctif : commits atomiques proprement rédigés (voir §9).

---

## 5. Jour 1 — Corriger & stabiliser le code

**Objectif : l'app tourne en venv (mode host) sans erreur, et le repo est propre.**

- [ ] Fixer les chemins templates/static (`backend/app.py`) → §4.1.
- [ ] Créer `requirements.txt` (backend) et valider un `pip install -r` propre.
- [ ] Créer `.env.example` + `.env` (non commité) + `.gitignore` → §4.3, §7.
- [ ] Réconcilier les IP : tout lire depuis l'environnement, défauts = VM (`10.0.1.10`) → §4.2.
- [ ] Nettoyer `infra/setup_samba.sh` : typo `-s /usr/sbin/nologinbash` → `/usr/sbin/nologin` ;
      trancher §4.3 (générer ou retirer les fichiers rsyslog manquants).
- [ ] Lancer l'app en venv, **avec la VM Samba joignable** :
      tester login employé, login admin, listage, upload, téléchargement, preview, delete,
      chgt de mot de passe.
  - Si la VM n'est pas dispo, tester au moins que l'app **démarre** et que toutes les
    routes non-SMB répondent (login affiché, redirections, 403…).
- [ ] Uniformiser les flashs et libellés UI en anglais → §4.4.
- [ ] Commit propre : `fix(backend): corrige les chemins de templates + config env-driven`.

**DoD Jour 1** : `python app.py` démarre sans crash, aucun IP en dur incohérent, git status propre
après commit.

---

## 6. Jour 2 — Docker du web (gunicorn) + provisioning VM

**Objectif : `docker compose up` sur la VM sert l'app à `:5000`, Samba en systemd derrière.**

### 6.1 Choix de serving (décidé)
- **Gunicorn seul** dans le conteneur web — suffisant pour la démo :
  - `--worker-class gthread --threads 4` : nécessaire pour le **streaming 64 Ko**
    (download/preview) et les uploads sans bloquer les workers.
  - Pas de nginx : rien à configurer côté limites de body (piège du
    `client_max_body_size` 1 Mo par défaut — à éviter pour des uploads de 500 Mo).
- nginx → documenté au README comme « upgrade production » (port 80, TLS, statiques, gzip),
  **non implémenté**.

### 6.2 Dockerfile web (`backend/Dockerfile`)
- `FROM python:3.12-slim`
- copie `requirements.txt`, `pip install -r`
- copie `backend/` + `frontend/` (respecter la résolution `../frontend/...`)
- `WORKDIR /app/backend`
- CMD : `gunicorn -w 2 --threads 4 --worker-class gthread -b 0.0.0.0:5000 app:app`
- `HEALTHCHECK` : GET `/` (curl ou python).
- **volumes (persistance)** :
  - sessions Flask : `/tmp/flask_sessions_samba` → volume nommé (sinon déconnexion à chaque rebuild)
  - `audit.log` : monter un volume **sur le fichier** `/app/backend/audit.log`
    (ne PAS monter sur `/app/backend` entier, sinon on masque le code).
- (J3) étape multi-stage ajoutée pour builder `frontend-react/dist` avec Node.

### 6.3 `docker-compose.yml` (root) — service unique `web`
```yaml
services:
  web:
    build: ./backend
    ports: ["5000:5000"]
    env_file: .env
    environment:
      SAMBA_SERVER: ${VM_IP:-10.0.1.10}   # la VM (systemd) :445
      SSH_HOST:      ${VM_IP:-10.0.1.10}   # la VM (systemd) :22
    volumes:
      - web-sessions:/tmp/flask_sessions_samba
      - web-audit:/app/backend/audit.log
    restart: unless-stopped
    healthcheck: ...
volumes:
  web-sessions:
  web-audit:
```
> Pas de dépendance entre conteneurs : Samba est un service hôte, pas un service compose.

### 6.4 Provisioning VM
- **Vagrantfile** : ajouter un provisioner shell qui installe `docker.io` +
  `docker-compose-plugin` (et `usermod -aG docker` pour l'utilisateur). La VM garde
  `10.0.1.10` (IP connue = celle de `.env`). La `synced_folder` existante peut
  monter le repo dans la VM.
- **`setup_samba.sh`** : lancé **depuis l'hôte** une fois la VM up :
  `vagrant up` puis `./infra/setup_samba.sh` (sshpass géré par le script,
  creds par défaut `vagrant/vagrant` cohérentes avec le Vagrantfile).
  Identique sur une machine réelle uniquement en changeant `SERVER_IP`/creds.
- **(option) `deploy.sh`** : étape « push → VM » : `git clone/pull`, `cp .env.example .env`,
  `docker compose up -d --build`. À mettre en infra/ si le temps le permet.

### 6.5 Test e2e (sur la VM)
1. Sur une VM propre : `git clone` → `cp .env.example .env` → `docker compose up -d --build`.
2. Login employé (`direction1/Samba2024!`) → portal → listage.
3. Upload + download + preview (texte + image) + delete.
4. Login admin (creds SSH) → dashboard (**KPIs de la vraie VM**, via systemd) → créer/changer/supprimer un user.
5. Unban IP (fail2ban **réel** sur l'hôte) + backup manuel.
6. Tester depuis une machine tierce du réseau (accès `http://<IP-VM>:5000`).
7. Redémarrer la VM → la stack se relance (`restart: unless-stopped`) et les données persistent.

**Ligne de repli (si Docker web embêtant)** : gunicorn en service systemd direct sur la VM
(comme Samba) — le code est strictement identique. Aucune perte.

**DoD Jour 2** : sur VM vierge → app visible à `:5000`, e2e §6.5 au vert, Samba et fail2ban natifs.

---

## 7. Jour 3 — Login React (bonus) + polish UI

### 7.1 Application React
- Nouveau dossier `frontend-react/` : `npm create vite@latest . -- --template react`.
- Composant Login : username/password, flèche affichage mdp, **comptes démo** (comme l'actuel
  `login.html`), selecteur de thème dark/light (réutiliser les var CSS existantes).
- Afficher les erreurs API (identifiants incorrects, serveur injoignable…).

### 7.2 Endpoints JSON côté Flask (nouveaux, dans une blueprint dédiée)
- `POST /api/login`  {username, password} → `{ok, role, redirect}` (réutilise
  `smb.test_auth` / `admin_logic.test_ssh_auth`, même mécanique qu'aujourd'hui).
- `GET  /api/session` → `{logged_in, username, group, role}`.
- `POST /api/logout` → vide la session.
- Factoriser la fonction de connexion partagée avec la route `login()` existante.

### 7.3 Intégration
- Le build (`npm run build`) produit `dist/`. Flask sert `dist/index.html` sur `/login`
  (les assets via `send_from_directory`).
- `login.html` conservé en fallback (route `/login-legacy` par exemple).
- `frontend-react/dist/` au `.gitignore` (build au déploiement).
- Mettre à jour le `Dockerfile web` en **multi-stage** (node LTS → builder → copie `dist/`
  dans l'image finale python). Une seule image finale.

### 7.4 Polish des vues restantes (si temps)
- **Responsive** : menu latéral portal/admin → version mobile.
- **États vides / erreurs** : chaque état a un visuel propre (déjà partiellement le cas).
- **Cohérence FR/EN** : terminer §4.4 + titres d'onglets admin.

### 7.5 Coupe de sécurité jour 3
- Si le temps déborde : **React sauté** → on garde le login Jinja et on finit le polish.
  (Le bonus est conditionnel, le socle ne l'est pas.)

**DoD Jour 3** : login (React ou fallback Jinja) fonctionne de bout en bout, UI cohérente
et correcte en mobile + desktop.

---

## 8. Jour 4 — Packaging & push GitHub

### 8.1 README.md (réécriture complète)
Sections prévues :
- Pitch en 3 lignes + screenshot hero.
- Schéma ASCII de l'architecture (dupliquer §3) : systemd Samba + web Docker.
- **Quickstart** : `vagrant up` → `./infra/setup_samba.sh` → `git clone → cp .env.example .env →
  docker compose up -d --build` (et la variante sans Vagrant).
- Table des **comptes démo** (2 users/groupe + admin) & mot de passe par défaut.
- Posture sécurité (SMBv1 off, SMB3 obligatoire, fail2ban **actif sur l'hôte**, `shlex.quote`,
  session server-side, `audit.log`, backups) — le fil rouge SOC, **réel**.
- **Serving** : gunicorn seul (démo) ; nginx en prod (port 80, TLS, statiques) + piège
  `client_max_body_size`.
- Stack technique & structure du repo.
- Pistes d'amélioration (UEBA daemon, `hosts allow`, CI, tests, nginx/TLS).

### 8.2 captures
- `docs/` : login (dark + light), portal (liste de fichiers), admin (overview, users, fail2ban).
- Référencées dans le README.

### 8.3 Push
- Repo public GitHub (nom type `sambapme`).
- Branche `main`, tags `v1.0.0`.
- `.env` jamais commité ; secrets démo uniquement via `.env.example`.
- Message de commit cohérent avec la roadmap (jour par jour).

### 8.4 Test final « from scratch »
- VM vierge (ou `vagrant destroy && vagrant up`) :
  `setup_samba.sh` → `git clone → cp .env.example .env → docker compose up -d --build`
  → e2e complet.
- Check final : rien ne dépend d'un état local de ta machine.

**DoD Jour 4** : le repo est publié, le quickstart marche sur machine propre, README complet.

---

## 9. Git — règles du dépôt

- Commit par journée / par étape logique (messages conventionnels : `fix:`, `feat:`, `docs:`, `chore:`).
- Ne **jamais** commiter : `.env`, `venv/`, `__pycache__/`, `node_modules/`, `frontend-react/dist/`, `audit.log`.
- Garder l'historique **lisible** : un recruteur regarde les commits.

---

## 10. Notes techniques / pièges connus

- **Cible réseau du conteneur** : depuis le conteneur web, `127.0.0.1` désigne le **conteneur
  lui-même** → SMB/SSH doivent pointer sur l'**IP de la VM** (`10.0.1.10`), pas loopback.
  Si problème de connectivité bridge → alternative `network_mode: host` (mais IP préférée).
- **ufw sur la VM** : si actif, ouvrir `5000` (web) et garder `445/139/22` pour les clients
  SMB/SSH légitimes.
- **Gunicorn** : `gthread --threads 4` indispensable pour le **streaming 64 Ko** et les uploads.
- **Upload 500 Mo en RAM** : `app.py` fait `data = file.read()` → fichier entier en mémoire.
  OK pour la démo mono-utilisateur ; le documenter dans le README.
- **Sessions Flask filesystem** : `/tmp/flask_sessions_samba` éphémère → **volume nommé**
  recommandé (sinon déconnecté à chaque rebuild).
- **`audit.log`** : écrit à `backend/audit.log` dans le conteneur → monter un volume sur ce
  **fichier** (et non sur `/app/backend` qui masquerait le code).
- **fail2ban** : reste sur l'hôte en systemd → efficacité réelle (vraies IP, bans iptables hôte).
  Le fil rouge sécurité est authentique, pas simulé.
- **`FLASK_SECRET_KEY`** : fourni via `.env` ; jamais commiter un vrai secret.
- **`MAX_CONTENT_LENGTH` 500 Mo** : conservé, à documenter.
- **UEBA** : on ne touche pas. Les endpoints `/api/ueba/*` existent toujours, rien ne les
  consomme, c'est OK.

---

## 11. Points de coupe (ordre de sacrifice)

| Priorité | Élément sacrifiable | Impact | Condition de coupe |
|---|---|---|---|
| 1 | Login React | Bonus perdu, login Jinja conservé | Fin de J3 dépassée sans UI stable |
| 2 | Persistance sessions/audit (volumes) | Rebuild → déconnexions + audit vidé | Chronophage en J2 |
| 3 | `deploy.sh` / synced_folder | Déploiement manuel simple documenté suffit | Temps manquant en J2 |

> **Plus de risque conteneur Samba ni fail2ban** : ces deux points sont résolus nativement
> par le choix systemd.

Le socle non sacrifiable : **corrections §4 + web docker (ou gunicorn systemd) + README + push GitHub**.
#!/bin/bash

# setup_server.sh -- SambaPME
# Configure a clean Ubuntu Server 24.04 VM into a full Samba server.
# Run from the HOST machine (not from inside the VM).
#
# Usage:
#   chmod +x setup_server.sh
#   ./setup_server.sh
#
# This script configures:
#   - Samba 4 with SMB3 encryption, SMBv1 disabled
#   - 5 shares (direction, comptabilite, rh, technique, commun)
#   - 10 users (2 per group)
#   - Fail2ban jail for samba
#   - Daily backup cron job
#   - Samba logs

set -e  # Stop immediately on any error

# Configuration
SERVER_IP="${SERVER_IP:-10.0.1.10}"
SSH_USER="${SSH_USER:-vagrant}"
SSH_PASSWORD="${SSH_PASSWORD:-vagrant}"
SAMBA_PASSWORD="${SAMBA_PASSWORD:-Samba2024!}"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Pre-flight checks
echo ""
echo "========================================================"
echo "          SambaPME -- Server Configuration              "
echo "========================================================"
echo ""
log_info "Target: $SSH_USER@$SERVER_IP"
echo ""

command -v sshpass >/dev/null 2>&1 || {
    log_warn "sshpass not installed -- installing..."
    sudo apt-get install -y sshpass >/dev/null 2>&1
}

# SSH function to execute a command on the VM
ssh_run() {
    sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no \
        -o ConnectTimeout=10 \
        "$SSH_USER@$SERVER_IP" "$@"
}

# Test SSH connection
log_info "Testing SSH connection..."
ssh_run "echo 'SSH OK'" >/dev/null 2>&1 || log_error "Cannot connect to $SERVER_IP -- is the VM running?"
log_ok "SSH connection established"

# 0. Copying relevant files to the machine
ssh_run "mkdir ~/Samba/"
scp 1* rsyslog.conf smb.conf $SSH_USER@$SERVER_IP:~/Samba/

# 1. System update
log_info "Updating system..."
ssh_run "echo '$SSH_PASSWORD' | sudo -S apt-get update -qq 2>/dev/null"
ssh_run "echo '$SSH_PASSWORD' | sudo -S apt-get upgrade -y -qq 2>/dev/null"
log_ok "System up to date"

# 2. Install packages
log_info "Installing Samba, Fail2ban, tools..."
ssh_run "echo '$SSH_PASSWORD' | sudo -S apt-get install -y \
    samba samba-common smbclient \
    fail2ban \
    cron \
    rsync \
    ufw \
    -qq 2>/dev/null"
log_ok "Packages installed"

# 3. Create Linux groups
log_info "Creating Linux groups..."
for group in direction comptabilite rh technique; do
    ssh_run "echo '$SSH_PASSWORD' | sudo -S groupadd -f $group 2>/dev/null || true"
done
log_ok "Groups created: direction, comptabilite, rh, technique"

# 4. Create users
log_info "Creating Samba users..."

declare -A USER_GROUPS=(
    ["direction1"]="direction"
    ["direction2"]="direction"
    ["compta1"]="comptabilite"
    ["compta2"]="comptabilite"
    ["rh1"]="rh"
    ["rh2"]="rh"
    ["tech1"]="technique"
    ["tech2"]="technique"
)

for username in "${!USER_GROUPS[@]}"; do
    group="${USER_GROUPS[$username]}"

    # Create user if it doesn't exist
    # User does not need home directory
    ssh_run "id $username >/dev/null 2>&1 || \
        echo '$SSH_PASSWORD' | sudo -S useradd -M -G $group -s /usr/sbin/nologinbash $username 2>/dev/null"

    # Linux password
    ssh_run "echo '$SSH_PASSWORD' | sudo -S bash -c \"echo '$username:$SAMBA_PASSWORD' | chpasswd\" 2>/dev/null"

    # Samba password
    ssh_run "echo '$SSH_PASSWORD' | sudo -S bash -c \"printf '%s\\n%s\\n' '$SAMBA_PASSWORD' '$SAMBA_PASSWORD' | smbpasswd -a $username\" 2>/dev/null || true"
    ssh_run "echo '$SSH_PASSWORD' | sudo -S smbpasswd -e $username >/dev/null 2>&1"
done
log_ok "Users created with password: $SAMBA_PASSWORD"

# 5. Create share directories
log_info "Creating share directories..."

ssh_run "echo '$SSH_PASSWORD' | sudo -S mkdir -p \
    /srv/samba/direction \
    /srv/samba/comptabilite \
    /srv/samba/rh \
    /srv/samba/technique \
    /srv/samba/commun"

# Strict permissions for private shares
for share in direction comptabilite rh technique; do
    ssh_run "echo '$SSH_PASSWORD' | sudo -S chown root:$share /srv/samba/$share"
    ssh_run "echo '$SSH_PASSWORD' | sudo -S chmod 2770 /srv/samba/$share"
done

# Commun accessible to everyone
ssh_run "echo '$SSH_PASSWORD' | sudo -S chown root:root /srv/samba/commun"
ssh_run "echo '$SSH_PASSWORD' | sudo -S chmod 2777 /srv/samba/commun"

log_ok "Directories created with permissions"

# 6. smb.conf configuration
log_info "Writing smb.conf..."

ssh_run "cat << 'SMBCONF' | echo '$SSH_PASSWORD' | sudo -S tee /etc/samba/smb.conf >/dev/null
[global]
   workgroup = WORKGROUP
   server string = SambaPME Server
   netbios name = SAMBAPME

   # Security
   security = user
   map to guest = never
   restrict anonymous = 2

   # Protocols
   min protocol = SMB2
   max protocol = SMB3

   # SMB3 encryption required
   smb encrypt = required

   # Logging
   log file = /var/log/samba/log.%m
   max log size = 1000
   log level = 2

   # Performance
   socket options = TCP_NODELAY IPTOS_LOWDELAY SO_RCVBUF=131072 SO_SNDBUF=131072

[direction]
   path = /srv/samba/direction
   valid users = @direction
   read only = no
   create mask = 0660
   directory mask = 2770
   force group = direction

[comptabilite]
   path = /srv/samba/comptabilite
   valid users = @comptabilite
   read only = no
   create mask = 0660
   directory mask = 2770
   force group = comptabilite

[rh]
   path = /srv/samba/rh
   valid users = @rh
   read only = no
   create mask = 0660
   directory mask = 2770
   force group = rh

[technique]
   path = /srv/samba/technique
   valid users = @technique
   read only = no
   create mask = 0660
   directory mask = 2770
   force group = technique

[commun]
   path = /srv/samba/commun
   valid users = @direction @comptabilite @rh @technique
   read only = no
   create mask = 0664
   directory mask = 2777
SMBCONF"
log_ok "smb.conf written"

# 7. Fail2ban configuration
log_info "Configuring Fail2ban..."

ssh_run "cat << 'F2BCONF' | echo '$SSH_PASSWORD' | sudo -S tee /etc/fail2ban/jail.d/samba.conf >/dev/null
[samba]
enabled  = true
port     = 139,445
filter   = samba
logpath  = /var/log/samba/log.smbd
maxretry = 3
bantime  = 600
findtime = 300
F2BCONF"

ssh_run "cat << 'F2BFILT' | echo '$SSH_PASSWORD' | sudo -S tee /etc/fail2ban/filter.d/samba.conf >/dev/null
[Definition]
failregex = .*Authentication.*Account-Name: <HOST>.*NT_STATUS_WRONG_PASSWORD.*
            .*Authentication.*Account-Name: <HOST>.*NT_STATUS_NO_SUCH_USER.*
            .*Authentication.*smb login.*from <HOST>.*failed.*
ignoreregex =
F2BFILT"
log_ok "Fail2ban configured"

# Rsyslog configs 
log_info "Setting rsyslog surveillance up ..."

ssh_run "cp ~/Samba/10-samba-audit.conf /etc/rsyslog.d/"
ssh_run "cp ~/Samba/rsyslog.conf /etc/"
ssh_run "echo '$SSH_PASSWORD' | sudo -S systemctl restart rsyslog"

# 8. Backup script
log_info "Creating backup script..."

ssh_run "cat << 'BAKSCRIPT' | echo '$SSH_PASSWORD' | sudo -S tee /usr/local/bin/backup_samba.sh >/dev/null
#!/bin/bash
BACKUP_DIR=/srv/backup
SRC_DIR=/srv/samba
LOG=/var/log/samba/backup.log
DATE=\$(date '+%Y-%m-%d %H:%M:%S')
DOW=\$(date '+%u')  # 1=Mon, 7=Sun

mkdir -p \$BACKUP_DIR

echo \"[\$DATE] Starting backup (DOW=\$DOW)\" >> \$LOG

if [ \"\$DOW\" = \"7\" ]; then
    # Sunday -- full backup
    tar -czf \$BACKUP_DIR/samba_full_\$(date '+%Y%m%d').tar.gz \$SRC_DIR 2>>\$LOG
    echo \"[\$DATE] FULL backup completed\" >> \$LOG
else
    # Mon-Sat -- incremental backup
    rsync -av --archive --delete \$SRC_DIR/ \$BACKUP_DIR/samba_incremental/ >> \$LOG 2>&1
    echo \"[\$DATE] INCREMENTAL backup completed\" >> \$LOG
fi
BAKSCRIPT"

ssh_run "echo '$SSH_PASSWORD' | sudo -S chmod +x /usr/local/bin/backup_samba.sh"
ssh_run "echo '$SSH_PASSWORD' | sudo -S mkdir -p /srv/backup"

# Cron at 2am
ssh_run "echo '$SSH_PASSWORD' | sudo -S bash -c \
    '(crontab -l 2>/dev/null | grep -v backup_samba; echo \"0 2 * * * /usr/local/bin/backup_samba.sh\") | crontab -'"
log_ok "Backup script created + cron 0 2 * * *"

# 9. Start services
log_info "Starting and enabling services..."

ssh_run "echo '$SSH_PASSWORD' | sudo -S systemctl enable --now smbd nmbd fail2ban 2>/dev/null"
ssh_run "echo '$SSH_PASSWORD' | sudo -S systemctl restart smbd nmbd fail2ban 2>/dev/null"
log_ok "Services started: smbd, nmbd, fail2ban"

# 10. Final verification
echo ""
echo "========================================================"
log_info "Final verification..."

smbd_status=$(ssh_run "systemctl is-active smbd")
f2b_status=$(ssh_run "systemctl is-active fail2ban")
shares=$(ssh_run "echo '$SSH_PASSWORD' | sudo -S smbclient -L localhost -U direction1%$SAMBA_PASSWORD 2>/dev/null | grep -c Disk || echo 0")

echo ""
echo "  smbd      : $smbd_status"
echo "  fail2ban  : $f2b_status"
echo "  shares    : $shares detected"
echo ""

if [ "$smbd_status" = "active" ]; then
    echo -e "${GREEN}========================================================${NC}"
    echo -e "${GREEN}  SambaPME server configured successfully!             ${NC}"
    echo -e "${GREEN}========================================================${NC}"
    echo -e "${GREEN}  Server IP     : $SERVER_IP                       ${NC}"
    echo -e "${GREEN}  User password : $SAMBA_PASSWORD                  ${NC}"
    echo -e "${GREEN}  SSH admin     : $SSH_USER / $SSH_PASSWORD        ${NC}"
    echo ""
else
    log_error "smbd did not start correctly. Check: ssh $SSH_USER@$SERVER_IP 'journalctl -u smbd -n 20'"
fi

# SambaPME - host-side tooling.
#
# Every target here runs on YOUR machine (the host), never inside the VM.
# The VM only receives: Docker (via Vagrant) and the Samba setup (via SSH).

SHELL   := /bin/bash
VAGRANT := env VAGRANT_CWD=infra vagrant

# VM connection (matches infra/setup_samba.sh defaults)
VM_IP   ?= 10.0.1.10
VM_USER ?= vagrant
VM_PASS ?= vagrant

# Everything that runs *inside* the VM goes over plain SSH (no Vagrant needed):
# it matches infra/setup_samba.sh and keeps `make up/down/logs/ssh` independent
# from the Vagrant/libvirt plugin. Vagrant is only used for the VM lifecycle
# (machine / status / destroy).
SSH_OPTS  := -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
SSH       := sshpass -p $(VM_PASS) ssh $(SSH_OPTS) $(VM_USER)@$(VM_IP)
RSYNC_SSH := sshpass -p $(VM_PASS) ssh $(SSH_OPTS)

.DEFAULT_GOAL := help
.PHONY: help tools machine ssh status destroy infra env up down logs sync

help: ## Show this help
	@echo "SambaPME - available targets:"
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

tools: ## Install host tools (libvirt, Vagrant, uv) - Fedora
	chmod +x tools.sh
	./tools.sh

machine: ## Boot the VM (10.0.1.10) and install Docker inside it
	$(VAGRANT) up

sync: ## Re-copy the project into the VM (/home/vagrant/samba), excluding .venv/.git
	rsync -az --delete \
		--exclude '.git' --exclude '.venv' --exclude '.vagrant' \
		--exclude '__pycache__' --exclude '*.pyc' \
		-e "$(RSYNC_SSH)" \
		./ $(VM_USER)@$(VM_IP):/home/vagrant/samba/
	@echo "Synced to $(VM_USER)@$(VM_IP):/home/vagrant/samba/"

infra: ## Provision Samba + fail2ban + backups on the VM (over SSH, from the host)
	chmod +x infra/setup_samba.sh
	./infra/setup_samba.sh

env: ## Create .env from .env.example (if missing)
	@test -f .env || cp .env.example .env
	@echo ".env ready"

up: ## Build & start the web container (on the VM)
	$(SSH) "cd /home/vagrant/samba && cp -n .env.example .env 2>/dev/null; docker compose up -d --build --force-recreate"

down: ## Stop the web container (on the VM)
	$(SSH) "cd /home/vagrant/samba && docker compose down"

logs: ## Follow the web container logs
	$(SSH) "cd /home/vagrant/samba && docker compose logs -f"

ssh: ## SSH into the VM
	$(SSH)

status: ## Show the VM status
	$(VAGRANT) status

destroy: ## Destroy the VM
	$(VAGRANT) destroy -f

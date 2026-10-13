# SambaPME — host-side tooling.
#
# Every target here runs on YOUR machine (the host), never inside the VM.
# The VM only receives: Docker (via Vagrant) and the Samba setup (via SSH).

SHELL   := /bin/bash
VAGRANT := env VAGRANT_CWD=infra vagrant

.DEFAULT_GOAL := help
.PHONY: help tools machine ssh status destroy infra env up down logs

help: ## Show this help
	@echo "SambaPME — available targets:"
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

tools: ## Install host tools (libvirt, Vagrant, uv) — Fedora
	chmod +x tools.sh
	./tools.sh

machine: ## Boot the VM (10.0.1.10) and install Docker inside it
	$(VAGRANT) up

infra: ## Provision Samba + fail2ban + backups on the VM (over SSH, from the host)
	@command -v sshpass >/dev/null 2>&1 || { \
		echo "sshpass is required on the host — install it with: sudo dnf install sshpass"; exit 1; }
	chmod +x infra/setup_samba.sh
	./infra/setup_samba.sh

env: ## Create .env from .env.example (if missing)
	@test -f .env || cp .env.example .env
	@echo ".env ready"

up: ## Build & start the web container (on the VM)
	$(VAGRANT) ssh -c "cd /home/vagrant/samba && cp -n .env.example .env; docker compose up -d --build"

down: ## Stop the web container (on the VM)
	$(VAGRANT) ssh -c "cd /home/vagrant/samba && docker compose down"

logs: ## Follow the web container logs
	$(VAGRANT) ssh -c "cd /home/vagrant/samba && docker compose logs -f"

ssh: ## SSH into the VM
	$(VAGRANT) ssh

status: ## Show the VM status
	$(VAGRANT) status

destroy: ## Destroy the VM
	$(VAGRANT) destroy -f

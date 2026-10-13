
# Usage:
#   make 

.PHONY: start recreate new destroy clean help

VAGRANT := env VAGRANT_CWD=infra vagrant

help:


tools:
	@echo "Installation des outils ..."
	chmod u+x tools.sh
	./tools.sh

machine:
	@echo "Mise en service de la machine virtuelle ..."
	$(VAGRANT) up

destroy:
	$(VAGRANT) destroy -f

ssh:
	$(VAGRANT) ssh

status:
	$(VAGRANT) status  

infra:
	@echo "Mise en place de l'environement"
	chmod u+x infra/setup_samba.sh
	./infra/setup_samba.sh 

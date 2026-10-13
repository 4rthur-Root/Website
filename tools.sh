#!/usr/bin/env bash
set -euo pipefail

# Helper

install_pkg() {
    local pkg="$1"
    if rpm -q "$pkg" &>/dev/null; then
        echo "  ✓ $pkg - already installed, skipping"
    else
        echo "  * Installing $pkg..."
        sudo dnf install -y -qq "$pkg"
    fi
}

add_zshrc() {
    local line="$1"
    if grep -qF "$line" ~/.zshrc 2>/dev/null; then
        echo "  ✓ $line - already in ~/.zshrc, skipping"
    else
        echo "  * Adding to ~/.zshrc: $line"
        echo "$line" >> ~/.zshrc
    fi
}

# Virtualization backend

echo " Virtualization backend "
for pkg in qemu-kvm libvirt libguestfs-tools virt-install rsync; do
    install_pkg "$pkg"
done

echo "  * Enabling libvirtd..."
sudo systemctl enable --now libvirtd

add_zshrc 'export LIBVIRT_DEFAULT_URI="qemu:///system"'

# HashiCorp repo & Vagrant

echo " Vagrant (HashiCorp repo) "
install_pkg dnf-plugins-core

if ! ls /etc/yum.repos.d/hashicorp.repo &>/dev/null; then
    echo "  * Adding HashiCorp repo..."
    sudo dnf config-manager addrepo --from-repofile=https://rpm.releases.hashicorp.com/fedora/hashicorp.repo
else
    echo "  ✓ HashiCorp repo — already present, skipping"
fi

install_pkg vagrant

# Vagrant plugins

echo " Vagrant plugins "
install_pkg vagrant-libvirt

add_zshrc 'export VAGRANT_DEFAULT_PROVIDER=libvirt'

# UV
echo " UV package manager"
install_pkg uv

# Done

echo ""
echo "Done. Run 'source ~/.zshrc' (or open a new shell) to apply env vars."   
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
# HashiCorp Vagrant loads plugins from ~/.vagrant.d/gems/<ruby> (its own
# embedded Ruby) and ignores the distro's /usr/share/vagrant/gems. Installing
# the Fedora `vagrant-libvirt` RPM is therefore useless here: the plugin has to
# be installed the supported way. It compiles against libvirt, hence the -devel
# packages below.

echo " Vagrant plugins "
for pkg in gcc make libvirt-devel libxml2-devel; do
    install_pkg "$pkg"
done

if vagrant plugin list 2>/dev/null | grep -q '^vagrant-libvirt'; then
    echo "  ✓ vagrant-libvirt plugin - already installed, skipping"
else
    echo "  * Installing vagrant-libvirt plugin (this can take a couple of minutes)..."
    vagrant plugin install vagrant-libvirt
fi

add_zshrc 'export VAGRANT_DEFAULT_PROVIDER=libvirt'

# UV
echo " UV package manager"
install_pkg uv

# Done

echo ""
echo "Done. Run 'source ~/.zshrc' (or open a new shell) to apply env vars."   
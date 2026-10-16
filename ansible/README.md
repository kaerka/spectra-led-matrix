# Spectra Ansible

See [docs/ORCHESTRATION.md](../docs/ORCHESTRATION.md) for full usage.

```bash
cp inventory/hosts.example.yml inventory/hosts.yml
# edit hosts.yml with real IPs (never commit)
ansible-playbook playbooks/bootstrap.yml -i inventory/hosts.yml -l controller -e ansible_user="$USER"
```

Standalone Mini-Spectra Clocks (`mini_clocks` group) deploy directly from the
Ansible machine, no Pi5 involved:

```bash
ansible-playbook playbooks/mini-clocks.yml -i inventory/hosts.yml
```

Per-device panel layout goes in `matrix_config` (written to
`/data/spectra/config/matrix.local.json`); optional `clock_config` sets the
world-clock cities and `brightness_schedule` replaces the night-dim steps.

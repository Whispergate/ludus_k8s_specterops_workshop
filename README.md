# K8s Attack Path Workshop: Ludus Range

> ⚠️ **Unofficial.** This is a community port of the SpecterOps *"Kubernetes Attack Path"* workshop lab environment from Vagrant to [Ludus](https://ludus.cloud). It is not affiliated with, endorsed by, or supported by SpecterOps. Use at your own risk.

An Ansible-based [Ludus](https://ludus.cloud) range that spins up the full lab environment for the [Kubernetes Attack Path workshop](https://github.com/SpecterOps/): a Kubernetes 1.35 cluster (1 control plane + 2 workers), a Mythic C2 teamserver, and a private TLS Docker registry, all wired up with the RBAC/manifests/certificates needed to run the three attack-path labs.

The original lab ships as a `Vagrantfile` targeting VirtualBox on a single host. This port converts every shell provisioner into a proper Ansible role and deploys the whole thing on a Proxmox-backed Ludus server, so a range can be handed out to any number of students on WireGuard.

## What gets deployed

| VM | Role | vCPU / RAM | Purpose |
|---|---|---|---|
| `k8s-control-plane-1` | K8s control plane | 2 / 4 GB | kubeadm-initialized cluster, Calico CNI, seeds prod-debug client cert |
| `k8s-worker-1` | K8s worker | 1 / 2 GB | Tainted `workshop/reserved-for-later:NoSchedule` (Lab 2 pre-condition) |
| `k8s-worker-2` | K8s worker + workshop manifests | 1 / 2 GB | Hosts `prod-backend`; applies all workshop RBAC/policy manifests |
| `teamserver` | Mythic C2 + Docker registry + workshop users | 4 / 8 GB | Mythic UI on :7443, TLS registry on :5000, Poseidon agents running as `developer` and `noaccess` |

All four VMs land on the same VLAN (default `10`) so the K8s nodes can reach the teamserver's registry over its hostname.

## Roles

Eight custom roles + one upstream role, wired up via `config.yml`.

### Custom (in `roles/`)

| Role | What it does | Replaces |
|---|---|---|
| `k8s-attack-path-common` | Installs containerd, kubeadm/kubelet/kubectl 1.35.1, CNI plugins, kernel modules, pre-pulls Calico images | `vagrant-scripts/common.sh` |
| `k8s-attack-path-control-plane` | Runs `kubeadm init`, installs Calico via the Tigera operator, stages the join command + admin kubeconfig for the workers | `vagrant-scripts/control-plane.sh` |
| `k8s-attack-path-worker` | Consumes the staged join command and joins the cluster | `vagrant-scripts/worker.sh` |
| `k8s-attack-path-registry-cert` | Generates a self-signed cert for the teamserver's Docker registry and installs it into containerd trust on every K8s node | `vagrant-scripts/generate-registry-cert.sh` + `install-registry-cert*.sh` |
| `k8s-attack-path-workshop` | Applies all Lab 1/2/3 manifests (namespaces, code-server, cicd RBAC, admission policy, prod-backend, RBAC gadgets) and taints worker-1 | `vagrant-scripts/workshop-setup.sh` |
| `k8s-attack-path-prod-debug` | Uses the K8s certificates API to mint a client cert for the `prod-debug-agent` user and seeds it as `prod-debug-certs` Secret in `production` | `vagrant-scripts/generate-prod-debug-agent.sh` |
| `k8s-attack-path-teamserver` | Layered on top of the Mythic role: installs Poseidon + `container_wrapper` + `container_registry` agents, creates the Mythic API token, builds a Poseidon HTTP payload, creates `developer`/`noaccess` workshop users with Poseidon systemd units, spins up a TLS Docker registry container | `playbooks/roles/k8s-wksp-teamserver` |
| `k8s-attack-path-kubeconfig` | Reads the `developer` ServiceAccount token from the cluster and drops a scoped kubeconfig at `/home/developer/.kube/config` on the teamserver | `vagrant-scripts/generate-kubeconfig.sh` |

### Upstream

| Role | Purpose |
|---|---|
| [`whispergate.ludus_mythic_teamserver`](https://github.com/Whispergate/ludus_mythic_teamserver) | Installs Docker, clones/builds Mythic, installs its stock C2 profiles (HTTP, SMB) and agents (Apollo, forge, service_wrapper, Starburst, Erebus), and stands up the `mythicteamserver` systemd service |

## Prerequisites

- A working Ludus server (self-hosted or team instance) with the CLI configured
- Your Ludus API key set (`export LUDUS_API_KEY=...` or via `~/.config/ludus/config.yml`)
- A built `ubuntu-24.04-x64-server-template` on the Ludus host
- WireGuard client for VPN access to the range

## Setup

### 1. Confirm the template

```bash
ludus templates list
```

If `ubuntu-24.04-x64-server-template` isn't built, build it (~30–60 min):

```bash
ludus templates build -n ubuntu-24.04-x64-server-template
```

### 2. Install the upstream Mythic role

```bash
ludus ansible roles add-from-git https://github.com/Whispergate/ludus_mythic_teamserver.git
```

### 3. Install the custom workshop roles

From the repo root:

```bash
cd ludus-range
for role in roles/k8s-attack-path-*; do
  ludus ansible roles add -d "$role"
done
```

Verify:

```bash
ludus ansible roles list
```

You should see `whispergate.ludus_mythic_teamserver` plus all 8 `k8s-attack-path-*` roles.

The roles use modules from `community.general`, `community.docker`, and `ansible.posix`. These ship with the default Ludus Ansible install; if a task later fails with `couldn't resolve module`, add the missing one with `ludus ansible collections add <name>`.

### 4. Push the range config

```bash
ludus range config set -f config.yml
```

### 5. Deploy

```bash
ludus range deploy
```

Watch progress in a second terminal:

```bash
ludus range logs -f
```

Total deploy time: **60–90 minutes** (Mythic build + Calico + Kubernetes bootstrap dominate).

If a task fails, `ludus range errors` shows the tail. The roles are idempotent, so re-running `ludus range deploy` picks up where it left off.

## Access

Assuming a `range_second_octet` of `2`:

| Service | URL / Command |
|---|---|
| Mythic UI | `https://10.2.10.10:7443` (password from `sudo /opt/mythic/mythic-cli config get MYTHIC_ADMIN_PASSWORD` on the teamserver) |
| Docker registry | `https://10.2.10.10:5000` |
| Code-server (Lab 1 entry) | Port-forward from teamserver as `developer` user, then browse to `http://<teamserver>:8080` |
| Cluster admin | SSH to `k8s-control-plane-1`, use root's kubeconfig (`sudo kubectl ...`) |
| Developer identity | SSH to teamserver, `sudo -iu developer`, use `~/.kube/config` |

Substitute your actual `range_second_octet` (check `ludus range status`).

## Verifying the deploy

Quick sanity checks (from `k8s-control-plane-1`):

```bash
sudo kubectl get nodes -o wide          # 3 nodes Ready v1.35.1
sudo kubectl get pods -A                # everything Running
sudo kubectl describe node k8s-worker-1 | grep Taints    # workshop/reserved-for-later
sudo kubectl -n production get pod,secret,configmap      # prod-backend + certs
sudo kubectl get validatingadmissionpolicy cicd-block-node-steering
sudo kubectl get clusterrole prod-debug-agent-observer
```

On the teamserver:

```bash
sudo systemctl status mythicteamserver poseidon-developer poseidon-noaccess
sudo docker ps    # Mythic containers + docker_registry
```

In the Mythic UI's Callbacks tab you should see both `developer` and `noaccess` Poseidon callbacks live within a few seconds of deploy completion.

## Layout

```
ludus-range/
├── config.yml                        # Ludus range definition (4 VMs, role assignments)
├── README.md                         # (this file)
└── roles/
    ├── k8s-attack-path-common/
    ├── k8s-attack-path-control-plane/
    ├── k8s-attack-path-worker/
    ├── k8s-attack-path-registry-cert/
    ├── k8s-attack-path-workshop/
    │   └── files/manifests/          # 01-Lab, 02-Lab, 03-Lab Kubernetes manifests
    ├── k8s-attack-path-prod-debug/
    ├── k8s-attack-path-teamserver/
    │   ├── files/payload_setup.py    # Mythic API client that builds the Poseidon payload
    │   └── templates/                # Poseidon systemd unit
    └── k8s-attack-path-kubeconfig/
```

## Iterating

Edit a role, then reinstall it and re-run the deploy. Ludus reapplies only what's changed:

```bash
ludus ansible roles add -d roles/k8s-attack-path-<name> --force
ludus range deploy
```

To wipe and restart from scratch:

```bash
ludus range rm
ludus range deploy
```

## Credits

- **Workshop content & original Vagrant lab**: [SpecterOps: Kubernetes for Red Teamers](https://academy.specterops.io/kubernetes-for-red-teamers). The labs, RBAC design, and manifests are theirs.

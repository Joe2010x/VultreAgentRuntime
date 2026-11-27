# Deploy on Vultr

Use an Ubuntu 24.04 LTS Cloud Compute VM with an SSH key. A starting size for this single-job demo is 2 vCPUs and 4 GB RAM. Allow inbound TCP 80 and 443 for Caddy and TCP 22 from your admin IP. Point your demo hostname's DNS A record at the instance's public IPv4 address.

## Prepare the VM

On the VM, install Docker before installing `runsc` so the gVisor package can register the Docker runtime.

```bash
sudo apt update
sudo apt install -y docker.io python3-venv caddy curl ca-certificates gnupg
curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" | sudo tee /etc/apt/sources.list.d/gvisor.list >/dev/null
sudo apt update
sudo apt install -y runsc
sudo runsc install
sudo systemctl restart docker
sudo docker run --rm --runtime=runsc hello-world
sudo useradd --system --user-group --shell /usr/sbin/nologin vultre-agent
sudo install -d -m 0755 /opt/vultre-agent
```

See the [gVisor installation guide](https://gvisor.dev/docs/user_guide/install/) for supported systems.

## Install the app

From the local project directory, replace `USER@VM_IP` with your SSH target. The archive contains the application source and deployment templates.

```bash
tar -czf - requirements.txt runner/Dockerfile runner/run.sh runner/*.py runner/sample-sales.csv web/*.py web/index.html deploy |
  ssh USER@VM_IP 'sudo -n tar -xzf - --no-same-owner -C /opt/vultre-agent'
```

On the VM, build the image and test it using the exact runtime the service will use.

```bash
cd /opt/vultre-agent
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo docker build -t vultre-agent-runner:local runner
sudo -u vultre-agent -g docker sh -c 'cd "$(mktemp -d)" && VULTRE_PREBUILT=1 VULTRE_SANDBOX_RUNTIME=runsc /opt/vultre-agent/runner/run.sh timeout-test'
```

The test should print the containment checks and end with `Timed out after 3s. Container removed.`

## Add the inference settings and start the service

```bash
sudo install -d -m 0700 /etc/vultre-agent
sudo touch /etc/vultre-agent/inference.env
sudo chmod 600 /etc/vultre-agent/inference.env
sudoedit /etc/vultre-agent/inference.env
```

Set `VULTR_INFERENCE_API_KEY` to your subscription key and `VULTR_INFERENCE_MODEL` to your chat model ID in that file. For example, the model line is `VULTR_INFERENCE_MODEL=qwen3.8-flash-next`.

```bash
sudo install -m 0644 deploy/vultre-agent.service /etc/systemd/system/vultre-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now vultre-agent
curl -fsS http://127.0.0.1:8000/ >/dev/null
```

The backend binds only to loopback. Its service account can use the Docker daemon, which grants host-equivalent privileges to the backend. Generated code runs with the separate gVisor sandbox policy and receives only its CSV and script mounts.

## Enable HTTPS and verify

Copy `deploy/Caddyfile` to `/etc/caddy/Caddyfile` on the demo VM. Replace `csv.example.com` with your DNS hostname, then validate and reload Caddy.

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Open the public HTTPS URL on a separate device or browser session. Ask for a chart with the sample data, click **Test sandbox timeout**, then ask a different question. Confirm that both charts render and the timeout log reports container removal.

For startup failures, use `sudo journalctl -u vultre-agent -u caddy -n 80 --no-pager`.

## Current Stockholm demo

The demo is available at [https://70.34.198.248](https://70.34.198.248). It uses a Let's Encrypt short-lived IP certificate, so it does not require a DNS hostname. Caddy serves the ACME challenge from `/var/www/vultre-acme` on port 80 and redirects other HTTP requests to HTTPS. The `vultre-cert-renew.timer` checks for renewal twice daily. Certbot's deploy hook copies renewed certificate files into `/etc/caddy/vultre-tls` and reloads Caddy.

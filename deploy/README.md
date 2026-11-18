# Deploying MarketMind AI to a private always-on server

The app runs 24/7 on a small Ubuntu server that only your Tailscale devices can reach. Your laptop is only for development.
Total time: about 45 minutes. Commands are for **Git Bash on your laptop** unless marked **(server)**.

## A. Put the code on GitHub (laptop)

1. Create a **private** repo at https://github.com/new named `marketmind_ai` (no README, no .gitignore).
2. In the project folder (the first two lines only once per laptop):
   ```bash
   git config --global user.name "Your Name"
   git config --global user.email "you@example.com"
   git init -b main
   git add .
   git commit -m "MarketMind AI 0.7.1"
   git remote add origin https://github.com/<you>/marketmind_ai.git
   git push -u origin main      # a browser window asks you to sign in to GitHub
   ```
   Check `git status` / the repo page: `marketmind.db` and `.venv` must NOT be there (they're in `.gitignore`).
3. Make an SSH key for logging in to the server (press Enter at every prompt): `ssh-keygen -t ed25519`, then `cat ~/.ssh/id_ed25519.pub` and copy the line.

## B. Create the server

4. Any provider; pick **Ubuntu 24.04 LTS, 2 GB RAM or more**, region **Singapore** (closest to Perth), and paste your SSH public key.
   Hetzner Cloud or DigitalOcean are simplest. Oracle Cloud's Always Free tier also works but its Ubuntu images ship
   extra firewall rules, so expect more fiddling.
5. Log in with the IP address it gives you: `ssh root@<IP>` (Oracle: `ssh ubuntu@<IP>`).
6. **(server)** Join your Tailscale network:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up --ssh --hostname=marketmind
   ```
   Open the link it prints and approve. Install Tailscale on your laptop and phone too, same account.
   Test from the laptop: `ssh root@marketmind` (no IP needed; Tailscale may ask you to confirm in the browser).

## C. Install MarketMind

7. Copy the setup script up and run it (laptop, from the project folder):
   ```bash
   scp deploy/setup.sh root@marketmind:/root/
   ssh -t root@marketmind "sudo bash /root/setup.sh git@github.com:<you>/marketmind_ai.git"
   ```
   It prints a **deploy key**. Add it at GitHub → repo → Settings → Deploy keys → Add (leave *write access* off), then press Enter.
   It installs everything, runs all tests, starts the app and the nightly backup, and turns on the firewall (~5 minutes).
8. **(server)** Add your API key (optional): `sudo nano /etc/marketmind.env`, paste after `ANTHROPIC_API_KEY=`,
   save (Ctrl+O, Enter, Ctrl+X), then `sudo systemctl restart marketmind`.
9. **(server)** Close public SSH once step 6's `ssh root@marketmind` works: `sudo ufw delete allow OpenSSH`.
   Optionally remove port 22 in the provider's firewall too. The server is now reachable only through Tailscale.

## D. Start using it

10. On your phone (Tailscale on): open **http://marketmind:8501**, create your account, then *Add to Home Screen*.
11. Make yourself admin: `ssh root@marketmind "sudo mm grant-admin <your-username>"`, then refresh.
12. Check market data works from the server: Analyse → NVDA → Fetch. If Yahoo refuses data-centre traffic, run the
    same kit on a Raspberry Pi at home instead (identical steps from 5).

## E. Everyday

| Task | Command |
| --- | --- |
| Ship a change | Laptop: test, then `git add -A && git commit -m "what changed" && git push`, then `ssh root@marketmind "sudo /opt/marketmind/deploy/update.sh"` (pulls, tests, backs up, restarts; rolls back automatically if any test fails) |
| Is it running? | `ssh root@marketmind "systemctl status marketmind"` |
| Recent errors | `ssh root@marketmind "journalctl -u marketmind -n 50"` |
| Restart | `ssh root@marketmind "sudo systemctl restart marketmind"` |
| Users / admin / password reset | `sudo mm list-users`, `sudo mm grant-admin <u>`, `sudo mm reset-password <u>` (server) |
| Backups | Automatic every night at 03:30 Perth time; 14 days kept in `/var/lib/marketmind/backups` |
| Copy a backup to your laptop | `ssh root@marketmind "sudo mm backup /tmp/mm.db && chmod 644 /tmp/mm.db"` then `scp root@marketmind:/tmp/mm.db ./marketmind-backup.db` |
| Restore a backup (server) | `sudo systemctl stop marketmind && sudo cp /var/lib/marketmind/backups/<file>.db /var/lib/marketmind/marketmind.db && sudo chown marketmind: /var/lib/marketmind/marketmind.db && sudo systemctl start marketmind` |
| Change settings / API key | `sudo nano /etc/marketmind.env` then `sudo systemctl restart marketmind` |

Security notes: the app runs as an unprivileged `marketmind` account that can only write to `/var/lib/marketmind`; the
settings file is root-only; the deploy key is read-only; the firewall admits only Tailscale traffic; Ubuntu installs
security updates automatically.

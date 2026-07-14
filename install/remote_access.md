# Remote access with Tailscale

DebriPod binds to `127.0.0.1` by default. That is the right default for a local media app. For remote access, use Tailscale instead of binding DebriPod directly to your LAN or the public internet.

This guide uses Tailscale Services so DebriPod gets a stable HTTPS name inside your tailnet, while the Flask app can keep listening only on `127.0.0.1`.

## What you need

You need a Tailscale account, Tailscale installed on the DebriPod host, Tailscale installed on every device that will connect to DebriPod, and admin permissions in the tailnet if you want to define a Service and approve the host.

The DebriPod host must be authenticated with a Tailscale tag before it can host a Tailscale Service. Do not use a tag on your normal laptop or phone just to browse DebriPod. Tags are for the host machine that runs the service.

## Install Tailscale

Install Tailscale on the host computer and sign in to the same tailnet that your other devices use.

Windows and macOS can use the normal Tailscale installer from `https://tailscale.com/download`.

Linux can use the official install script from Tailscale or the package instructions for your distribution. After install, start and sign in with:

```bash
sudo tailscale up
```

Install Tailscale on your phone, tablet, laptop, or other client device too. Sign in to the same tailnet.

## Create the host tag and permissions

Open the Tailscale admin console, go to Access controls, and merge rules like this into the existing policy. Replace `you@example.com` with your Tailscale user, a group, or another tag that should be allowed to authenticate the host as `tag:debripod-host`.

```json
{
  "tagOwners": {
    "tag:debripod-host": ["you@example.com"]
  },
  "autoApprovers": {
    "services": {
      "svc:debripod": ["tag:debripod-host"]
    }
  },
  "grants": [
    {
      "src": ["autogroup:member"],
      "dst": ["svc:debripod"],
      "ip": ["443"]
    }
  ]
}
```

The `tagOwners` block controls who can apply the host tag. The `autoApprovers` block lets a host with `tag:debripod-host` advertise `svc:debripod` without a manual approval click. The `grants` block lets tailnet members access the service on port `443`. If you do not want automatic approval, leave out `autoApprovers` and approve the service host manually later.

## Authenticate the host with the tag

On the DebriPod host, reauthenticate Tailscale with the host tag.

Linux:

```bash
sudo tailscale up --advertise-tags=tag:debripod-host
```

macOS or Windows Tailscale CLI:

```bash
tailscale up --advertise-tags=tag:debripod-host
```

Tailscale may print a login or approval URL. Open it, sign in with a tag owner account, and approve the tagged host. After this, the host is identified by the tag instead of a normal user identity.

## Start DebriPod locally

Start DebriPod with the installer or from the repo folder.

Windows:

```powershell
irm https://raw.githubusercontent.com/JoeDoe56/Debripod/main/install/debripod.ps1 | iex
```

macOS or Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/JoeDoe56/Debripod/main/install/debripod.sh | sh
```

Confirm that the host can open DebriPod locally at:

```text
http://127.0.0.1:8083
```

If you selected another port with `--port` or `DEBRIPOD_PORT`, use that port in the next command instead of `8083`.

## Start Tailscale Serve for DebriPod

Run this on the DebriPod host. Replace `YOUR_SERVICE_NAME` with `debripod` unless you created a different service name. Replace `YOUR_LOCAL_PORT` with the local DebriPod port.

```bash
tailscale serve --bg --service=svc:YOUR_SERVICE_NAME --https=443 127.0.0.1:YOUR_LOCAL_PORT
```

For the default DebriPod install, that becomes:

```bash
tailscale serve --bg --service=svc:debripod --https=443 127.0.0.1:8083
```

Check the Serve status:

```bash
tailscale serve status --json
```

If you did not configure auto approval, open the Tailscale admin console, go to Services, choose the DebriPod service, find the pending host advertisement, and approve it.

## Access DebriPod from other devices

On another device in the same tailnet, make sure Tailscale is connected, then open the HTTPS address printed by the `tailscale serve` command. It usually looks like this:

```text
https://debripod.YOUR_TAILNET.ts.net/
```

Sign in with your DebriPod local account. Tailscale controls network access, but DebriPod login still controls app access.

If an older Linux client cannot reach the Service, update Tailscale. On Linux clients with Tailscale 1.93 or earlier, you may also need:

```bash
sudo tailscale set --accept-routes
```

## Stopping or changing the service

To temporarily stop the service host from accepting new connections, drain it:

```bash
tailscale serve drain svc:debripod
```

To remove the HTTPS endpoint on port `443`, run the same service command with `off`:

```bash
tailscale serve --service=svc:debripod --https=443 off
```

To clear all Serve configuration on the host:

```bash
tailscale serve reset
```

## Troubleshooting

If the service URL does not load, first confirm DebriPod loads locally on the host at `http://127.0.0.1:8083`. Then check `tailscale status`, `tailscale serve status --json`, the Services page in the Tailscale admin console, and the Access controls policy.

If the command says the host needs approval, approve it in the Services page or add an `autoApprovers.services` rule for `svc:debripod` and the host tag.

If login or passkeys act strangely through the service URL, use the exact HTTPS service URL shown by Tailscale. Passkeys are tied to the browser origin, so a passkey created at `http://127.0.0.1:8083` is not the same credential as one created at the Tailscale HTTPS name.

Do not use Tailscale Funnel for normal DebriPod access unless you intentionally want a public internet endpoint. Tailscale Serve keeps access inside your tailnet.

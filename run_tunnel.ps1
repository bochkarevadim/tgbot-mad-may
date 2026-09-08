# Wrapper: opens a public HTTPS tunnel to the local web form (port 8080) via
# serveo.net (SSH reverse tunnel, no account/signup needed). Cloudflare Tunnel
# does not work on this network (Argo/QUIC port 7844 is blocked), so this is
# the fallback. serveo.log is overwritten fresh on every (re)start and its
# "Forwarding HTTP traffic from ..." line has the current public URL - the
# URL is random and changes every time this restarts.
#
# serveo's anonymous forwarding silently expires after a while (the ssh
# process keeps running but traffic stops working - it does not exit, so
# Task Scheduler's restart-on-failure never fires on its own). To guard
# against that, this wrapper force-restarts the tunnel every 30 minutes.

$ProjectDir = $PSScriptRoot
$LogFile = Join-Path $ProjectDir "serveo.log"
$ErrFile = Join-Path $ProjectDir "serveo_err.log"

$p = Start-Process -FilePath "ssh.exe" `
    -ArgumentList "-o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 80:localhost:8080 serveo.net" `
    -WorkingDirectory $ProjectDir `
    -RedirectStandardOutput $LogFile `
    -RedirectStandardError $ErrFile `
    -NoNewWindow -PassThru

$p.WaitForExit(30 * 60 * 1000) | Out-Null

if (-not $p.HasExited) {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}

# Always exit non-zero so Task Scheduler's "restart on failure" relaunches
# this script - both on an ssh crash and on our own 30-minute refresh.
exit 1

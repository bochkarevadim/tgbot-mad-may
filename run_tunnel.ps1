# Wrapper: opens a public HTTPS tunnel to the local web form (port 8080) via
# serveo.net (SSH reverse tunnel, no account/signup needed). Cloudflare Tunnel
# does not work on this network (Argo/QUIC port 7844 is blocked), so this is
# the fallback. serveo.log is overwritten fresh on every (re)start and its
# "Forwarding HTTP traffic from ..." line has the current public URL - the
# URL is random and changes every time this restarts.

$ProjectDir = $PSScriptRoot
$LogFile = Join-Path $ProjectDir "serveo.log"
$ErrFile = Join-Path $ProjectDir "serveo_err.log"

Start-Process -FilePath "ssh.exe" `
    -ArgumentList "-o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 80:localhost:8080 serveo.net" `
    -WorkingDirectory $ProjectDir `
    -RedirectStandardOutput $LogFile `
    -RedirectStandardError $ErrFile `
    -NoNewWindow -Wait

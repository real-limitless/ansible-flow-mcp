# Lab-only: enable WinRM HTTP for hub Ansible (NTLM). Not for production.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

Write-Host "== ansible-flow lab: enable WinRM =="

# Long paths / basic hardening off for lab speed
try {
  Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -Type DWord -Force -ErrorAction SilentlyContinue
} catch {}

Enable-PSRemoting -Force -SkipNetworkProfileCheck

# Prefer HTTP 5985 for lab (hub uses ansible_winrm_scheme=http)
winrm quickconfig -q -force 2>$null
winrm set winrm/config/service '@{AllowUnencrypted="true"}'
winrm set winrm/config/service/auth '@{Basic="true"}'
winrm set winrm/config/service/auth '@{Negotiate="true"}'
winrm set winrm/config/client/auth '@{Basic="true"}'
winrm set winrm/config/winrs '@{MaxMemoryPerShellMB="1024"}'

# Firewall
New-NetFirewallRule -DisplayName "Ansible WinRM HTTP" -Direction Inbound -LocalPort 5985 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue | Out-Null
New-NetFirewallRule -DisplayName "Ansible WinRM HTTPS" -Direction Inbound -LocalPort 5986 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue | Out-Null

# Network profile: Private helps WinRM on some SKUs
try {
  Get-NetConnectionProfile | ForEach-Object {
    try { Set-NetConnectionProfile -InterfaceIndex $_.InterfaceIndex -NetworkCategory Private -ErrorAction SilentlyContinue } catch {}
  }
} catch {}

# Ready marker (also on Shared Z: when samba is up)
$marker = "C:\OEM\WINRM_READY"
"ready $(Get-Date -Format o)" | Set-Content -Path $marker -Encoding ascii
if (Test-Path "Z:\") {
  try { Copy-Item $marker "Z:\WINRM_READY" -Force -ErrorAction SilentlyContinue } catch {}
}

Write-Host "WinRM ready. Marker: $marker"
winrm enumerate winrm/config/listener

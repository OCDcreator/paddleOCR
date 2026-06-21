<#
.SYNOPSIS
  一键启动 PaddleOCR LAN 服务,可选机器(Mac/Windows)、引擎、端口。

.DESCRIPTION
  从本机(Windows)一条命令启动服务:
    - Machine mac    : SSH 到 Mac mini 后台启动(nohup),返回局域网访问 URL
    - Machine windows: 本机后台启动,返回访问 URL
  引擎和端口可选;默认后台运行(-Foreground 改前台)。

.PARAMETER Machine
  必填。mac 或 windows。决定服务跑在哪台机器。

.PARAMETER Engine
  可选。rapidocr(默认,快) 或 paddleocr(纯中文精度略高)。
  实际生效优先级:本参数 > .env 里的 PADDLEOCR_ENGINE > 默认 rapidocr。

.PARAMETER Port
  可选。默认 8866。

.PARAMETER Foreground
  开关。加上则前台运行(看实时日志,Ctrl+C 停);不加则后台运行。

.EXAMPLE
  .\start.ps1 -Machine mac
  .\start.ps1 -Machine windows -Engine paddleocr -Port 9000
  .\start.ps1 -Machine mac -Foreground

.NOTES
  Mac 目标来自 ssh 配置: dht@192.168.31.215,仓库在
  /Volumes/SDD2T/obsidian-vault-write/custom-project/paddleOCR
  改这些常量请同步更新 $MacTarget / $MacRepo。
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("mac", "windows")]
    [string]$Machine,

    [ValidateSet("rapidocr", "paddleocr")]
    [string]$Engine = "rapidocr",

    [int]$Port = 8866,

    [switch]$Foreground
)

# --- 设备/仓库常量(改这里即可适配你的环境) ---
$MacTarget = "dht@192.168.31.215"
$MacRepo = "/Volumes/SDD2T/obsidian-vault-write/custom-project/paddleOCR"
$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "    $msg" -ForegroundColor Green }

# --- 启动后的就绪探测:轮询 /health 直到 200 或超时 ---
function Wait-Ready($BaseUrl, $TimeoutSec = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/health" -TimeoutSec 3
            if ($r.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Seconds 1
    }
    return $false
}

if ($Machine -eq "mac") {
    Write-Step "通过 SSH 在 Mac($MacTarget) 启动"
    Write-Step "引擎=$Engine 端口=$Port $(if ($Foreground) { '前台' } else { '后台' })"

    # 远端脚本:进入仓库,设环境变量,后台或前台启动。
    # 用 PADDLEOCR_* 环境变量覆盖引擎/端口,不依赖远端 .env。
    $remoteMode = if ($Foreground) { "" } else { "nohup" }
    $remoteBg = if ($Foreground) { "" } else { "&" }
    $remoteRedirect = if ($Foreground) { "" } else { ">$MacRepo/logs/lan-service.out 2>&1 &" }

    $remoteScript = @"
set -e
cd '$MacRepo'
mkdir -p logs
export PADDLEOCR_ENGINE='$Engine'
export PADDLEOCR_SERVICE_PORT='$Port'
$remoteMode uv run paddleocr-lan-service $remoteRedirect
echo "MAC_PID=`$!"
"@

    $b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($remoteScript.Replace("`r`n", "`n")))
    ssh -o BatchMode=yes -o ConnectTimeout=10 $MacTarget "printf '%s' '$b64' | /usr/bin/base64 -D | /bin/zsh -s"
    if ($LASTEXITCODE -ne 0) { throw "Mac SSH 启动失败 (exit $LASTEXITCODE)。检查 Mac 是否开机、SSH 密钥是否可用。" }

    $lanIp = ($MacTarget -split "@")[1]
    $url = "http://${lanIp}:$Port"
    Write-Step "等待服务就绪(最长 60 秒,首次要下载/加载模型可能更久)..."
    if (Wait-Ready $url) {
        Write-Ok "服务已就绪"
        Write-Host ""
        Write-Host "  浏览器工作台 : $url/" -ForegroundColor Yellow
        Write-Host "  健康检查     : $url/health" -ForegroundColor Yellow
        Write-Host "  引擎         : $Engine"
        Write-Host ""
        if (-not $Foreground) {
            Write-Host "  (后台运行。停服务: ssh $MacTarget 'pkill -f paddleocr-lan-service')" -ForegroundColor DarkGray
        }
    } else {
        Write-Warning "60 秒内未就绪。可能是首次下载模型。稍后再试 $url/health"
        Write-Host "  查日志: ssh $MacTarget 'tail -30 $MacRepo/logs/lan-service.out'" -ForegroundColor DarkGray
    }
}
elseif ($Machine -eq "windows") {
    Write-Step "在 Windows 本机启动"
    Write-Step "引擎=$Engine 端口=$Port $(if ($Foreground) { '前台' } else { '后台' })"

    $env:PADDLEOCR_ENGINE = $Engine
    $env:PADDLEOCR_SERVICE_PORT = "$Port"

    if ($Foreground) {
        Write-Step "前台运行中(Ctrl+C 停止)"
        uv run paddleocr-lan-service
        return
    }

    # 后台:Start-Process 起新窗口隐藏的进程,日志写文件(stdout 和 stderr
    # 必须是不同的文件路径,否则 Start-Process 报错)。
    $logDir = Join-Path $PSScriptRoot "logs"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $outFile = Join-Path $logDir "lan-service.out"
    $errFile = Join-Path $logDir "lan-service.err"
    $procArgs = @{
        FilePath               = "uv"
        ArgumentList           = @("run", "paddleocr-lan-service")
        WindowStyle            = "Hidden"
        RedirectStandardOutput = $outFile
        RedirectStandardError  = $errFile
        PassThru               = $true
    }
    $proc = Start-Process @procArgs
    Write-Ok "后台进程 PID=$($proc.Id),日志 $logFile"

    $url = "http://127.0.0.1:$Port"
    Write-Step "等待服务就绪(最长 60 秒)..."
    if (Wait-Ready $url) {
        Write-Ok "服务已就绪"
        Write-Host ""
        Write-Host "  本机浏览器     : $url/" -ForegroundColor Yellow
        Write-Host "  局域网其他设备 : http://192.168.31.148:$Port/" -ForegroundColor Yellow
        Write-Host "  健康检查       : $url/health" -ForegroundColor Yellow
        Write-Host "  引擎           : $Engine"
        Write-Host ""
        Write-Host "  (停服务: Stop-Process -Id $($proc.Id),或任务管理器找 uv/uvicorn)" -ForegroundColor DarkGray
    } else {
        Write-Warning "60 秒内未就绪。查日志: $outFile / $errFile"
    }
}

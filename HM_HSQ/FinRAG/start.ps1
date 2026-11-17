param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$frontendRoot = Join-Path $projectRoot 'frontend'
$runtimeRoot = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null

function Test-Endpoint([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Wait-Endpoint([string]$Url, [System.Diagnostics.Process]$Process, [string]$LogPath) {
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        if (Test-Endpoint $Url) { return }
        if ($Process.HasExited) { throw "服务启动失败，请查看 $LogPath" }
        Start-Sleep -Milliseconds 500
    }
    throw "服务启动超时，请查看 $LogPath"
}

$startedProcesses = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()
try {
    # Reuse this project's named container and existing development services.
    $docker = Get-Command docker.exe -ErrorAction Stop
    & $docker.Source info --format '{{.ServerVersion}}' *> $null
    if ($LASTEXITCODE -ne 0) {
        $desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
        if (-not (Test-Path -LiteralPath $desktop)) { throw '请先安装并启动 Docker Desktop' }
        Start-Process -FilePath $desktop -WindowStyle Hidden
        $dockerDeadline = (Get-Date).AddSeconds(120)
        do {
            Start-Sleep -Seconds 2
            & $docker.Source info --format '{{.ServerVersion}}' *> $null
        } while ($LASTEXITCODE -ne 0 -and (Get-Date) -lt $dockerDeadline)
        if ($LASTEXITCODE -ne 0) { throw 'Docker 尚未就绪，请启动 Docker Desktop 后重试' }
    }
    & $docker.Source inspect finrag-milvus *> $null
    if ($LASTEXITCODE -ne 0) { throw '未找到 finrag-milvus 容器，请按 README 准备 Milvus 服务' }
    & $docker.Source start finrag-milvus *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Milvus 启动失败' }
    $milvusDeadline = (Get-Date).AddSeconds(120)
    while (-not (Test-Endpoint 'http://127.0.0.1:9091/healthz')) {
        if ((Get-Date) -gt $milvusDeadline) { throw 'Milvus 健康检查超时，请查看 docker logs finrag-milvus' }
        Start-Sleep -Seconds 1
    }
    Write-Host 'Milvus 已就绪'

    if (-not (Test-Endpoint 'http://127.0.0.1:8010/api/health')) {
        if (Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue) {
            throw '8010 端口被其他服务占用'
        }
        $python = $env:RAG_PYTHON
        if (-not $python) {
            $python = 'E:\ProgrammingLanguage\Python\Anaconda3\Anaconda3-2024\anaconda3\envs\EduRAG_GANG\python.exe'
        }
        if (-not (Test-Path -LiteralPath $python)) { throw '请通过 RAG_PYTHON 指定已安装项目依赖的 Python 路径' }
        $backendLog = Join-Path $runtimeRoot 'backend.error.log'
        $backend = Start-Process -FilePath $python -ArgumentList @('-X', 'utf8', 'run_api.py') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeRoot 'backend.log') -RedirectStandardError $backendLog
        $startedProcesses.Add($backend)
        Wait-Endpoint 'http://127.0.0.1:8010/api/health' $backend $backendLog
    }
    Write-Host 'FastAPI 已就绪'

    if (-not (Test-Endpoint 'http://127.0.0.1:5173/src/main.js')) {
        if (Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue) {
            throw '5173 端口被其他服务占用'
        }
        $node = (Get-Command node.exe -ErrorAction Stop).Source
        $vite = Join-Path $frontendRoot 'node_modules\vite\bin\vite.js'
        if (-not (Test-Path -LiteralPath $vite)) { throw '请先进入 frontend 执行 npm ci 安装前端依赖' }
        $frontendLog = Join-Path $runtimeRoot 'frontend.error.log'
        $frontend = Start-Process -FilePath $node -ArgumentList @(('"' + $vite + '"'), '--host', '127.0.0.1') -WorkingDirectory $frontendRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeRoot 'frontend.log') -RedirectStandardError $frontendLog
        $startedProcesses.Add($frontend)
        Wait-Endpoint 'http://127.0.0.1:5173/src/main.js' $frontend $frontendLog
    }
    Write-Host 'Vue 前端已就绪'
    Write-Host 'FinRAG 已启动 http://127.0.0.1:5173'
    if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:5173' }
} catch {
    foreach ($process in $startedProcesses) {
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -ErrorAction SilentlyContinue }
    }
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

$ErrorActionPreference = 'Stop'
$runtimePython = 'E:\ProgrammingLanguage\Python\Anaconda3\Anaconda3-2024\anaconda3\envs\EduRAG_GANG\python.exe'
Push-Location -LiteralPath $PSScriptRoot
try {
    & $runtimePython -X utf8 run_api.py
} finally {
    Pop-Location
}

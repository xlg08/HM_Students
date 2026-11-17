param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ProjectArguments
)
$ErrorActionPreference = 'Stop'
$runtimePython = 'E:\ProgrammingLanguage\Python\Anaconda3\Anaconda3-2024\anaconda3\envs\EduRAG_GANG\python.exe'
$bootstrap = @'
import os
import sys
from urllib.parse import urlsplit

user_paths = [path for path in sys.path if 'AppData' in path and 'site-packages' in path]
sys.path[:] = [path for path in sys.path if path not in user_paths] + user_paths

from base import Config
from new_main import main

host = urlsplit(Config().DASHSCOPE_BASE_URL).hostname
existing = os.environ.get('NO_PROXY') or os.environ.get('no_proxy', '')
os.environ['NO_PROXY'] = ','.join(filter(None, [existing, host, 'localhost', '127.0.0.1']))
main()
'@
Push-Location -LiteralPath $PSScriptRoot
try {
    & $runtimePython -X utf8 -c $bootstrap @ProjectArguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}


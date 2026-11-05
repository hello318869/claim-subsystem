param(
    [ValidateSet('Start', 'Stop', 'Status')]
    [string]$Action = 'Start'
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$expectedRoot = [IO.Path]::GetFullPath('D:\软工大作业\claim-subsystem')
if ($projectRoot -ne $expectedRoot) {
    throw 'This task-specific script must remain inside its original project.'
}
$devEnvPath = Join-Path $projectRoot '.env'
$testEnvPath = Join-Path $projectRoot '.env.test'
$utf8 = [Text.UTF8Encoding]::new($false)
$OutputEncoding = $utf8
$applicationPassword = ''

function New-TaskSecret([int]$ByteCount) {
    $bytes = New-Object byte[] $ByteCount
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return -join ($bytes | ForEach-Object { $_.ToString('x2') })
}

if ($Action -eq 'Start') {
    if (Test-Path -LiteralPath $devEnvPath) {
        $existing = [IO.File]::ReadAllText($devEnvPath, $utf8)
        $passwordMatch = [regex]::Match($existing, '(?m)^DATABASE_URL=mysql\+pymysql://claim_app:([a-f0-9]{48})@127\.0\.0\.1:33307/claim_dev\?charset=utf8mb4\r?$')
        $secretMatch = [regex]::Match($existing, '(?m)^AUTH_SECRET=([a-f0-9]{64})\r?$')
        if (-not $passwordMatch.Success -or -not $secretMatch.Success) {
            throw 'Existing .env does not match this isolated instance. It was not overwritten.'
        }
        $applicationPassword = $passwordMatch.Groups[1].Value
        $authenticationSecret = $secretMatch.Groups[1].Value
    } else {
        $applicationPassword = New-TaskSecret 24
        $authenticationSecret = New-TaskSecret 32
        $devUrl = 'mysql+pymysql://claim_app:' + $applicationPassword + '@127.0.0.1:33307/claim_dev?charset=utf8mb4'
        $testUrl = 'mysql+pymysql://claim_app:' + $applicationPassword + '@127.0.0.1:33307/claim_test?charset=utf8mb4'
        $content = "DATABASE_URL=$devUrl`nTEST_DATABASE_URL=$testUrl`nAUTH_SECRET=$authenticationSecret`nDEMO_MODE=true`n"
        [IO.File]::WriteAllText($devEnvPath, $content, $utf8)
    }
    $testUrl = 'mysql+pymysql://claim_app:' + $applicationPassword + '@127.0.0.1:33307/claim_test?charset=utf8mb4'
    $testContent = "DATABASE_URL=$testUrl`nTEST_DATABASE_URL=$testUrl`nAUTH_SECRET=$authenticationSecret`nDEMO_MODE=true`n"
    if (Test-Path -LiteralPath $testEnvPath) {
        if ([IO.File]::ReadAllText($testEnvPath, $utf8).Replace("`r`n", "`n") -ne $testContent) {
            throw 'Existing .env.test differs from the isolated instance. It was not overwritten.'
        }
    } else {
        [IO.File]::WriteAllText($testEnvPath, $testContent, $utf8)
    }
}

$payload = @{
    action = $Action.ToLowerInvariant()
    application_password = $applicationPassword
} | ConvertTo-Json -Compress
$encodedPayload = [Convert]::ToBase64String($utf8.GetBytes($payload))

$pythonScript = @'
import base64
import json
import os
import pathlib
import secrets
import signal
import socket
import subprocess
import time

payload = json.loads(base64.b64decode('__PAYLOAD_B64__'))
base = pathlib.Path('/tmp/se-claim-20261105-44cc3b4f')
data = base / 'data'
sock = base / 'mysql.sock'
pid_file = base / 'mysql.pid'
log_file = base / 'mysql.log'
admin_file = base / 'admin-password'
mysql = '/usr/bin/mysql'
mysqld = '/usr/sbin/mysqld'
port = 33307

def require_safe_base():
    if str(base) != '/tmp/se-claim-20261105-44cc3b4f' or base.is_symlink():
        raise RuntimeError('Unsafe instance directory.')
    if base.exists() and (base.resolve() != base or base.stat().st_uid != os.getuid()):
        raise RuntimeError('Instance directory owner or resolved path differs.')
    if data.is_symlink() or (data.exists() and data.resolve() != data):
        raise RuntimeError('Unsafe data directory.')

def owned_server_pid():
    if not pid_file.exists():
        return None
    if pid_file.is_symlink():
        raise RuntimeError('Unsafe PID file.')
    raw = pid_file.read_text().strip()
    if not raw.isdecimal() or int(raw) <= 1:
        raise RuntimeError('Invalid PID file.')
    pid = int(raw)
    proc = pathlib.Path('/proc') / raw
    if not proc.exists():
        return None
    args = (proc / 'cmdline').read_bytes().split(b'\0')
    expected_data = ('--datadir=' + str(data)).encode()
    expected_socket = ('--socket=' + str(sock)).encode()
    if expected_data not in args or expected_socket not in args:
        raise RuntimeError('PID does not identify this task data directory and socket.')
    if (proc / 'exe').resolve() != pathlib.Path(mysqld).resolve():
        raise RuntimeError('PID executable is not the expected MySQL server.')
    if proc.stat().st_uid != os.getuid():
        raise RuntimeError('PID is owned by another user.')
    return pid

def run_sql(sql, password):
    env = os.environ.copy()
    env['MYSQL_PWD'] = password
    result = subprocess.run(
        [mysql, '--no-defaults', '--protocol=SOCKET', '--socket=' + str(sock),
         '--user=root', '--batch', '--skip-column-names'],
        input=sql, text=True, capture_output=True, env=env, timeout=20)
    if result.returncode != 0:
        raise RuntimeError('Task-local MySQL SQL operation failed; no credentials were printed.')
    return result.stdout.strip()

require_safe_base()
action = payload['action']
if action == 'status':
    pid = owned_server_pid() if base.exists() else None
    print(json.dumps({'state': 'running' if pid else 'stopped', 'port': port,
                      'pid': pid, 'datadir': str(data)}))
elif action == 'stop':
    pid = owned_server_pid() if base.exists() else None
    if pid is None:
        print(json.dumps({'state': 'stopped', 'port': port, 'datadir': str(data)}))
    else:
        if not admin_file.is_file() or admin_file.is_symlink():
            raise RuntimeError('Missing task-local admin secret; refusing to stop an unverified server.')
        password = admin_file.read_text().strip()
        try:
            run_sql('SHUTDOWN;', password)
        except RuntimeError:
            # Revalidate identity immediately before a task-scoped graceful signal.
            if owned_server_pid() == pid:
                os.kill(pid, signal.SIGTERM)
        for _ in range(200):
            proc_path = pathlib.Path('/proc') / str(pid)
            if not proc_path.exists():
                break
            try:
                if (proc_path / 'stat').read_text().split(') ', 1)[1].split()[0] == 'Z':
                    break
            except FileNotFoundError:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError('Task server did not stop; no force-kill was attempted.')
        print(json.dumps({'state': 'stopped', 'port': port, 'datadir': str(data)}))
elif action == 'start':
    application_password = payload['application_password']
    if len(application_password) != 48 or any(c not in '0123456789abcdef' for c in application_password):
        raise RuntimeError('Invalid task-specific application credential.')
    base.mkdir(mode=0o700, parents=False, exist_ok=True)
    require_safe_base()
    if not (data / 'auto.cnf').exists():
        if data.exists() and any(data.iterdir()):
            raise RuntimeError('Unrecognized nonempty task datadir; refusing to initialize over it.')
        data.mkdir(mode=0o700, exist_ok=True)
        init = subprocess.run(
            [mysqld, '--no-defaults', '--initialize-insecure', '--datadir=' + str(data),
             '--log-error=' + str(base / 'initialize.log')],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        if init.returncode:
            raise RuntimeError('Task-local MySQL initialization failed; see initialize.log.')
    pid = owned_server_pid()
    if pid is None:
        probe = socket.socket()
        try:
            # Match MySQL's reusable listener; TIME_WAIT from the previous
            # verified shutdown must not be mistaken for a live other server.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', port))
        finally:
            probe.close()
        proc = subprocess.Popen(
            [mysqld, '--no-defaults', '--datadir=' + str(data), '--socket=' + str(sock),
             '--pid-file=' + str(pid_file), '--log-error=' + str(log_file),
             '--port=' + str(port), '--bind-address=127.0.0.1', '--mysqlx=0',
             '--skip-name-resolve', '--innodb-buffer-pool-size=64M',
             '--max-connections=30', '--performance-schema=OFF'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        for _ in range(300):
            if proc.poll() is not None:
                raise RuntimeError('Task-local MySQL exited during startup; see mysql.log.')
            if sock.exists() and owned_server_pid() == proc.pid:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError('Timed out waiting for the task-local MySQL socket.')
    if admin_file.exists():
        if admin_file.is_symlink() or admin_file.stat().st_uid != os.getuid():
            raise RuntimeError('Unsafe task admin secret file.')
        admin_password = admin_file.read_text().strip()
        run_sql('SELECT 1;', admin_password)
    else:
        admin_password = secrets.token_hex(24)
        # The root account is secured immediately after the private instance starts.
        run_sql("ALTER USER 'root'@'localhost' IDENTIFIED BY '" + admin_password + "';", '')
        fd = os.open(admin_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(admin_password + '\n')
    sql = "CREATE DATABASE IF NOT EXISTS claim_dev CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n"
    sql += "CREATE DATABASE IF NOT EXISTS claim_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n"
    for host in ('localhost', '127.0.0.1'):
        account = "'claim_app'@'" + host + "'"
        sql += 'CREATE USER IF NOT EXISTS ' + account + " IDENTIFIED BY '" + application_password + "';\n"
        sql += 'ALTER USER ' + account + " IDENTIFIED BY '" + application_password + "';\n"
        sql += 'GRANT ALL PRIVILEGES ON claim_dev.* TO ' + account + ';\n'
        sql += 'GRANT ALL PRIVILEGES ON claim_test.* TO ' + account + ';\n'
    run_sql(sql, admin_password)
    version = run_sql('SELECT VERSION();', admin_password)
    print(json.dumps({'state': 'running', 'version': version, 'port': port,
                      'pid': owned_server_pid(), 'datadir': str(data),
                      'databases': ['claim_dev', 'claim_test'], 'user': 'claim_app'}))
else:
    raise RuntimeError('Unknown action.')
'@

$pythonScript = $pythonScript.Replace('__PAYLOAD_B64__', $encodedPayload)
$pythonScript | & wsl.exe -d Ubuntu -- python3 -
if ($LASTEXITCODE -ne 0) {
    throw "Task-local MySQL $Action failed."
}

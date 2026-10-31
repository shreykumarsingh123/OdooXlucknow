# Machine setup

Run these in PowerShell. Status describes the main dev machine as first checked on 2026-10-31 (Windows 11, 7.7 GB RAM, 324 GB free). Steps 1 and 2 have since been done on that machine, and teammates still need them.

## Status

| Tool | Status | Action |
|------|--------|--------|
| Git 2.56 | Installed | None |
| VS Code 1.144 with Python extensions | Installed | None |
| MySQL Server 8.0.46 and Workbench | Installed, service running on port 3306 | Add to PATH, create the project database |
| Python 3.14.2 | Installed at `C:\Python314`, not on PATH | Add to PATH |
| Node.js 20.20.2, npm 10.8 | Installed, but Node 20 is past end of life | Upgrade recommended |
| Django, DRF, MySQL driver | Not installed | Install in a virtual environment |
| GitHub CLI | Missing | Install |
| Docker, PostgreSQL, wkhtmltopdf | Missing, and WSL is broken | Only needed for Odoo |

## 1. Fix PATH

```powershell
$p = [Environment]::GetEnvironmentVariable('Path','User'); [Environment]::SetEnvironmentVariable('Path',"C:\Python314;C:\Python314\Scripts;C:\Program Files\MySQL\MySQL Server 8.0\bin;$p",'User')
```

Open a new terminal, then check that `python --version` prints 3.14.2. If it still mentions the Microsoft Store, turn off the `python.exe` and `python3.exe` aliases in Settings > Apps > Advanced app settings > App execution aliases.

## 2. Install missing tools

```powershell
winget install --id GitHub.cli --exact
```

```powershell
winget install --id OpenJS.NodeJS.LTS --exact
```

After upgrading Node, remove the old `C:\nodejs\node-v20.11.0-win-x64` entry from PATH.

## 3. Create the project database

You need the MySQL root password set during installation. If it is lost, reset it using the MySQL manual before the event.

```powershell
mysql -u root -p
```

Then run this, using your own password. Put the same password in `.env`.

```sql
CREATE DATABASE odooxlko CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'odooxlko'@'localhost' IDENTIFIED BY 'choose-a-password';
GRANT ALL PRIVILEGES ON odooxlko.* TO 'odooxlko'@'localhost';
GRANT ALL PRIVILEGES ON test_odooxlko.* TO 'odooxlko'@'localhost';
```

## 4. Backend packages

Run from the repo root once `backend/` exists. These resolved on Python 3.14 with prebuilt Windows wheels in a dry run, including `mysqlclient`, so no C compiler is needed.

```powershell
python -m venv .venv
```

```powershell
.venv\Scripts\Activate.ps1
```

```powershell
pip install "django>=5.2,<5.3" djangorestframework djangorestframework-simplejwt django-cors-headers django-filter mysqlclient python-dotenv pytest-django ruff
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

## 5. Accounts

- GitHub: run `gh auth login`.
- Hosting: only if the submission needs a live URL. See `/deploy-app`.

## Claude Code shortcuts

Availability can differ between the terminal, desktop and web versions.

| Shortcut | Use |
|----------|-----|
| `!command` | Run a shell command directly, with its output visible to Claude |
| `/btw` | Ask a quick side question without disturbing the main task |
| `/context` | Check context usage before starting a major task |
| Teleport and Remote Control | Move or continue a session on another device |

## Only if the event requires Odoo

Odoo runs on PostgreSQL only, so MySQL cannot be used. This machine has 7.7 GB of RAM, which is tight for Docker plus Odoo plus a browser and editor.

Check the problem statement first. Then either:

- **Native install (lighter):**

  ```powershell
  winget install --id PostgreSQL.PostgreSQL.17 --exact
  ```

  ```powershell
  winget install --id wkhtmltopdf.wkhtmltox --exact
  ```

  Check the Python version your Odoo release supports. Python 3.14 may be too new, and `Python.Python.3.12` is available alongside it through winget.

- **Docker:** WSL currently fails with `Wsl/CallMsi/Install/REGDB_E_CLASSNOTREG` and must be repaired first. Try `wsl --install` in an administrator terminal, then:

  ```powershell
  winget install --id Docker.DockerDesktop --exact
  ```

Allow time for this before the event, because the first Odoo install is slow.

# Manual install

Use the install scripts from the main README unless you need a manual development setup or need to debug dependency installation.

DebriPod needs Git, Python 3 with virtual environment support, pip, ffmpeg, and ffprobe. The app runs from a Python virtual environment inside the repo folder.

## Windows

Install Git, Python 3.12, and ffmpeg. Then open PowerShell and run:

```powershell
git clone https://github.com/JoeDoe56/Debripod.git debripod
cd debripod
py -3 -m venv --prompt debripod .debripod-venv
.\.debripod-venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e .
python -m debripod.app
```

## macOS

Install Homebrew, Git, Python, and ffmpeg. Then open Terminal and run:

```sh
git clone https://github.com/JoeDoe56/Debripod.git debripod
cd debripod
python3 -m venv --prompt debripod .debripod-venv
. .debripod-venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e .
python -m debripod.app
```

## Linux

Install Git, Python 3 with venv support, pip, and ffmpeg through your package manager. The automatic installer supports apt, dnf, yum, pacman, zypper, apk, xbps, Portage, Nix, and Linuxbrew. For a manual install, install the equivalent packages for your distribution, then run:

```bash
git clone https://github.com/JoeDoe56/Debripod.git debripod
cd debripod
python3 -m venv --prompt debripod .debripod-venv
. .debripod-venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e .
python -m debripod.app
```

## Running again

Windows:

```powershell
cd debripod
.\.debripod-venv\Scripts\Activate.ps1
python -m debripod.app
```

macOS or Linux:

```bash
cd debripod
. .debripod-venv/bin/activate
python -m debripod.app
```

Then open `http://127.0.0.1:8083` in a browser. If you changed `PORT` in `config/debripod.local.json`, use that port instead.

## Updating manually

From inside the `debripod` folder, pull the latest code and refresh the virtual environment packages.

```bash
git pull --ff-only
. .debripod-venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e .
python -m debripod.app
```

On Windows, activate with `.\.debripod-venv\Scripts\Activate.ps1` instead of `. .debripod-venv/bin/activate`.

## Notes

If `ffmpeg -version` works but `ffprobe -version` does not, reinstall ffmpeg or install the ffmpeg package from a fuller multimedia repository for your distribution.

Keep local config, data, downloads, caches, virtual environments, and logs out of Git.

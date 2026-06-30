## System Setup and Prerequisites 

- a. You'll need to install [python](https://www.python.org/downloads/)
  - After the installation make sure the [python enviroment variable is set](https://realpython.com/add-python-to-path/).
- b. Also, You'll need an IDE (Integrated Development Environment), we recommend to install [MS VS code](https://code.visualstudio.com/)
- d. We alse recommend to install extensions such as:
  - [Python](https://marketplace.visualstudio.com/items?itemName=ms-python.python) (required): Provides Python language support, debugging, environment selection, and IntelliSense in VS Code.
  - [edit CSV](https://marketplace.visualstudio.com/items?itemName=janisdd.vscode-edit-csv): To edit and interact with input csv files for SDOM directly in vs code.
  - [vscode-pdf](https://marketplace.visualstudio.com/items?itemName=tomoki1207.pdf): to read and see pdf files directly in vscode.


## Install SDOM

It is recommended to load the packages in a virtual enviroment. 

We recommend to use `uv`, a Python manager for virtual environments and packages.  

- a. Install `uv` following the instructions at [uv on PyPI](https://pypi.org/project/uv/).

  **Windows only — verify that `python` and `uv` are on your PATH** before creating the virtual environment. In PowerShell (or cmd) run:

  ```powershell
  where.exe python
  where.exe uv
  ```

  Each command should print a full path. If you see `INFO: Could not find files for the given pattern(s).`, the executable is not on your PATH — re-check the Python installer option *Add python.exe to PATH*, or reinstall `uv` and open a new terminal so PATH changes take effect.

  **Fix it manually (no admin required) — add the missing folders to your User PATH:**

  1. Locate the install folder(s). Common defaults are:
      - Python: `%LOCALAPPDATA%\Programs\Python\Python3xx\` and `%LOCALAPPDATA%\Programs\Python\Python3xx\Scripts\`
      - `uv`: `%USERPROFILE%\.local\bin\` (official installer) or the `Scripts` folder of the Python you used with `pip install uv`

      You can list installed Python versions with:

      ```powershell
      Get-ChildItem "$env:LOCALAPPDATA\Programs\Python" -Directory
      ```

  2. Append the folder(s) to your **User** PATH (persists across sessions, no admin needed). Edit the `$newPaths` list to match what you found in step 1, then run:

      ```powershell
      $newPaths = @(
          "$env:LOCALAPPDATA\Programs\Python\Python312",
          "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts",
          "$env:USERPROFILE\.local\bin"
      )
      $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
      $updated  = (@($userPath.TrimEnd(';')) + $newPaths) -join ';'
      [Environment]::SetEnvironmentVariable("Path", $updated, "User")
      ```

  3. **Close and reopen your terminal** (and VS Code) so the new PATH is picked up, then re-run `where.exe python` and `where.exe uv` to confirm both now resolve.

- b. Create a new virtual environment named `.venv`:

  ```bash
  uv venv .venv
  ```
        This command creates a Python virtual environment in the `.venv` directory.


- c. Activate your virtual environment and install the SDOM package:

  ```bash
  uv pip install sdom
  ```
        
- d. Install the python module according to your solver. We'll use here [HiGHS open-source solver](https://highs.dev/)

  ```bash
  uv pip install highspy
  ```

- e. Install the Logging package to be able to see sdom info, warning and error messages and log those:

  ```bash
  uv pip install logging
  ```

- f. Verify your environment by listing installed packages:

  In your terminal or powershell run:

  ```bash
  uv pip list
  ```

  You should see output similar to:

  ```bash
    Package         Version
    --------------- -----------
    contourpy       1.3.3
    cycler          0.12.1
    fonttools       4.63.0
    highspy         1.14.0
    kiwisolver      1.5.0
    matplotlib      3.10.9
    numpy           2.4.6
    packaging       26.2
    pandas          2.3.3
    pillow          12.2.0
    pyomo           6.10.0
    pyparsing       3.3.2
    python-dateutil 2.9.0.post0
    pytz            2026.2
    sdom            0.2.3
    six             1.17.0
    tzdata          2026.2
  ```
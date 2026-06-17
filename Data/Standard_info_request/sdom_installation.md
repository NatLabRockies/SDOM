## System Setup and Prerequisites 

- a. You'll need to install [python](https://www.python.org/downloads/)
  - After the installation make sure the [python enviroment variable is set](https://realpython.com/add-python-to-path/).
- b. Also, You'll need an IDE (Integrated Development Environment), we recommend to install [MS VS code](https://code.visualstudio.com/)
- d. We alse recommend to install extensions such as:
  - [edit CSV](https://marketplace.visualstudio.com/items?itemName=janisdd.vscode-edit-csv): To edit and interact with input csv files for SDOM directly in vs code.
  - [vscode-pdf](https://marketplace.visualstudio.com/items?itemName=tomoki1207.pdf): to read and see pdf files directly in vscode.


## Install SDOM

It is recommended to load the packages in a virtual enviroment. 

We recommend to use `uv`, a Python manager for virtual environments and packages.  

- a. Install `uv` following the instructions at [uv on PyPI](https://pypi.org/project/uv/).

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
@echo off
:: 1. Activate the virtual environment
call .venv\Scripts\activate

:: 2. Install/Update requirements
:: The --upgrade-strategy only switch tells pip to only install missing 
:: packages if they aren't already there.
echo Checking and installing requirements...
pip install -r requirements.txt --upgrade-strategy only

:: 3. Run the application
echo Starting application...
python -m app.ui.main_window

:: 4. Pause if the window closes due to an error
pause
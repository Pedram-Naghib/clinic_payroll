@echo off
:: 1. Activate the virtual environment
call .venv\Scripts\activate

:: 2. Install requirements (this will automatically skip what's already there)
echo Checking and installing requirements...
pip install -r requirements.txt

:: 3. Run the application
echo Starting application...
python -m app.ui.main_window

:: 4. Pause on error
pause
open virtual environment
.\venv\Scripts\Activate.ps1

python -m pip install django nepsepy


python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

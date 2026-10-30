open virtual env
.\venv\Scripts\Activate.ps1

python -m pip install django nepsepy


install dependies and setup and run
setup django

python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

check
migration run 

python manage.py makemigrations market
python manage.py migrate
python manage.py runserver

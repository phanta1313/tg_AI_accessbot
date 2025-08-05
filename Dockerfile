FROM python:3.13


WORKDIR /app


COPY requirements.txt .
RUN pip install -r requirements.txt


COPY . .

RUN alembic upgrade head

CMD ["python", "src/main.py"]

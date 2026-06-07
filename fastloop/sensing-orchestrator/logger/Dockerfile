FROM python:3.9

RUN apt -y update && apt -y upgrade

WORKDIR /app

COPY . .

RUN pip install -r ./requirements.txt

EXPOSE 8090

ENTRYPOINT [ "uvicorn", "app.main:app", "--reload", "--port", "8090", "--host", "0.0.0.0" ]
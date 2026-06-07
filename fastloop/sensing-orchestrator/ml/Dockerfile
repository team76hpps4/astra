FROM pytorch/pytorch:2.9.0-cuda13.0-cudnn9-runtime

RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libgl1 \
    && apt-get clean

WORKDIR /app

COPY . .

RUN pip install -r ./requirements.txt

EXPOSE 8080

ENTRYPOINT [ "uvicorn", "app.main:app", "--reload", "--port", "8080", "--host", "0.0.0.0" ]

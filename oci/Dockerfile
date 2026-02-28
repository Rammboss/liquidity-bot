FROM python:3.13-slim

WORKDIR /app

# Copy and install requirements
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy only the `app` folder into /app
COPY ./app /app

CMD ["python", "-m", "main"]

#EXPOSE 8000
#
## Run uvicorn with `app` as the module
#CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--log-level", "info"]

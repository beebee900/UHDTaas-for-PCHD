FROM python:3.12-slim
RUN pip install --no-cache-dir "mlflow-skinny==3.17.0" "mlflow==3.17.0" psycopg2-binary
EXPOSE 5000
CMD ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000", \
     "--backend-store-uri", "sqlite:////mlflow/mlflow.db", "--default-artifact-root", "/mlflow/artifacts"]

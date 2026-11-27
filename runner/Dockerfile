FROM python:3.12-slim

RUN pip install --no-cache-dir matplotlib==3.10.8
WORKDIR /app
COPY chart.py containment_check.py sample-sales.csv ./
ENV MPLCONFIGDIR=/tmp/matplotlib PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
CMD ["python", "/app/chart.py"]

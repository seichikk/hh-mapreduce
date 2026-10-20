FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLCONFIGDIR=/tmp/mpl

RUN pip install duckdb==1.5.6 pyarrow==26.0.0 psutil==7.2.2 matplotlib==3.11.2 boto3

RUN python -c "import duckdb; con = duckdb.connect(); con.install_extension('httpfs'); con.load_extension('httpfs'); print('httpfs установлен')" \
 && python -c "import matplotlib.pyplot; print('matplotlib готов')"

WORKDIR /app

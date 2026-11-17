FROM python:3.14
WORKDIR /app
COPY . /app
RUN pip install . -r requirements-test.txt
CMD ["pytest"]

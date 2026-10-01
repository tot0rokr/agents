# The official image ships Chromium and its system libraries but not the
# Python package; pin it to the browsers' version so the two always match.
ARG PLAYWRIGHT_VERSION=1.63.0
FROM mcr.microsoft.com/playwright/python:v${PLAYWRIGHT_VERSION}-noble
ARG PLAYWRIGHT_VERSION
RUN pip install --no-cache-dir --break-system-packages \
	"playwright==${PLAYWRIGHT_VERSION}"

# Fresh-env test container for the agents harness + INSTALLATION.md walkthrough.
#
# Build:
#     docker build -t agents-test -f test/Dockerfile .
#
# Run interactively:
#     docker run -it --rm agents-test
#
# Inside the container, follow the steps in INSTALLATION.md exactly as a
# fresh user would. Nothing about the host's ~/.claude, ~/agents, or git
# identity leaks in — the container starts with an empty $HOME.

FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG UV_VERSION=0.5.11

# Base toolchain INSTALLATION.md depends on:
#   - python3 (>=3.10 on Ubuntu 24.04) and python3-venv
#   - git for `git clone`
#   - curl + ca-certificates so we can fetch the uv installer over HTTPS
#   - bash (already present, listed for clarity)
#   - jq + rsync used by render-mcp.sh / install.py
#   - less + nano so the maintainer can poke at files while exec'd in
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-venv \
        git \
        curl ca-certificates \
        bash \
        jq rsync \
        less nano \
        sudo \
    && rm -rf /var/lib/apt/lists/*

# Non-root user so the test environment matches a typical workstation.
RUN useradd -m -s /bin/bash agent \
    && echo 'agent ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/agent

USER agent
WORKDIR /home/agent
ENV HOME=/home/agent

# Install uv (provides `uvx`) into the agent user's local bin so the
# INSTALLATION.md Step 5 snippet `command = "uvx"` works without setup.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH=/home/agent/.local/bin:$PATH

# Sanity probe: confirm everything is on PATH at build time.
RUN python3 --version \
    && git --version \
    && uv --version \
    && bash --version | head -1

CMD ["bash", "-l"]

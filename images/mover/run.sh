curl -sSL https://install.python-poetry.org | python3 -
export PATH=$PATH:$HOME/.local/bin

poetry install
poetry run python3 src/main.py
deactivate
conda deactivate
echo $PATH
docker compose down
docker compose up -d
export TOX_PY39_BASE="$HOME/.asdf/installs/python/3.9.21/bin/python"
export TOX_PY310_BASE="$HOME/.asdf/installs/python/3.10.16/bin/python"
export TOX_PY311_BASE="$HOME/.asdf/installs/python/3.11.11/bin/python"
export TOX_PY312_BASE="$HOME/.asdf/installs/python/3.12.9/bin/python"
export TOX_PY313_BASE="$HOME/.asdf/installs/python/3.13.2/bin/python"
tox -p

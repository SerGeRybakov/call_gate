project='./call_gate'
echo
echo "======= SSORT ======="
ssort ${project}
echo
echo "======= RUFF FORMAT ======="
ruff format .
echo
echo "======= RUFF LINT ======="
ruff check ${project} --fix
echo
echo "======= MYPY ======="
mypy ${project} --install-types
echo

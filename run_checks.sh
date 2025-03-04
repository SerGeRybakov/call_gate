project='./call_gate'
echo
echo "======= SSORT ======="
ssort ${project}
echo
echo "======= RUFF FORMAT ======="
ruff format ${project}
ruff format ./tests
echo
echo "======= RUFF LINT ======="
ruff check ${project} --fix
ruff check ./tests --fix
echo
echo "======= MYPY ======="
mypy ${project} --install-types
echo

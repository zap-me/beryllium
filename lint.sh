#!/bin/bash

set -e

what=$1
if [ -z "$what" ]; then
	what=all
fi
echo "## lint $what ##"

if [[ "$what" =~ ^(all|html)$ ]]; then 
	echo '# linting html files with djlint..'
	djlint --version
	djlint --ignore H029,H006,H021,H030,H031,H020 --lint --extension html src/templates
	djlint --check --extension html src/templates
fi

if [[ "$what" =~ ^(all|js)$ ]]; then 
	echo '# linting js files with eslint..'
	npx eslint 'src/static/assets/js_custom/*'
fi

if [[ "$what" =~ ^(all|python)$ ]]; then 
	# see https://www.flake8rules.com/ for description of rules
	echo '# linting python files with pycodestyle..'
	pycodestyle --version
	# TODO review and remove some ignores
	(cd src && pycodestyle --statistics --ignore E265,E501,E302,E305,W504 `ls|grep .py$|xargs`)

	#echo '# linting python files with mypy..'
	#mypy --version
	#mypy src/app.py --ignore-missing-imports

	echo '# linting python files with pyright..'
	pyright --version
	pyright
fi

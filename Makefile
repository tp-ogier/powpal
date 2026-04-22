SHELL := /bin/bash

.PHONY: publish-map

publish-map:
	jupyter nbconvert --to notebook --execute --inplace interactive_map.ipynb
	git add docs/index.html interactive_map.ipynb
	@if git diff --cached --quiet; then \
		echo "No map changes to commit."; \
	else \
		git commit -m "Update Folium map"; \
	fi
	git push

PLUGIN := OptiScaler
PLUGIN_DIR := $(HOME)/homebrew/plugins/$(PLUGIN)
PAYLOAD := plugin.json package.json main.py py_modules assets dist LICENSE README.md

.PHONY: build package install clean

build:
	pnpm install --frozen-lockfile
	pnpm run build

package: build
	rm -rf build/$(PLUGIN) build/$(PLUGIN).zip
	mkdir -p build/$(PLUGIN)
	cp -r $(PAYLOAD) build/$(PLUGIN)/
	find build/$(PLUGIN) -name __pycache__ -type d -prune -exec rm -rf {} +
	python3 -c "import shutil; shutil.make_archive('build/$(PLUGIN)', 'zip', 'build', '$(PLUGIN)')"
	@echo "built build/$(PLUGIN).zip"

# Decky owns ~/homebrew/plugins, so installing needs root.
install: build
	sudo rm -rf "$(PLUGIN_DIR)"
	sudo mkdir -p "$(PLUGIN_DIR)"
	sudo cp -r $(PAYLOAD) "$(PLUGIN_DIR)/"
	sudo chown -R root:root "$(PLUGIN_DIR)"
	sudo systemctl restart plugin_loader
	@echo "installed; Decky restarted"

clean:
	rm -rf dist build

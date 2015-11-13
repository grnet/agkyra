import os
import json
import agkyra

VERSION = agkyra.__version__
SRC = "nwgui_package.json"
DIST = os.path.join("agkyra", "resources", "nwgui", "package.json")

def main():
    with open(SRC) as f:
        d = json.load(f)

    d['version'] = agkyra.__version__

    with open(DIST, 'w') as f:
        json.dump(d, f)


if __name__ == '__main__':
    main()
